import json
import os
import time
from typing import Any, Dict, Generator

import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

# NOTE: All test calls go through the web-app ASGI reverse proxy server (port 4096)
# with the /kindle/ prefix. The web-app then routes requests to this Flask server (port 4098).
# Examples:
# - /kindle/open-random-book -> web-app handles random book selection from cache
# - /kindle/books?sync=false -> returns cached books from web-app
# - /kindle/books?sync=true -> routes to this server's /books endpoint

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:4096")
TEST_USER_EMAIL = os.environ.get("TEST_USER_EMAIL", "sam@solreader.com")
STAFF_AUTH_TOKEN = os.environ.get("INTEGRATION_TEST_STAFF_AUTH_TOKEN")
WEB_AUTH_TOKEN = os.environ.get("WEB_INTEGRATION_TEST_AUTH_TOKEN")
STAGING = "1"


class TestKindleAPIIntegration:
    """Integration tests for Kindle API endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test."""
        self.base_url = API_BASE_URL
        self.default_params = {"user_email": TEST_USER_EMAIL, "staging": STAGING}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "KindleAutomator/IntegrationTests"})

        # Set Authorization header for API authentication
        if WEB_AUTH_TOKEN:
            self.session.headers.update({"Authorization": f"Tolkien {WEB_AUTH_TOKEN}"})
            print(f"[TEST] Using Knox token for samuel@ofbrooklyn.com (staff user)")

        # Set staff auth cookie for user_email override
        if "localhost" in API_BASE_URL or "127.0.0.1" in API_BASE_URL:
            # Fetch staff auth token dynamically for local testing from Flask server
            try:
                # Fetch from Flask server directly, not through web-app proxy
                flask_staff_auth_response = requests.get("http://localhost:4098/staff-auth?auth=true")
                if flask_staff_auth_response.status_code == 200:
                    auth_data = flask_staff_auth_response.json()
                    if auth_data.get("authenticated"):
                        # Extract the full token from the Set-Cookie header
                        cookie_header = flask_staff_auth_response.headers.get("Set-Cookie", "")
                        if "staff_token=" in cookie_header:
                            # Extract token value from cookie header
                            token_start = cookie_header.find("staff_token=") + len("staff_token=")
                            token_end = cookie_header.find(";", token_start)
                            if token_end == -1:
                                token_end = len(cookie_header)
                            full_token = cookie_header[token_start:token_end]
                            self.session.cookies.set("staff_token", full_token)
                            print(f"[TEST] Fetched staff token from cookie: {full_token[:10]}... (full length={len(full_token)})")
                        else:
                            print("[TEST] No staff token found in Set-Cookie header")
                else:
                    print(f"[TEST] Failed to fetch staff token: {flask_staff_auth_response.status_code}")
            except Exception as e:
                print(f"Warning: Could not fetch staff token: {e}")

    def _make_request(
        self, endpoint: str, params: Dict[str, Any] = None, method: str = "GET"
    ) -> requests.Response:
        """Helper to make API requests with retry logic for 503 errors."""
        url = f"{self.base_url}/{endpoint}"
        request_params = {**self.default_params, **(params or {})}

        max_retries = 3
        retry_delay = 10  # seconds

        for attempt in range(max_retries):
            try:
                # Debug: print request details
                print(f"\n[DEBUG] Request to {url}")
                print(f"[DEBUG] Params: {request_params}")
                print(f"[DEBUG] Headers: {dict(self.session.headers)}")
                # Debug cookies - show full staff_token
                cookies_dict = dict(self.session.cookies)
                if "staff_token" in cookies_dict:
                    token = cookies_dict["staff_token"]
                    print(f"[DEBUG] Cookies: {{'staff_token': '{token}' (length={len(token)})}}")
                else:
                    print(f"[DEBUG] Cookies: {cookies_dict}")
                
                if method == "GET":
                    response = self.session.get(url, params=request_params, timeout=120)
                elif method == "POST":
                    response = self.session.post(url, params=request_params, timeout=120)

                # If we get a 503 and haven't exhausted retries, wait and retry
                if response.status_code == 503 and attempt < max_retries - 1:
                    print(
                        f"Got 503 error, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                    continue

                return response

            except requests.exceptions.RequestException as e:
                # If this is our last attempt, re-raise the exception
                if attempt == max_retries - 1:
                    raise
                print(
                    f"Request failed with error: {e}, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(retry_delay)

        # This should never be reached, but just in case
        return response

    def _parse_streaming_response(self, response: requests.Response) -> Generator[Dict[str, Any], None, None]:
        """Parse newline-delimited JSON streaming response."""
        for line in response.iter_lines():
            if line:
                try:
                    message = json.loads(line.decode("utf-8"))
                    print(f"[STREAM] Received message: {json.dumps(message, sort_keys=True)}")
                    yield message
                except json.JSONDecodeError as e:
                    print(f"[STREAM] Failed to parse line: {line}, error: {e}")

    @pytest.mark.timeout(120)
    def test_open_random_book(self):
        """Test /kindle/open-random-book endpoint."""
        response = self._make_request("kindle/open-random-book")
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
    def test_navigate_with_preview(self):
        """Test /kindle/navigate endpoint with preview."""
        # First ensure a book is open
        if not hasattr(self.__class__, "opened_book"):
            self.test_open_random_book()
            time.sleep(2)  # Give time for book to load

        # Skip if no book was opened
        if not hasattr(self.__class__, "opened_book"):
            pytest.skip("No book available to navigate")

        params = {"action": "preview", "preview": "true"}
        response = self._make_request("kindle/navigate", params)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "ocr_text" in data or "text" in data or "content" in data, f"Response missing OCR text: {data}"

        # Verify we got actual text back
        text_field = data.get("ocr_text")
        assert len(text_field) > 0, "OCR text should not be empty"

    @pytest.mark.timeout(120)
    def _test_shutdown(self):
        """Test /kindle/shutdown endpoint."""
        try:
            response = self._make_request("shutdown", method="POST")
        except requests.exceptions.ReadTimeout:
            # Don't skip - let the test fail
            raise

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "success" in data or "status" in data, f"Response missing success/status field: {data}"

        # Verify shutdown was acknowledged
        if "success" in data:
            assert data["success"] is True, f"Shutdown failed: {data}"
        elif "status" in data:
            assert data["status"] in [
                "success",
                "ok",
                "completed",
            ], f"Unexpected status: {data}"

    def test_endpoints_sequence(self):
        """Test the full sequence of endpoints."""
        # Open book
        open_response = self._make_request("kindle/open-random-book")
        assert open_response.status_code == 200

        # Navigate with preview
        nav_response = self._make_request("kindle/navigate", {"action": "preview", "preview": "true"})
        assert nav_response.status_code == 200
        nav_data = nav_response.json()
        assert any(key in nav_data for key in ["ocr_text", "text", "content"])

        # Shutdown
        shutdown_response = self._make_request("kindle/shutdown", method="POST")
        assert shutdown_response.status_code == 200

    @pytest.mark.expensive
    def test_recreate(self):
        """Ensure that recreation/creating a new AVD works"""
        response = self._make_request(
            "kindle/auth",
            method="GET",
            params={
                "user_email": "recreate@solreader.com",
                "recreate": "1",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data or "status" in data, f"Response missing success/status field: {data}"
        assert data["success"] is True, f"Recreation failed: {data}"
        assert data["authenticated"] is False, f"Recreation failed: {data}"

        # Shutdown
        shutdown_response = self._make_request(
            "kindle/shutdown", method="POST", params={"user_email": "recreate@solreader.com"}
        )
        assert shutdown_response.status_code == 200

    @pytest.mark.timeout(120)
    def test_books_endpoint(self):
        """Test /books endpoint with sync, pagination, and streaming functionality."""
        # Always use the web-app proxy for testing
        url = f"{self.base_url}/kindle/books"
        params = {}

        # Test 1: Non-streaming mode (sync=false or not specified)
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

        # Test 2: Pagination (page_size=2)
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
            if "next" in data and data["next"]:
                next_url = data["next"]
                print(f"[TEST] Found next page URL: {next_url}")
                page += 1
            else:
                print(f"[TEST] No more pages")
                break

            # Safety check to prevent infinite loops
            if page > 10:
                pytest.fail("Too many pages, possible infinite loop")

        print(f"[TEST] Pagination test passed! Got {len(all_pages_books)} books across {page} pages")
        assert len(all_pages_books) >= 3, f"Expected at least 3 books total, got {len(all_pages_books)}"

        # Test 3: Streaming mode (sync=true)
        print("\n[TEST] Testing streaming mode (sync=true)...")
        # Use the dedicated streaming endpoint for sync=true
        stream_url = f"{self.base_url}/kindle/books-stream"
        stream_params = params.copy()
        stream_params["sync"] = "true"

        try:
            response = self.session.get(stream_url, params=stream_params, stream=True, timeout=60)
            response.raise_for_status()

            messages = []
            for line in response.iter_lines():
                if line:
                    try:
                        # Try parsing as newline-delimited JSON first
                        message = json.loads(line.decode("utf-8"))
                        print(f"[STREAM] Received message: {json.dumps(message)}")
                        messages.append(message)

                        # Stop after getting done message or error
                        if message.get("done") or message.get("error"):
                            print("[TEST] Received done/error message, stopping stream")
                            break
                    except json.JSONDecodeError:
                        # Try SSE format: "data: {json}"
                        if line.startswith(b"data: "):
                            try:
                                message = json.loads(line[6:].decode("utf-8"))
                                print(f"[STREAM] Received SSE message: {json.dumps(message)}")
                                messages.append(message)

                                # Stop after getting done message or error
                                if message.get("done") or message.get("error"):
                                    print("[TEST] Received done/error message, stopping stream")
                                    break
                            except json.JSONDecodeError as e:
                                print(f"[STREAM] Failed to parse line: {line}, error: {e}")
                        else:
                            print(f"[STREAM] Skipping non-JSON line: {line}")

                # Stop after reasonable number of messages
                if len(messages) > 50:
                    print("[TEST] Reached message limit, stopping stream")
                    break

            print(f"[TEST] Received total of {len(messages)} messages in streaming mode")

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
