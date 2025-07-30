import json
import os
import time
from typing import Any, Dict, Generator

import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.sindarin.com")
TEST_USER_EMAIL = os.environ.get("TEST_USER_EMAIL", "kindle@solreader.com")
STAFF_AUTH_TOKEN = os.environ.get("INTEGRATION_TEST_STAFF_AUTH_TOKEN")
WEB_AUTH_TOKEN = os.environ.get("WEB_INTEGRATION_TEST_AUTH_TOKEN")
STAGING = "1"


class TestKindleAPIIntegration:
    """Integration tests for Kindle API endpoints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test."""
        self.base_url = f"{API_BASE_URL}/kindle"
        self.default_params = {"user_email": TEST_USER_EMAIL, "staging": STAGING}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "KindleAutomator/IntegrationTests"})

        # Set Authorization header for API authentication
        if WEB_AUTH_TOKEN:
            self.session.headers.update({"Authorization": f"Tolkien {WEB_AUTH_TOKEN}"})

        # Set staff auth cookie for user_email override
        if STAFF_AUTH_TOKEN:
            # Don't set domain to allow cookie to work with any domain
            self.session.cookies.set("staff_token", STAFF_AUTH_TOKEN)

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
        response = self._make_request("navigate", params)

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
        open_response = self._make_request("open-random-book")
        assert open_response.status_code == 200

        # Navigate with preview
        nav_response = self._make_request("navigate", {"action": "preview", "preview": "true"})
        assert nav_response.status_code == 200
        nav_data = nav_response.json()
        assert any(key in nav_data for key in ["ocr_text", "text", "content"])

        # Shutdown
        shutdown_response = self._make_request("shutdown", method="POST")
        assert shutdown_response.status_code == 200

    @pytest.mark.expensive
    def test_recreate(self):
        """Ensure that recreation/creating a new AVD works"""
        response = self._make_request(
            "auth",
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
            "shutdown", method="POST", params={"user_email": "recreate@solreader.com"}
        )
        assert shutdown_response.status_code == 200

    @pytest.mark.timeout(60)
    def test_books_stream(self):
        """Test /books-stream endpoint for streaming functionality."""
        # For local testing, override the base URL
        if "localhost" in API_BASE_URL or "127.0.0.1" in API_BASE_URL:
            # For local testing, use the direct endpoint without /kindle prefix
            url = "http://localhost:4098/books-stream"
            params = {"sindarin_email": "sam@solreader.com"}
        else:
            url = f"{self.base_url}/books-stream"
            params = self.default_params.copy()

        # Test 1: Test mode streaming
        print("\n[TEST] Starting test mode streaming...")
        test_params = params.copy()
        test_params["test"] = "1"

        try:
            response = self.session.get(url, params=test_params, stream=True, timeout=30)
            response.raise_for_status()

            messages = list(self._parse_streaming_response(response))
            print(f"[TEST] Received total of {len(messages)} messages in test mode")

            # Validate test mode messages
            assert len(messages) >= 10, f"Expected at least 10 messages, got {len(messages)}"

            # Check for expected message structure
            has_test_started = any(msg.get("status") == "test_started" for msg in messages)
            has_test_messages = any("test_message" in msg for msg in messages)
            has_test_complete = any(msg.get("test_complete") == True for msg in messages)

            assert has_test_started, "Missing test_started message"
            assert has_test_messages, "Missing test_message messages"
            assert has_test_complete, "Missing test_complete message"

            print("[TEST] Test mode validation passed!")

        except requests.exceptions.RequestException as e:
            pytest.fail(f"Test mode streaming failed: {e}")

        # Test 2: Normal mode streaming
        print("\n[TEST] Starting normal mode streaming...")
        try:
            response = self.session.get(url, params=params, stream=True, timeout=30)
            response.raise_for_status()

            messages = []
            for message in self._parse_streaming_response(response):
                messages.append(message)
                # Stop after getting done message or error
                if message.get("done") or message.get("error"):
                    print("[TEST] Received done/error message, stopping stream")
                    break
                # Also stop after reasonable number of messages to prevent hanging
                if len(messages) > 50:
                    print("[TEST] Reached message limit, stopping stream")
                    break

            print(f"[TEST] Received total of {len(messages)} messages in normal mode")

            # Check for expected streaming response format
            assert len(messages) > 0, "No messages received from stream"

            # Should have either books or error response
            has_books = any("books" in msg for msg in messages)
            has_error = any("error" in msg for msg in messages)
            has_done = any(msg.get("done") == True for msg in messages)
            has_status = any("status" in msg for msg in messages)
            has_filter_count = any("filter_book_count" in msg for msg in messages)

            print(
                f"[TEST] Message types found: books={has_books}, error={has_error}, done={has_done}, status={has_status}, filter_count={has_filter_count}"
            )

            assert (
                has_books or has_error or has_status
            ), "Stream should contain books, error, or status messages"

            if has_books:
                # If we got books, should also have done message
                assert has_done, "Stream with books should have done message"

            print("[TEST] Normal mode validation passed!")

        except requests.exceptions.RequestException as e:
            # This might fail if no emulator is running, which is acceptable
            if response.status_code in [401, 404]:
                print(f"[TEST] Expected error response: {response.status_code}")
            else:
                pytest.fail(f"Normal mode streaming failed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
