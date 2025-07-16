"""Utility functions for staff authentication."""

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Path to the tokens file
# Store in the AVD profiles directory for persistence across deployments
# In production this is /opt/android-sdk/profiles
# In development (Mac) this is {project_root}/user_data
if os.environ.get("FLASK_ENV") == "development" and os.uname().sysname == "Darwin":
    # Mac development environment
    project_root = Path(__file__).resolve().parent.parent.parent
    TOKENS_FILE = os.path.join(project_root, "user_data", "staff_tokens.json")
else:
    # Production environment
    TOKENS_FILE = "/opt/android-sdk/profiles/staff_tokens.json"


def generate_token() -> str:
    """Generate a secure random token for staff authentication."""
    return secrets.token_hex(32)


def _load_tokens() -> Dict[str, Dict]:
    """Load the tokens from disk."""
    if not os.path.exists(TOKENS_FILE):
        # Create the parent directory if it doesn't exist
        os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
        return {}

    try:
        with open(TOKENS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        logger.warning(f"Failed to load tokens from {TOKENS_FILE}, returning empty dict")
        return {}


def _save_tokens(tokens: Dict[str, Dict]) -> bool:
    """Save the tokens to disk."""
    try:
        # Create the parent directory if it doesn't exist
        os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)

        with open(TOKENS_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to save tokens to {TOKENS_FILE}: {e}", exc_info=True)
        return False


def create_staff_token() -> str:
    """Create a new staff token and save it to disk."""
    token = generate_token()
    tokens = _load_tokens()

    # Add the new token with creation timestamp
    tokens[token] = {
        "created_at": int(time.time()),
    }

    _save_tokens(tokens)
    return token


def validate_token(token: str) -> bool:
    """Validate a staff token."""
    if not token:
        return False

    tokens = _load_tokens()
    return token in tokens


def get_all_tokens() -> List[Dict]:
    """Get all tokens with their metadata."""
    tokens = _load_tokens()
    result = []

    for token, metadata in tokens.items():
        # Add token to metadata for convenience
        token_info = {"token": token, **metadata}
        result.append(token_info)

    return result


def revoke_token(token: str) -> bool:
    """Revoke a staff token."""
    tokens = _load_tokens()
    if token in tokens:
        del tokens[token]
        _save_tokens(tokens)
        return True
    return False
