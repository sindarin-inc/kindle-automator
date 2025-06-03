import os
import time
from typing import Any, Dict

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
        """Helper to make API requests."""
        url = f"{self.base_url}/{endpoint}"
        request_params = {**self.default_params, **(params or {})}

        if method == "GET":
            response = self.session.get(url, params=request_params, timeout=120)
        elif method == "POST":
            response = self.session.post(url, json=request_params, timeout=120)

        return response

    @pytest.mark.timeout(60)
    def test_open_random_book(self):
        """Test /kindle/open-random-book endpoint."""
        response = self._make_request("open-random-book")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "success" in data or "status" in data, f"Response missing success/status field: {data}"
        assert "book" in data or "title" in data or "message" in data, f"Response missing book info: {data}"

        # Store book info for subsequent tests
        self.__class__.opened_book = data

    @pytest.mark.timeout(60)
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
        text_field = data.get("ocr_text") or data.get("text") or data.get("content", "")
        assert len(text_field) > 0, "OCR text should not be empty"

    @pytest.mark.timeout(60)
    def test_shutdown(self):
        """Test /kindle/shutdown endpoint."""
        # Authenticate via staff-auth endpoint
        auth_url = f"{API_BASE_URL}/kindle/staff-auth"
        auth_response = self.session.get(auth_url, params={"auth": "1"})
        assert auth_response.status_code == 200, f"Staff auth failed: {auth_response.status_code}"

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
        time.sleep(3)  # Wait for book to load

        # Navigate with preview
        nav_response = self._make_request("navigate", {"action": "preview", "preview": "true"})
        assert nav_response.status_code == 200
        nav_data = nav_response.json()
        assert any(key in nav_data for key in ["ocr_text", "text", "content"])

        # Shutdown
        shutdown_response = self._make_request("shutdown", method="POST")
        assert shutdown_response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
