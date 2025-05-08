"""Middleware for staff authentication."""

import logging
from functools import wraps

from flask import Response, jsonify, request

from server.utils.staff_token_manager import validate_token

logger = logging.getLogger(__name__)


def require_staff_auth(f):
    """Decorator to require staff authentication for protected routes.

    All requests to protected routes must include a valid staff token in cookies.
    - With valid token: allows access to the protected resource
    - Without valid token: returns 403 Forbidden

    Staff-only features should use this decorator to ensure only staff members
    can access them.
    """

    @wraps(f)
    def middleware(*args, **kwargs):
        # Get token from cookies
        token = request.cookies.get("staff_token")

        if not token:
            logger.warning("Staff token is required but not found in cookies")
            # Return the error response as a dictionary and status code
            # so that it can be processed by the handle_automator_response decorator
            return {
                "error": "Staff authentication required",
                "message": "You must authenticate as staff to access this resource",
            }, 403

        # Validate the token
        if not validate_token(token):
            logger.warning(f"Invalid staff token: {token}")
            # Return the error response as a dictionary and status code
            # so that it can be processed by the handle_automator_response decorator
            return {
                "error": "Invalid staff token",
                "message": "Your staff token is invalid or has been revoked",
            }, 403

        logger.info("Staff authentication successful")
        return f(*args, **kwargs)

    return middleware


def require_staff_auth_for_impersonation(f):
    """Decorator to require staff authentication only when impersonating users.

    This middleware checks for email impersonation attempts with special cases:
    - The /auth endpoint is completely exempt and allows all email parameters
    - For other endpoints, only check for 'sindarin_email' or 'email' if not on /auth

    Staff members can impersonate any user by passing email parameters,
    but only if they have a valid token.
    """

    @wraps(f)
    def middleware(*args, **kwargs):
        # SPECIAL CASE: Always allow the auth endpoint to use email parameters without staff auth
        if request.path == "/auth":
            logger.debug("Auth endpoint detected, skipping all staff auth checks")
            return f(*args, **kwargs)

        # For all other endpoints, check for sindarin_email or email parameters
        email_in_query = "sindarin_email" in request.args or "email" in request.args
        email_in_body = False

        if request.is_json:
            data = request.get_json(silent=True) or {}
            email_in_body = "sindarin_email" in data or "email" in data

        # If neither email parameter is present, no need for staff auth
        if not email_in_query and not email_in_body:
            logger.debug("No email parameters in request, skipping staff auth check")
            return f(*args, **kwargs)

        # Get token from cookies
        token = request.cookies.get("staff_token")

        if not token:
            logger.warning("Staff token is required but not found in cookies")
            return {
                "error": "Staff authentication required",
                "message": "You must authenticate as staff to impersonate users",
            }, 403

        # Validate the token
        if not validate_token(token):
            logger.warning(f"Invalid staff token: {token}")
            return {
                "error": "Invalid staff token",
                "message": "Your staff token is invalid or has been revoked",
            }, 403

        logger.info("Staff authentication successful, allowing impersonation")
        return f(*args, **kwargs)

    return middleware
