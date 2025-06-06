"""Image resource for serving images."""

import logging

from flask_restful import Resource

from server.middleware.response_handler import serve_image

logger = logging.getLogger(__name__)


class ImageResource(Resource):
    """Resource for serving images."""

    def get(self, image_id):
        """Get an image by ID and delete it after serving."""
        # Don't use the @handle_automator_response decorator as it can't handle Flask Response objects
        return serve_image(image_id, delete_after=False)

    def post(self, image_id):
        """Get an image by ID without deleting it."""
        # Don't use the @handle_automator_response decorator as it can't handle Flask Response objects
        return serve_image(image_id, delete_after=False)
