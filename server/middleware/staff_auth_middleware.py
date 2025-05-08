"""Middleware for staff authentication."""

import logging
from functools import wraps

from flask import Response, jsonify, request

from server.utils.staff_token_manager import validate_token

logger = logging.getLogger(__name__)


def require_staff_auth_for_impersonation(f):
    """Decorator to require staff authentication only when impersonating users.

    This middleware checks for email impersonation attempts (email/sindarin_email parameters).
    - If no impersonation is attempted: allows the request to proceed normally
    - If impersonation is attempted: requires a valid staff token in cookies
      - With valid token: allows impersonation
      - Without valid token: returns 403 Forbidden

    Staff members can impersonate any user by passing email/sindarin_email parameters,
    but only if they have a valid token.
    """

    @wraps(f)
    def middleware(*args, **kwargs):
        # Check for sindarin_email or email in query parameters or JSON body
        email_in_query = "sindarin_email" in request.args or "email" in request.args
        email_in_body = False

        if request.is_json:
            data = request.get_json(silent=True) or {}
            email_in_body = "sindarin_email" in data or "email" in data

        # If neither email parameter is present, no need for staff auth
        if not email_in_query and not email_in_body:
            logger.debug("No sindarin_email in request, skipping staff auth check")
            return f(*args, **kwargs)

        # Get token from cookies
        token = request.cookies.get("staff_token")

        if not token:
            logger.warning("Staff token is required but not found in cookies")
            return (
                jsonify(
                    {
                        "error": "Staff authentication required",
                        "message": "You must authenticate as staff to impersonate users",
                    }
                ),
                403,
            )

        # Validate the token
        if not validate_token(token):
            logger.warning(f"Invalid staff token: {token}")
            return (
                jsonify(
                    {
                        "error": "Invalid staff token",
                        "message": "Your staff token is invalid or has been revoked",
                    }
                ),
                403,
            )

        logger.info("Staff authentication successful, allowing impersonation")
        return f(*args, **kwargs)

    return middleware
