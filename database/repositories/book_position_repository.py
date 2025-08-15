"""Repository for managing book navigation positions."""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database.models import BookPosition, User

logger = logging.getLogger(__name__)


class BookPositionRepository:
    """Repository for managing book position data with atomic database operations."""

    def __init__(self, session: Session):
        self.session = session

    def get_position(self, email: str, book_title: str) -> int:
        """
        Get the current position for a book.

        Args:
            email: The user's email address
            book_title: The title of the book

        Returns:
            The current position (0 if not found)
        """
        try:
            # First get the user
            user = self.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if not user:
                logger.warning(f"User not found: {email}")
                return 0

            # Get the position
            stmt = select(BookPosition).where(
                BookPosition.user_id == user.id, BookPosition.book_title == book_title
            )
            position = self.session.execute(stmt).scalar_one_or_none()

            if position:
                logger.debug(f"Found position {position.current_position} for {email}/{book_title}")
                return position.current_position
            else:
                logger.debug(f"No position found for {email}/{book_title}, returning 0")
                return 0
        except SQLAlchemyError as e:
            logger.error(f"Error getting position for {email}/{book_title}: {e}")
            return 0

    def reset_position(self, email: str, book_title: str) -> None:
        """
        Reset the position to 0 for a book (called when opening a book).

        Args:
            email: The user's email address
            book_title: The title of the book
        """
        try:
            # First get the user
            user = self.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if not user:
                logger.warning(f"User not found: {email}")
                return

            # Check if position record exists
            stmt = select(BookPosition).where(
                BookPosition.user_id == user.id, BookPosition.book_title == book_title
            )
            position = self.session.execute(stmt).scalar_one_or_none()

            now = datetime.now(timezone.utc)
            if position:
                # Update existing record
                position.current_position = 0
                position.position_updated_at = now
            else:
                # Create new record
                position = BookPosition(
                    user_id=user.id,
                    book_title=book_title,
                    current_position=0,
                    position_updated_at=now,
                    created_at=now,
                )
                self.session.add(position)

            self.session.commit()
            logger.debug(f"Reset position to 0 for {email}/{book_title}")
        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error resetting position for {email}/{book_title}: {e}")

    def update_position(self, email: str, book_title: str, delta: int) -> int:
        """
        Update the position by a relative amount.

        Args:
            email: The user's email address
            book_title: The title of the book (optional, uses current book if not provided)
            delta: The relative change in position

        Returns:
            The new position after update
        """
        try:
            # First get the user
            user = self.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if not user:
                logger.warning(f"User not found: {email}")
                return 0

            # If no book title provided, we can't update position
            if not book_title:
                logger.warning(f"No book title provided for position update for {email}")
                return 0

            # Get or create position record
            stmt = select(BookPosition).where(
                BookPosition.user_id == user.id, BookPosition.book_title == book_title
            )
            position = self.session.execute(stmt).scalar_one_or_none()

            now = datetime.now(timezone.utc)
            if position:
                # Update existing record
                old_position = position.current_position
                new_position = old_position + delta
                position.current_position = new_position
                position.position_updated_at = now
            else:
                # Create new record with delta as the initial position
                new_position = delta
                position = BookPosition(
                    user_id=user.id,
                    book_title=book_title,
                    current_position=new_position,
                    position_updated_at=now,
                    created_at=now,
                )
                self.session.add(position)

            self.session.commit()
            logger.debug(
                f"Updated position for {email}/{book_title}: delta={delta}, new_position={new_position}"
            )
            return new_position
        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error updating position for {email}/{book_title}: {e}")
            return 0

    def set_position(self, email: str, book_title: str, position_value: int) -> None:
        """
        Set the absolute position for a book.

        Args:
            email: The user's email address
            book_title: The title of the book
            position_value: The absolute position to set
        """
        try:
            # First get the user
            user = self.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if not user:
                logger.warning(f"User not found: {email}")
                return

            # Get or create position record
            stmt = select(BookPosition).where(
                BookPosition.user_id == user.id, BookPosition.book_title == book_title
            )
            position = self.session.execute(stmt).scalar_one_or_none()

            now = datetime.now(timezone.utc)
            if position:
                # Update existing record
                position.current_position = position_value
                position.position_updated_at = now
            else:
                # Create new record
                position = BookPosition(
                    user_id=user.id,
                    book_title=book_title,
                    current_position=position_value,
                    position_updated_at=now,
                    created_at=now,
                )
                self.session.add(position)

            self.session.commit()
            logger.debug(f"Set position to {position_value} for {email}/{book_title}")
        except SQLAlchemyError as e:
            self.session.rollback()
            logger.error(f"Error setting position for {email}/{book_title}: {e}")

    def get_position_with_book(
        self, email: str, book_title: Optional[str] = None
    ) -> tuple[int, Optional[str]]:
        """
        Get the position for a specific book or the most recently updated book.

        Args:
            email: The user's email address
            book_title: Optional book title. If not provided, returns the most recent position.

        Returns:
            Tuple of (position, book_title)
        """
        try:
            # First get the user
            user = self.session.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if not user:
                logger.warning(f"User not found: {email}")
                return 0, None

            if book_title:
                # Get position for specific book
                stmt = select(BookPosition).where(
                    BookPosition.user_id == user.id, BookPosition.book_title == book_title
                )
                position = self.session.execute(stmt).scalar_one_or_none()
                if position:
                    return position.current_position, book_title
                else:
                    return 0, book_title
            else:
                # Get most recent position
                stmt = (
                    select(BookPosition)
                    .where(BookPosition.user_id == user.id)
                    .order_by(BookPosition.position_updated_at.desc())
                    .limit(1)
                )
                position = self.session.execute(stmt).scalar_one_or_none()
                if position:
                    return position.current_position, position.book_title
                else:
                    return 0, None
        except SQLAlchemyError as e:
            logger.error(f"Error getting position for {email}: {e}")
            return 0, None
