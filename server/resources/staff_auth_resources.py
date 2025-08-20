"""Staff authentication resource."""

import logging
from datetime import datetime

from flask import jsonify, make_response, request
from flask_restful import Resource

from server.utils.staff_token_manager import (
    create_staff_token,
    get_all_tokens,
    revoke_token,
    validate_token,
)

logger = logging.getLogger(__name__)


class StaffAuthResource(Resource):
    """Resource for staff authentication endpoints."""

    def get(self):
        """Check if the user is authenticated as staff or authenticate with 'auth' parameter.

        If 'auth=1' query parameter is passed, this will create a new token and set the cookie,
        allowing easy authentication via browser.
        """
        # Check if authentication is requested via query parameter
        auth_param = request.args.get("auth", "")
        if auth_param in ("1", "true"):
            # Generate a new staff token
            token = create_staff_token()

            # Create response with success message
            resp = make_response(
                jsonify(
                    {
                        "authenticated": True,
                        "message": "Staff authentication successful via GET request",
                        "token": token,
                    }
                )
            )

            # Set the cookie - secure in production, httponly for all environments
            secure = request.environ.get("wsgi.url_scheme", "http") == "https"
            resp.set_cookie(
                "staff_token",
                token,
                httponly=True,
                secure=secure,
                max_age=90 * 24 * 60 * 60,  # 90 days
                samesite="Lax",
            )

            logger.info(f"Staff token created and set in cookie via GET request")
            return resp

        # Standard behavior - check if already authenticated
        token = request.cookies.get("staff_token")

        if not token:
            return {"authenticated": False, "message": "No staff token found"}, 200

        is_valid = validate_token(token)

        if is_valid:
            return {
                "authenticated": True,
                "message": "Valid staff token",
            }, 200
        else:
            return {"authenticated": False, "message": "Invalid staff token"}, 200

    def post(self):
        """Authenticate as staff by generating and setting a token cookie."""
        # Generate a new staff token
        token = create_staff_token()

        # Create response with success message
        resp = make_response(
            jsonify(
                {
                    "authenticated": True,
                    "message": "Staff authentication successful",
                    "token": token[:8] + "..." + token[-8:],  # Show truncated token for confirmation
                }
            )
        )

        # Set the cookie - secure in production, httponly for all environments
        secure = request.environ.get("wsgi.url_scheme", "http") == "https"
        resp.set_cookie(
            "staff_token",
            token,
            httponly=True,
            secure=secure,
            max_age=90 * 24 * 60 * 60,  # 90 days
            samesite="Lax",
        )

        logger.info(f"Staff token created and set in cookie")
        return resp

    def delete(self):
        """Revoke the current staff token."""
        token = request.cookies.get("staff_token")

        if not token:
            return {"success": False, "message": "No staff token to revoke"}, 400

        # Revoke the token
        success = revoke_token(token)

        # Create response - always clear the cookie
        resp = make_response(
            jsonify(
                {
                    "success": success,
                    "message": "Staff token revoked" if success else "Token not found or already revoked",
                }
            )
        )

        # Clear the cookie
        resp.delete_cookie("staff_token")

        return resp


class StaffTokensResource(Resource):
    """Resource for managing staff tokens."""

    def get(self):
        """List all staff tokens."""
        # Check if the requester is authenticated
        token = request.cookies.get("staff_token")
        if not token or not validate_token(token):
            return {"error": "Staff authentication required"}, 403

        tokens = get_all_tokens()

        # Format the timestamps for better readability
        for token_info in tokens:
            if "created_at" in token_info:
                timestamp = token_info["created_at"]
                token_info["created_at_formatted"] = datetime.fromtimestamp(timestamp).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            # Truncate the actual token for security
            if "token" in token_info:
                full_token = token_info["token"]
                token_info["token"] = full_token[:8] + "..." + full_token[-8:]

        return {"tokens": tokens}, 200
