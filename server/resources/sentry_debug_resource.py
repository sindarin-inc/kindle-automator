"""Sentry debug resource for testing Sentry integration."""

import logging
import os

import sentry_sdk
from flask import request
from flask_restful import Resource

from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


class SentryDebugResource(Resource):
    """Debug endpoint for testing Sentry integration."""

    def get(self):
        """Trigger a test error for Sentry."""
        sindarin_email = get_sindarin_email()

        # Set user context for Sentry
        if sindarin_email:
            sentry_sdk.set_user({"email": sindarin_email})

        # Add custom context
        ENVIRONMENT = os.getenv("ENVIRONMENT", "DEV")
        SENTRY_DSN = os.getenv("SENTRY_DSN")

        sentry_sdk.set_context(
            "environment",
            {
                "flask_env": os.getenv("FLASK_ENV", "production"),
                "environment": ENVIRONMENT,
                "has_sentry": bool(SENTRY_DSN),
            },
        )

        # Check if we should actually trigger an error
        trigger_error = request.args.get("trigger", "false").lower() == "true"

        if trigger_error:
            # This will be caught by Sentry
            raise Exception("Test error from /sentry-debug endpoint")
        else:
            return {
                "message": "Sentry debug endpoint is working",
                "sentry_enabled": bool(SENTRY_DSN),
                "environment": ENVIRONMENT,
                "user_email": sindarin_email,
                "hint": "Add ?trigger=true to actually trigger a test error",
            }, 200
