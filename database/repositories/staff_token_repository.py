"""Repository for StaffToken model operations."""

import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from database.models import StaffToken

logger = logging.getLogger(__name__)


class StaffTokenRepository:
    """Repository for StaffToken CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def create_token(self) -> StaffToken:
        """Create a new staff token."""
        token_value = secrets.token_hex(32)

        token = StaffToken(
            token=token_value,
            created_at=datetime.now(timezone.utc),
        )

        self.session.add(token)
        self.session.commit()
        self.session.refresh(token)

        logger.info(f"Created new staff token with ID {token.id}")
        return token

    def get_token(self, token_value: str) -> Optional[StaffToken]:
        """Get a token by its value."""
        return (
            self.session.query(StaffToken)
            .filter(StaffToken.token == token_value, StaffToken.revoked == False)
            .first()
        )

    def validate_token(self, token_value: str) -> bool:
        """Validate a staff token and update last_used timestamp."""
        token = self.get_token(token_value)

        if token:
            # Update last_used timestamp
            token.last_used = datetime.now(timezone.utc)
            self.session.commit()
            return True

        return False

    def get_all_tokens(self) -> List[StaffToken]:
        """Get all non-revoked tokens."""
        return (
            self.session.query(StaffToken)
            .filter(StaffToken.revoked == False)
            .order_by(StaffToken.created_at.desc())
            .all()
        )

    def revoke_token(self, token_value: str) -> bool:
        """Revoke a staff token."""
        token = self.session.query(StaffToken).filter(StaffToken.token == token_value).first()

        if token and not token.revoked:
            token.revoked = True
            token.revoked_at = datetime.now(timezone.utc)
            self.session.commit()
            logger.info(f"Revoked staff token with ID {token.id}")
            return True

        return False

    def cleanup_old_tokens(self, days: int = 90) -> int:
        """Remove tokens older than specified days that have never been used."""
        cutoff_date = datetime.now(timezone.utc).timestamp() - (days * 24 * 60 * 60)
        cutoff_datetime = datetime.fromtimestamp(cutoff_date, tz=timezone.utc)

        tokens_to_revoke = (
            self.session.query(StaffToken)
            .filter(
                StaffToken.created_at < cutoff_datetime,
                StaffToken.last_used.is_(None),
                StaffToken.revoked == False,
            )
            .all()
        )

        count = 0
        for token in tokens_to_revoke:
            token.revoked = True
            token.revoked_at = datetime.now(timezone.utc)
            count += 1

        if count > 0:
            self.session.commit()
            logger.info(f"Revoked {count} unused tokens older than {days} days")

        return count
