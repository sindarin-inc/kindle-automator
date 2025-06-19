"""Authentication check resource."""

import logging
from datetime import datetime

from flask import jsonify, request
from flask_restful import Resource

from server.utils.request_utils import get_sindarin_email
from views.core.avd_profile_manager import AVDProfileManager

logger = logging.getLogger(__name__)


class AuthCheckResource(Resource):
    """Resource for checking authentication status of a user."""

    def get(self):
        """Check the authentication status for the current user.

        Returns three possible states:
        1. authenticated: User has auth_date set (was authenticated)
        2. auth_failed: User has auth_failed_date set (authentication was lost)
        3. never_authenticated: No profile exists OR neither auth_date nor auth_failed_date exists
        """
        try:
            # Get the user's email
            sindarin_email = get_sindarin_email()

            if not sindarin_email:
                return {"error": "No email provided", "message": "Email parameter is required"}, 400

            # Get the profile manager instance
            profile_manager = AVDProfileManager.get_instance()

            # Check if profile exists
            if sindarin_email not in profile_manager.profiles_index:
                # No profile = never authenticated
                return {
                    "authenticated": False,
                    "status": "never_authenticated",
                    "message": "User has never been authenticated",
                    "email": sindarin_email,
                }, 200

            # Check authentication fields
            auth_date = profile_manager.get_user_field(sindarin_email, "auth_date")
            auth_failed_date = profile_manager.get_user_field(sindarin_email, "auth_failed_date")

            # Determine authentication state
            if auth_failed_date:
                # User has lost authentication
                return {
                    "authenticated": False,
                    "status": "auth_failed",
                    "auth_failed_date": auth_failed_date,
                    "auth_date": auth_date,  # Include original auth date if exists
                    "message": "User authentication has failed or expired",
                    "email": sindarin_email,
                }, 200
            elif auth_date:
                # User is authenticated
                return {
                    "authenticated": True,
                    "status": "authenticated",
                    "auth_date": auth_date,
                    "message": "User is authenticated",
                    "email": sindarin_email,
                }, 200
            else:
                # User has never been authenticated
                return {
                    "authenticated": False,
                    "status": "never_authenticated",
                    "message": "User has never been authenticated",
                    "email": sindarin_email,
                }, 200

        except Exception as e:
            logger.error(f"Error checking authentication status: {e}")
            return {"error": "Failed to check authentication status", "message": str(e)}, 500
