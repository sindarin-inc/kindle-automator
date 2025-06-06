"""Cover image resource for serving book cover images."""

import logging
import traceback
from pathlib import Path

from flask import make_response, send_file
from flask_restful import Resource

logger = logging.getLogger(__name__)


class CoverImageResource(Resource):
    """Resource for serving book cover images."""

    def get(self, email_slug, filename):
        """Get a book cover image by email slug and filename."""
        try:
            # Construct the absolute path to the cover image
            project_root = Path(__file__).resolve().parent.parent.parent.absolute()
            covers_dir = project_root / "covers"
            user_covers_dir = covers_dir / email_slug
            cover_path = user_covers_dir / filename

            # Check if cover file exists
            if not cover_path.exists():
                logger.error(f"Cover image not found: {cover_path}")
                return {"error": "Cover image not found"}, 404

            # Create response with proper mime type
            response = make_response(send_file(str(cover_path), mimetype="image/png"))

            # No need to delete cover images - they're persisted for future use
            return response

        except Exception as e:
            from server.utils.appium_error_utils import is_appium_error

            if is_appium_error(e):
                raise
            logger.error(f"Error serving cover image: {e}")
            traceback.print_exc()
            return {"error": str(e)}, 500
