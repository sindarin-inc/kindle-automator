"""Base test class for Kindle Automator integration tests."""

import json
import logging
import os
import time
from typing import Any, Dict, Generator, Optional

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

logger = logging.getLogger(__name__)

# Configuration from environment variables
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:4096")
TEST_USER_EMAIL = os.environ.get("TEST_USER_EMAIL", "kindle@solreader.com")
RECREATE_USER_EMAIL = os.environ.get("RECREATE_USER_EMAIL", "recreate@solreader.com")
STAFF_AUTH_TOKEN = os.environ.get("INTEGRATION_TEST_STAFF_AUTH_TOKEN")
WEB_AUTH_TOKEN = os.environ.get("WEB_INTEGRATION_TEST_AUTH_TOKEN")
STAGING = "1"


class BaseKindleTest:
    """Base class for Kindle Automator integration tests.

    Provides common setup, authentication, and request handling functionality.
    """

    def setup_base(self):
        """Common setup for all test classes."""
        self.base_url = API_BASE_URL
        self.default_params = {"user_email": TEST_USER_EMAIL, "staging": STAGING}
        self.session = self._create_session()

        # Set up authentication
        self._setup_authentication()

    def _create_session(self) -> requests.Session:
        """Create a configured session with connection pooling and retries."""
        session = requests.Session()
        session.headers.update({"User-Agent": "KindleAutomator/IntegrationTests"})

        # Configure connection pooling and retries
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=10,
            max_retries=Retry(total=3, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _setup_authentication(self):
        """Set up authentication headers and cookies."""
        # Set Authorization header for API authentication
        if WEB_AUTH_TOKEN:
            self.session.headers.update({"Authorization": f"Tolkien {WEB_AUTH_TOKEN}"})
            logger.info("Using Knox token for staff user")

        # Set staff auth cookie for user_email override
        if STAFF_AUTH_TOKEN:
            self.session.cookies.set("staff_token", STAFF_AUTH_TOKEN)
            logger.info("Using staff token from environment variable")
        else:
            # Try to get a staff token from the server if not in environment
            self._get_and_set_staff_token()

    def _get_and_set_staff_token(self):
        """Get a staff token from the server and set it in the session."""
        try:
            # Use the proxy endpoint for consistency
            response = self.session.get(
                f"{self.base_url}/kindle/staff-auth", params={"auth": "1"}, timeout=10
            )
            if response.status_code == 200:
                # Extract token from cookies
                for cookie in response.cookies:
                    if cookie.name == "staff_token":
                        self.session.cookies.set("staff_token", cookie.value)
                        logger.info("Got staff token from server")
                        break
        except Exception as e:
            logger.warning(f"Could not get staff token: {e}")

    def _make_request(
        self,
        endpoint: str,
        params: Dict[str, Any] = None,
        method: str = "GET",
        timeout: int = 120,
        max_deploy_retries: int = 1,
        use_proxy: bool = True,
    ) -> requests.Response:
        """Helper to make API requests with retry logic for 503 errors during deployments.

        IMPORTANT: We use the /kindle/ prefix to route through the FastAPI reverse proxy
        (running on port 4096). This proxy handles authentication, caching, and routing
        to the Flask backend (port 4098). The proxy provides:
        - Authentication handling with Knox tokens
        - Response caching for certain endpoints
        - Request routing and load balancing
        - Additional security and validation

        Args:
            endpoint: The API endpoint (without /kindle/ prefix if use_proxy=True)
            params: Query parameters
            method: HTTP method
            timeout: Request timeout in seconds
            max_deploy_retries: Maximum number of retries for 503 errors during deployments (default: 1)
            use_proxy: Whether to use the proxy server (port 4096) or direct (port 4098)

        Returns:
            The response object
        """
        # Build URL based on proxy setting
        if use_proxy:
            # Use FastAPI reverse proxy with /kindle/ prefix for proper routing
            # The proxy handles auth, caching, and forwards to Flask backend
            url = f"{self.base_url}/kindle/{endpoint.lstrip('/')}"
        else:
            # Direct to Flask server (bypasses proxy features)
            url = f"{self.base_url}/{endpoint.lstrip('/')}"

        request_params = {**self.default_params, **(params or {})}
        retry_delay = 10  # seconds

        for attempt in range(max_deploy_retries):
            try:
                # Debug: log request details
                logger.debug(f"Request attempt {attempt + 1}/{max_deploy_retries} to {url}")
                logger.debug(f"Params: {request_params}")
                logger.debug(f"Headers: {dict(self.session.headers)}")

                # Debug cookies - show full staff_token
                try:
                    cookies_dict = dict(self.session.cookies)
                    if "staff_token" in cookies_dict:
                        token = cookies_dict["staff_token"]
                        logger.debug(f"Cookies: {{'staff_token': '{token}' (length={len(token)})}}")
                    else:
                        logger.debug(f"Cookies: {cookies_dict}")
                except Exception as e:
                    # Handle cookie conflicts gracefully
                    logger.debug(f"Cookie info unavailable: {e}")

                if method == "GET":
                    response = self.session.get(url, params=request_params, timeout=timeout)
                elif method == "POST":
                    response = self.session.post(url, params=request_params, timeout=timeout)
                elif method == "DELETE":
                    response = self.session.delete(url, params=request_params, timeout=timeout)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                # If we get a 503 and haven't exhausted retries, wait and retry
                if response.status_code == 503 and attempt < max_deploy_retries - 1:
                    logger.info(
                        f"Got 503 error (deployment in progress), retrying in {retry_delay} seconds... "
                        f"(attempt {attempt + 1}/{max_deploy_retries})"
                    )
                    time.sleep(retry_delay)
                    continue

                # Fail immediately on 500 errors (internal server error)
                if response.status_code == 500:
                    error_msg = f"Request failed with status 500 (Internal Server Error)"
                    try:
                        error_data = response.json()
                        error_msg += f": {error_data}"
                    except:
                        error_msg += f": {response.text}"
                    raise AssertionError(error_msg)

                return response

            except requests.exceptions.RequestException as e:
                # If this is our last attempt, re-raise the exception
                if attempt == max_deploy_retries - 1:
                    raise
                logger.info(
                    f"Request failed with error: {e}, retrying in {retry_delay} seconds... "
                    f"(attempt {attempt + 1}/{max_deploy_retries})"
                )
                time.sleep(retry_delay)

        # This should never be reached, but just in case
        return response

    def _parse_streaming_response(self, response: requests.Response) -> Generator[Dict[str, Any], None, None]:
        """Parse newline-delimited JSON streaming response."""
        for line in response.iter_lines():
            if line:
                try:
                    # Try parsing as newline-delimited JSON first
                    message = json.loads(line.decode("utf-8"))
                    logger.debug(f"[STREAM] Received message: {json.dumps(message, sort_keys=True)}")
                    yield message
                except json.JSONDecodeError:
                    # Try SSE format: "data: {json}"
                    if line.startswith(b"data: "):
                        try:
                            message = json.loads(line[6:].decode("utf-8"))
                            logger.debug(f"[STREAM] Received SSE message: {json.dumps(message)}")
                            yield message
                        except json.JSONDecodeError as e:
                            logger.warning(f"[STREAM] Failed to parse line: {line}, error: {e}")
                    else:
                        logger.debug(f"[STREAM] Skipping non-JSON line: {line}")

    def _create_test_session(self) -> requests.Session:
        """Create a new session with proper authentication for test threads.

        This is useful for multi-threaded tests where each thread needs its own session.
        """
        session = self._create_session()

        # Copy authentication from main session
        if WEB_AUTH_TOKEN:
            session.headers.update({"Authorization": f"Tolkien {WEB_AUTH_TOKEN}"})

        # Get staff token from main session cookies
        staff_token = None
        for cookie in self.session.cookies:
            if cookie.name == "staff_token":
                staff_token = cookie.value
                break

        if staff_token:
            session.cookies.set("staff_token", staff_token)
        elif STAFF_AUTH_TOKEN:
            session.cookies.set("staff_token", STAFF_AUTH_TOKEN)

        return session

    def _build_params(self, base_params: Dict[str, Any]) -> Dict[str, Any]:
        """Build request parameters with common fields.

        Args:
            base_params: The base parameters to extend

        Returns:
            Parameters with staging flag and other common fields
        """
        params = base_params.copy()
        params["staging"] = STAGING
        # Only add sindarin_email if not already present and it's different from user_email
        if "sindarin_email" not in params and params.get("user_email") != TEST_USER_EMAIL:
            params["sindarin_email"] = TEST_USER_EMAIL
        return params
