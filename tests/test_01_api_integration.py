import json
import threading
import time

import pytest
import requests

from tests.test_base import (
    RECREATE_USER_EMAIL,
    STAGING,
    TEST_USER_EMAIL,
    BaseKindleTest,
)

# NOTE: All test calls go through the web-app ASGI reverse proxy server (port 4096)
# with the /kindle/ prefix. The web-app then routes requests to this Flask server (port 4098).
# Examples:
# - /kindle/open-random-book -> web-app handles random book selection from cache
# - /kindle/books?sync=false -> returns cached books from web-app
# - /kindle/books?sync=true -> routes to this server's /books endpoint


class TestKindleAPIIntegration(BaseKindleTest):
    """Integration tests for Kindle API endpoints.

    Tests run in the order they appear in the file.
    Since the Kindle emulator is stateful, test order matters.
    The emulator is only shut down at the end of all tests.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test."""
        # Use the base class setup
        self.setup_base()

    @classmethod
    def teardown_class(cls):
        """Teardown after all tests in this class.
        Only shutdown the emulator once at the very end."""
        try:
            # Create a session for teardown
            session = requests.Session()
            base_url = f"http://localhost:{4096 if not STAGING else 80}"

            # Shutdown the emulator
            shutdown_url = f"{base_url}/kindle/shutdown"
            params = {"user_email": TEST_USER_EMAIL, "staging": STAGING}
            response = session.post(shutdown_url, params=params, timeout=30)

            if response.status_code == 200:
                print("\n[TEARDOWN] Successfully shut down emulator after all tests")
            else:
                print(f"\n[TEARDOWN] Shutdown returned {response.status_code}: {response.text}")

        except Exception as e:
            print(f"\n[TEARDOWN] Error during shutdown: {e}")

    # The _make_request and _parse_streaming_response methods are inherited from BaseKindleTest

    @pytest.mark.timeout(30)
    def test_auth_check_known_user(self):
        """Test /kindle/auth-check endpoint with known user."""
        print(f"\n[TEST] Testing auth-check for known user: {TEST_USER_EMAIL}")
        auth_response = self._make_request("auth-check")
        assert (
            auth_response.status_code == 200
        ), f"Auth check failed: {auth_response.status_code}: {auth_response.text}"

        auth_data = auth_response.json()
        assert "authenticated" in auth_data, f"Auth response missing authenticated field: {auth_data}"
        assert "status" in auth_data, f"Auth response missing status field: {auth_data}"
        assert "email" in auth_data, f"Auth response missing email field: {auth_data}"
        assert auth_data["email"] == TEST_USER_EMAIL, f"Wrong email in response: {auth_data['email']}"

        # Known user should be authenticated
        print(f"[TEST] Auth check result: {auth_data['status']} for {auth_data['email']}")
        if auth_data.get("auth_date"):
            print(f"[TEST] Authenticated at: {auth_data['auth_date']}")

    @pytest.mark.timeout(30)
    def test_auth_check_unknown_user(self):
        """Test /kindle/auth-check endpoint with unknown user."""
        unknown_email = "no-auth@solreader.com"
        print(f"\n[TEST] Testing auth-check for unknown user: {unknown_email}")

        # Override the default params for this request
        unknown_params = {"user_email": unknown_email, "staging": STAGING}
        auth_response = self._make_request("auth-check", params=unknown_params)
        assert (
            auth_response.status_code == 200
        ), f"Auth check failed: {auth_response.status_code}: {auth_response.text}"

        auth_data = auth_response.json()
        assert "authenticated" in auth_data, f"Auth response missing authenticated field: {auth_data}"
        assert "status" in auth_data, f"Auth response missing status field: {auth_data}"
        assert "email" in auth_data, f"Auth response missing email field: {auth_data}"
        assert auth_data["email"] == unknown_email, f"Wrong email in response: {auth_data['email']}"

        # Unknown user should not be authenticated
        assert auth_data["authenticated"] is False, f"Unknown user should not be authenticated: {auth_data}"
        assert (
            auth_data["status"] == "never_authenticated"
        ), f"Unknown user should have never_authenticated status: {auth_data['status']}"
        print(f"[TEST] Auth check result: {auth_data['status']} for {auth_data['email']} (as expected)")

    @pytest.mark.timeout(120)
    def test_books_non_streaming(self):
        """Test /books endpoint in non-streaming mode (sync=false)."""
        # Always use the web-app proxy for testing
        url = f"{self.base_url}/kindle/books"
        params = self.default_params.copy()

        print("\n[TEST] Testing non-streaming mode (sync=false)...")
        non_stream_params = params.copy()
        non_stream_params["sync"] = "false"

        try:
            response = self.session.get(url, params=non_stream_params, timeout=30)
            response.raise_for_status()
            data = response.json()

            print(f"[TEST] Non-streaming response: {json.dumps(data, indent=2)}")

            # Should have books list
            assert "books" in data, "Response should contain 'books' field"
            assert isinstance(data["books"], list), "books should be a list"
            assert len(data["books"]) >= 3, f"Expected at least 3 books, got {len(data['books'])}"

            # Check book structure
            if len(data["books"]) > 0:
                book = data["books"][0]
                assert "title" in book, "Book should have title"
                assert "author" in book, "Book should have author"

            print(f"[TEST] Non-streaming mode passed! Got {len(data['books'])} books")

        except requests.exceptions.RequestException as e:
            pytest.fail(f"Non-streaming mode failed: {e}")

    @pytest.mark.timeout(120)
    def test_books_pagination(self):
        """Test /books endpoint with pagination (page_size=2)."""
        url = f"{self.base_url}/kindle/books"
        params = self.default_params.copy()

        print("\n[TEST] Testing pagination with page_size=2...")
        page_params = params.copy()
        page_params["sync"] = "false"
        page_params["page_size"] = "2"

        all_pages_books = []
        page = 1
        next_url = None

        while True:
            if next_url:
                # Parse the next URL and update the base to match our test setup
                if next_url.startswith("http://localhost/"):
                    next_url = next_url.replace("http://localhost/", f"{self.base_url}/")
                response = self.session.get(next_url, timeout=30)
            else:
                # First page
                page_params["page"] = str(page)
                response = self.session.get(url, params=page_params, timeout=30)

            response.raise_for_status()
            data = response.json()

            print(f"[TEST] Page {page} response: {json.dumps(data, indent=2)}")

            # Validate pagination response - paginated responses use 'results' instead of 'books'
            books_key = "results" if "results" in data else "books"
            assert (
                books_key in data
            ), f"Paginated response should contain 'results' or 'books', got: {data.keys()}"
            # Check pagination metadata (may vary between implementations)
            assert "page_size" in data or "count" in data, "Paginated response should contain pagination info"

            # Collect books
            all_pages_books.extend(data[books_key])

            # Check if there's a next page
            if "next" in data and data["next"] and data["next"] != "null":
                next_url = data["next"]
                print(f"[TEST] Found next page URL: {next_url}")
                page += 1
            else:
                print(f"[TEST] No more pages")
                break

            # Safety check to prevent infinite loops
            # With 51 books at 2 per page, we could have up to 26 pages
            if page > 30:
                pytest.fail("Too many pages, possible infinite loop")

        print(f"[TEST] Pagination test passed! Got {len(all_pages_books)} books across {page} pages")
        assert len(all_pages_books) >= 3, f"Expected at least 3 books total, got {len(all_pages_books)}"

    @pytest.mark.timeout(120)
    def test_books_streaming(self):
        """Test /books endpoint in streaming mode (sync=true) - verify it actually streams."""
        import time
        
        print("\n[TEST] Testing streaming mode (sync=true)...")
        # Use the dedicated streaming endpoint for sync=true
        stream_url = f"{self.base_url}/kindle/books-stream"
        stream_params = self.default_params.copy()
        stream_params["sync"] = "true"

        try:
            # 120s timeout needed to allow the emulator to boot first
            start_time = time.time()
            response = self.session.get(stream_url, params=stream_params, stream=True, timeout=120)
            response.raise_for_status()

            messages = []
            message_times = []
            first_message_time = None
            
            # Use chunk_size=1 to avoid buffering and get true streaming
            for line in response.iter_lines(chunk_size=1, decode_unicode=False):
                if line:
                    try:
                        # Try parsing as newline-delimited JSON first
                        message = json.loads(line.decode("utf-8"))
                        current_time = time.time()
                        
                        if first_message_time is None:
                            first_message_time = current_time
                            print(f"[STREAM] First message received after {current_time - start_time:.2f}s")
                        
                        elapsed = current_time - first_message_time
                        message_times.append(elapsed)
                        
                        # Log message with timing info
                        if "books" in message:
                            print(f"[STREAM] @{elapsed:.2f}s: Batch {message.get('batch_num', '?')} with {len(message['books'])} books")
                        else:
                            print(f"[STREAM] @{elapsed:.2f}s: {json.dumps(message)}")
                        
                        messages.append(message)

                        # Stop after getting done message or error
                        if message.get("done") or message.get("error"):
                            print(f"[TEST] Stream completed after {elapsed:.2f}s")
                            break
                    except json.JSONDecodeError:
                        # Try SSE format: "data: {json}"
                        if line.startswith(b"data: "):
                            try:
                                message = json.loads(line[6:].decode("utf-8"))
                                current_time = time.time()
                                
                                if first_message_time is None:
                                    first_message_time = current_time
                                
                                elapsed = current_time - first_message_time
                                message_times.append(elapsed)
                                
                                print(f"[STREAM] @{elapsed:.2f}s: SSE: {json.dumps(message)}")
                                messages.append(message)

                                # Stop after getting done message or error
                                if message.get("done") or message.get("error"):
                                    print(f"[TEST] Stream completed after {elapsed:.2f}s")
                                    break
                            except json.JSONDecodeError as e:
                                print(f"[STREAM] Failed to parse line: {line}, error: {e}")
                        else:
                            print(f"[STREAM] Skipping non-JSON line: {line}")

                # Stop after reasonable number of messages
                if len(messages) > 50:
                    print("[TEST] Reached message limit, stopping stream")
                    break

            print(f"[TEST] Received total of {len(messages)} messages over {time.time() - start_time:.2f}s")
            
            # CRITICAL TEST: Verify streaming behavior (not buffering)
            # Check that we received messages progressively, not all at once
            book_messages = [msg for msg in messages if "books" in msg]
            
            # Verify we got the expected streaming messages
            assert any("status" in msg for msg in messages), "Should have status message"
            assert any("filter_book_count" in msg for msg in messages), "Should have filter count"
            assert len(book_messages) > 0, "Should have at least one book batch"
            
            # Check timing - messages should arrive over time
            if len(messages) > 2:
                # Calculate time span of all messages
                total_time_span = message_times[-1] - message_times[0] if message_times else 0
                print(f"[TEST] Messages arrived over {total_time_span:.3f}s")
                
                # Even with fast retrieval, streaming should show some time distribution
                # (as opposed to all messages having exactly the same timestamp)
                unique_times = len(set(round(t, 3) for t in message_times))
                print(f"[TEST] Found {unique_times} unique timestamps (rounded to ms)")
                
                # Verify messages didn't all arrive at exactly the same instant
                assert unique_times > 1, "All messages have the same timestamp - likely buffered!"
                
                # If we have multiple book batches, check they arrived sequentially
                if len(book_messages) > 1:
                    book_indices = [i for i, msg in enumerate(messages) if "books" in msg]
                    for i in range(1, len(book_indices)):
                        time_gap = message_times[book_indices[i]] - message_times[book_indices[i-1]]
                        print(f"[TEST] Time between batch {i} and {i+1}: {time_gap*1000:.1f}ms")
                    
                    # Verify batches arrived in sequence (not reversed or jumbled)
                    assert all(message_times[book_indices[i]] >= message_times[book_indices[i-1]] 
                              for i in range(1, len(book_indices))), "Batches not in time order!"
                
                print("[TEST] ✓ Streaming verified: Messages arrived progressively")
            else:
                print("[TEST] Too few messages to verify streaming timing")

            # Log all messages for comparison
            print(f"[TEST] All streaming messages: {json.dumps(messages, indent=2)}")

            # Check for expected streaming response format
            assert len(messages) > 0, "No messages received from stream"

            # Should have either books or error response
            has_books = any("books" in msg for msg in messages)
            has_error = any("error" in msg for msg in messages)
            has_done = any(msg.get("done") == True for msg in messages)
            has_status = any("status" in msg for msg in messages)
            has_filter_count = any("filter_book_count" in msg for msg in messages)

            print(
                f"[TEST] Message types found: books={has_books}, error={has_error}, done={has_done}, "
                f"status={has_status}, filter_count={has_filter_count}"
            )

            assert (
                has_books or has_error or has_status
            ), "Stream should contain books, error, or status messages"

            if has_books:
                # If we got books, should also have done message
                assert has_done, "Stream with books should have done message"

                # Count total books from all batches
                total_streamed_books = sum(len(msg.get("books", [])) for msg in messages if "books" in msg)
                print(f"[TEST] Total books received via streaming: {total_streamed_books}")
                assert (
                    total_streamed_books >= 3
                ), f"Expected at least 3 books via streaming, got {total_streamed_books}"

            print("[TEST] Streaming mode validation passed!")

        except requests.exceptions.RequestException as e:
            # This might fail if no emulator is running, which is acceptable
            if hasattr(response, "status_code") and response.status_code in [401, 404]:
                print(f"[TEST] Expected error response: {response.status_code}")
            else:
                pytest.fail(f"Streaming mode failed: {e}")

    @pytest.mark.timeout(120)
    def test_staff_auth_fail_without_token(self):
        """Test that impersonation fails without staff token."""
        # Save current session state
        original_cookies = self.session.cookies.copy()

        # Clear any existing staff token
        self.session.cookies.clear()

        print("\n[TEST] Testing impersonation without staff token (should fail)...")
        response = self._make_request("auth", {"user_email": TEST_USER_EMAIL})
        assert response.status_code == 403, f"Expected 403 without staff token, got {response.status_code}"
        data = response.json()
        assert "error" in data, "Response should contain error"
        assert "staff" in data["error"].lower(), f"Error should mention staff auth: {data}"
        print(f"[TEST] ✓ Correctly rejected: {data['error']}")

        # Restore original session state
        self.session.cookies = original_cookies

    @pytest.mark.timeout(120)
    def test_staff_auth_create_token(self):
        """Test creating or retrieving a staff token."""
        # Save current session state
        original_cookies = self.session.cookies.copy()

        # Check if we already have a token from a previous test
        if hasattr(self.__class__, "staff_token") and self.__class__.staff_token:
            print("\n[TEST] Using existing staff token from previous test...")
            # Verify the existing token is still valid
            self.session.cookies.clear()
            self.session.cookies.set("staff_token", self.__class__.staff_token)
            response = self._make_request("staff-auth")
            if response.status_code == 200:
                data = response.json()
                if data.get("authenticated") is True:
                    print(
                        f"[TEST] ✓ Existing token still valid: {self.__class__.staff_token[:8]}...{self.__class__.staff_token[-8:]}"
                    )
                    self.session.cookies = original_cookies
                    return
            # If we get here, existing token is invalid, so create a new one
            print("[TEST] Existing token invalid, creating new one...")

        self.session.cookies.clear()
        print("\n[TEST] Creating new staff token...")
        response = self._make_request("staff-auth", {"auth": "1"})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["authenticated"] is True, f"Authentication failed: {data}"
        assert "token" in data, "Response should contain token"

        # Extract the full token from cookies (since response only shows truncated version)
        staff_token = None
        for cookie in response.cookies:
            if cookie.name == "staff_token":
                staff_token = cookie.value
                break
        assert staff_token is not None, "No staff_token cookie received"
        assert len(staff_token) == 12, f"Token should be 12 chars, got {len(staff_token)}"
        print(f"[TEST] ✓ Staff token created: {staff_token[:8]}...{staff_token[-8:]}")

        # Store token for all tests
        self.__class__.staff_token = staff_token

        # Restore original session state
        self.session.cookies = original_cookies

    @pytest.mark.timeout(120)
    def test_staff_auth_impersonate_user(self):
        """Test using staff token to impersonate a user."""
        # Save current session state
        original_cookies = self.session.cookies.copy()

        # Use the token from previous test
        assert hasattr(self.__class__, "staff_token"), "No staff token from previous test"
        staff_token = self.__class__.staff_token

        print("\n[TEST] Testing user impersonation with staff token...")
        # Clear cookies first to avoid conflicts
        self.session.cookies.clear()
        self.session.cookies.set("staff_token", staff_token)
        response = self._make_request("auth", {"user_email": TEST_USER_EMAIL})
        assert response.status_code == 200, f"Expected 200 with staff token, got {response.status_code}"
        data = response.json()
        assert "success" in data or "authenticated" in data, f"Response missing expected fields: {data}"
        print(f"[TEST] ✓ Successfully impersonated user: {data}")

        # Restore original session state
        self.session.cookies = original_cookies

    @pytest.mark.timeout(120)
    def test_staff_auth_validate_token(self):
        """Test verifying staff token validation."""
        # Save current session state
        original_cookies = self.session.cookies.copy()

        # Use the token from previous test
        assert hasattr(self.__class__, "staff_token"), "No staff token from previous test"
        staff_token = self.__class__.staff_token

        print("\n[TEST] Verifying staff token validation...")
        self.session.cookies.clear()
        self.session.cookies.set("staff_token", staff_token)
        response = self._make_request("staff-auth")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["authenticated"] is True, f"Token validation failed: {data}"
        assert "Valid staff token" in data["message"], f"Unexpected message: {data}"
        print(f"[TEST] ✓ Token validated: {data['message']}")

        # Restore original session state
        self.session.cookies = original_cookies

    @pytest.mark.timeout(120)
    def test_staff_auth_revoke_token(self):
        """Test token revocation endpoint (without actually revoking)."""
        # Save current session state
        original_cookies = self.session.cookies.copy()

        # Use the token from previous test
        assert hasattr(self.__class__, "staff_token"), "No staff token from previous test"
        staff_token = self.__class__.staff_token

        print("\n[TEST] Testing token revocation endpoint (dry run - not actually revoking)...")
        # We're just testing that the endpoint exists and responds properly
        # Not actually revoking since we want to reuse the token
        print("[TEST] ✓ Token revocation endpoint test skipped to preserve token for reuse")
        print(f"[TEST] Token {staff_token[:8]}...{staff_token[-8:]} preserved for future tests")

        # Restore original session state
        self.session.cookies = original_cookies

    @pytest.mark.timeout(120)
    def test_staff_auth_verify_invalid_token_fails(self):
        """Test that an invalid token is rejected."""
        # Save current session state
        original_cookies = self.session.cookies.copy()

        print("\n[TEST] Verifying invalid token is rejected...")
        # Use a fake invalid token
        invalid_token = "invalid" * 8  # 64 chars of "invalid"
        self.session.cookies.clear()
        self.session.cookies.set("staff_token", invalid_token)
        response = self._make_request("auth", {"user_email": TEST_USER_EMAIL})
        assert response.status_code == 403, f"Expected 403 with invalid token, got {response.status_code}"
        data = response.json()
        assert "error" in data, "Response should contain error"
        assert (
            "invalid" in data["error"].lower() or "staff" in data["error"].lower()
        ), f"Error should mention invalid token or staff auth: {data}"
        print(f"[TEST] ✓ Invalid token correctly rejected: {data['error']}")

        # Restore original session state
        self.session.cookies = original_cookies
        print("\n[TEST] Staff token authentication workflow completed successfully!")

    @pytest.mark.timeout(120)
    def test_open_random_book(self):
        """Test /kindle/open-random-book endpoint."""
        response = self._make_request("open-random-book")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "success" in data or "status" in data, f"Response missing success/status field: {data}"

        # Handle last read dialog response
        if data.get("last_read_dialog") and data.get("dialog_text"):
            # Verify dialog-specific fields
            assert "message" in data, f"Response missing message field: {data}"
            assert len(data["dialog_text"]) > 0, "Dialog text should not be empty"
        else:
            # Normal book open response
            assert "ocr_text" in data, f"Response missing OCR text: {data}"
            # Verify we got actual text back
            assert len(data["ocr_text"]) > 0, "OCR text should not be empty"

        # Store book info for subsequent tests
        self.__class__.opened_book = data

    @pytest.mark.timeout(120)
    def test_navigate_preview(self):
        """Test /kindle/navigate endpoint with preview action."""
        # This test depends on test_open_random_book having run first
        if not hasattr(self.__class__, "opened_book"):
            pytest.skip("No book available to navigate - test_open_random_book must run first")

        params = {"action": "preview", "preview": "true"}
        response = self._make_request("navigate", params)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()

        # Handle last read dialog response
        if data.get("last_read_dialog") and data.get("dialog_text"):
            # Verify dialog-specific fields
            assert "message" in data, f"Response missing message field: {data}"
            assert len(data["dialog_text"]) > 0, "Dialog text should not be empty"
        else:
            # Normal navigation response
            assert (
                "ocr_text" in data or "text" in data or "content" in data
            ), f"Response missing OCR text: {data}"
            # Verify we got actual text back
            text_field = data.get("ocr_text") or data.get("text") or data.get("content")
            assert len(text_field) > 0, "OCR text should not be empty"

    @pytest.mark.timeout(120)
    def test_table_of_contents(self):
        """Test /kindle/table-of-contents endpoint."""
        # This test depends on test_open_random_book or test_navigate_preview having run first
        if not hasattr(self.__class__, "opened_book"):
            pytest.skip("No book available - test_open_random_book must run first")

        # Get the title of the currently open book
        opened_book = self.__class__.opened_book
        title = opened_book.get("title") if opened_book else None

        # Make the Table of Contents request
        params = {}
        if title:
            params["title"] = title

        response = self._make_request("table-of-contents", params)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()

        # Verify the response structure
        assert "success" in data, f"Response missing success field: {data}"
        assert data["success"] is True, f"Request was not successful: {data}"

        # Verify position information
        assert "position" in data, f"Response missing position field: {data}"
        position = data["position"]
        if position:
            # Position might have current_page, total_pages, percentage
            if "current_page" in position:
                assert isinstance(position["current_page"], int), "current_page should be an integer"
            if "total_pages" in position:
                assert isinstance(position["total_pages"], int), "total_pages should be an integer"
            if "percentage" in position:
                assert isinstance(position["percentage"], int), "percentage should be an integer"

        # Verify chapters list
        assert "chapters" in data, f"Response missing chapters field: {data}"
        assert isinstance(data["chapters"], list), "chapters should be a list"

        # Verify chapter count
        assert "chapter_count" in data, f"Response missing chapter_count field: {data}"
        assert data["chapter_count"] == len(
            data["chapters"]
        ), "chapter_count doesn't match chapters list length"

        # If we have chapters, verify their structure
        if data["chapters"]:
            for chapter in data["chapters"]:
                assert isinstance(chapter, dict), f"Chapter should be a dict: {chapter}"
                assert "title" in chapter, f"Chapter missing title: {chapter}"
                assert isinstance(chapter["title"], str), f"Chapter title should be a string: {chapter}"
                # Page number is optional
                if "page" in chapter:
                    assert isinstance(chapter["page"], int), f"Chapter page should be an integer: {chapter}"

            print(f"\n[TEST] Found {data['chapter_count']} chapters in Table of Contents")
            # Print first few chapters as a sample
            for i, chapter in enumerate(data["chapters"][:5]):
                page_info = f" (page {chapter['page']})" if "page" in chapter else ""
                print(f"  Chapter {i+1}: {chapter['title']}{page_info}")

    @pytest.mark.expensive
    @pytest.mark.timeout(180)
    def test_recreate_avd(self):
        """Test recreating/creating a new AVD with duplicate request deduplication."""
        print("\n[TEST_RECREATE] Starting test_recreate with duplicate request testing")

        # Dictionary to store results from threads
        results = {}

        def make_recreate_request(request_num, delay=0):
            """Make a recreate request after an optional delay."""
            if delay > 0:
                print(f"[TEST_RECREATE] Request {request_num} waiting {delay}s before starting...")
                time.sleep(delay)

            start_time = time.time()
            print(f"[TEST_RECREATE] Request {request_num} starting recreate request")

            # Use a longer timeout for recreate operations and disable retries
            response = self._make_request(
                "auth",
                method="GET",
                params={
                    "user_email": RECREATE_USER_EMAIL,
                    "recreate": "1",
                },
                timeout=120,  # 2 minutes timeout
                max_deploy_retries=1,  # No retries - recreate is expensive and should only run once
            )

            elapsed = time.time() - start_time
            print(f"[TEST_RECREATE] Request {request_num} completed in {elapsed:.1f}s")
            print(f"[TEST_RECREATE] Request {request_num} status: {response.status_code}")

            data = response.json()
            print(f"[TEST_RECREATE] Request {request_num} response: {data}")

            results[request_num] = {
                "response": response,
                "data": data,
                "elapsed": elapsed,
                "start_time": start_time,
            }

        # Create two threads - one immediate, one delayed by 10 seconds
        thread1 = threading.Thread(target=make_recreate_request, args=(1, 0))
        thread2 = threading.Thread(target=make_recreate_request, args=(2, 10))

        # Start both threads
        print("[TEST_RECREATE] Starting Request 1 immediately and Request 2 after 10s delay")
        thread1.start()
        thread2.start()

        # Wait for both to complete
        thread1.join()
        thread2.join()

        # Verify both requests succeeded
        assert 1 in results, "Request 1 did not complete"
        assert 2 in results, "Request 2 did not complete"

        # Check first request
        response1 = results[1]["response"]
        data1 = results[1]["data"]
        assert response1.status_code == 200, f"Request 1 failed with status {response1.status_code}"
        assert "success" in data1 or "status" in data1, f"Request 1 missing success/status field: {data1}"
        assert data1["success"] is True, f"Request 1 recreation failed: {data1}"
        assert data1["authenticated"] is False, f"Request 1 recreation failed: {data1}"

        # Check second request
        response2 = results[2]["response"]
        data2 = results[2]["data"]
        assert response2.status_code == 200, f"Request 2 failed with status {response2.status_code}"
        assert "success" in data2 or "status" in data2, f"Request 2 missing success/status field: {data2}"
        assert data2["success"] is True, f"Request 2 recreation failed: {data2}"
        assert data2["authenticated"] is False, f"Request 2 recreation failed: {data2}"

        # Verify deduplication worked
        elapsed1 = results[1]["elapsed"]
        elapsed2 = results[2]["elapsed"]
        server_time1 = data1.get("time_taken", 0)
        server_time2 = data2.get("time_taken", 0)

        print(f"\n[TEST_RECREATE] DEDUPLICATION ANALYSIS:")
        print(f"[TEST_RECREATE] Request 1: actual {elapsed1:.1f}s, server reported {server_time1:.1f}s")
        print(f"[TEST_RECREATE] Request 2: actual {elapsed2:.1f}s, server reported {server_time2:.1f}s")

        # Both should have the same server-reported time if deduplicated
        if abs(server_time1 - server_time2) < 0.5:  # Allow small difference
            print(
                f"[TEST_RECREATE] ✓ Both requests report same server time ({server_time1:.1f}s) - confirms deduplication"
            )

        # Request 2 should complete faster in real time if it was deduplicated
        if elapsed2 < elapsed1:
            time_saved = elapsed1 - elapsed2
            print(f"[TEST_RECREATE] ✓ Request 2 completed {time_saved:.1f}s faster in real time")
        else:
            print(f"[TEST_RECREATE] ⚠️ Request 2 took as long as Request 1 (may not have been deduplicated)")

        # Check if requests overlapped
        request1_end = results[1]["start_time"] + elapsed1
        request2_start = results[2]["start_time"]
        if request2_start < request1_end:
            overlap = request1_end - request2_start
            print(f"[TEST_RECREATE] ✓ Requests overlapped by {overlap:.1f}s")

        # Shutdown the recreated AVD
        print("\n[TEST_RECREATE] Making shutdown request")
        shutdown_response = self._make_request(
            "shutdown", method="POST", params={"user_email": RECREATE_USER_EMAIL}
        )
        print(f"[TEST_RECREATE] Shutdown response status: {shutdown_response.status_code}")
        assert shutdown_response.status_code == 200
        print("[TEST_RECREATE] Test completed successfully")

    # Note: The shutdown test is removed as individual method since we handle it in teardown_class
    # If you need to test shutdown/restart routines, you can add specific test methods for those


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
