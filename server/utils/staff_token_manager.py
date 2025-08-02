"""Utility functions for staff authentication."""

import logging
from typing import Dict, List

from database.connection import DatabaseConnection
from database.repositories.staff_token_repository import StaffTokenRepository

logger = logging.getLogger(__name__)


def create_staff_token() -> str:
    """Create a new staff token and save it to database."""
    with DatabaseConnection().get_session() as session:
        repo = StaffTokenRepository(session)
        token = repo.create_token()
        return token.token


def validate_token(token: str) -> bool:
    """Validate a staff token."""
    if not token:
        return False

    with DatabaseConnection().get_session() as session:
        repo = StaffTokenRepository(session)
        return repo.validate_token(token)


def get_all_tokens() -> List[Dict]:
    """Get all tokens with their metadata."""
    with DatabaseConnection().get_session() as session:
        repo = StaffTokenRepository(session)
        tokens = repo.get_all_tokens()

        result = []
        for token in tokens:
            token_info = {
                "token": token.token,
                "created_at": int(token.created_at.timestamp()),
                "last_used": int(token.last_used.timestamp()) if token.last_used else None,
            }
            result.append(token_info)

        return result


def revoke_token(token: str) -> bool:
    """Revoke a staff token."""
    with DatabaseConnection().get_session() as session:
        repo = StaffTokenRepository(session)
        return repo.revoke_token(token)
