"""Repository for managing book session operations."""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from database.models import BookSession, User

logger = logging.getLogger(__name__)


class BookSessionRepository:
    """Repository for book session operations."""

    def __init__(self, session: Session):
        """Initialize the repository with a database session.

        Args:
            session: SQLAlchemy session
        """
        self.session = session

    def get_or_create_session(
        self, email: str, book_title: str, session_key: str, position: int = 0
    ) -> BookSession:
        """Get existing session or create a new one.

        Args:
            email: User's email address
            book_title: Title of the book
            session_key: Client's session key
            position: Initial position if creating new session

        Returns:
            BookSession object
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            raise ValueError(f"User not found: {email}")

        # Try to find existing session for this user and book
        book_session = (
            self.session.query(BookSession).filter_by(user_id=user.id, book_title=book_title).first()
        )

        if book_session:
            # Existing session found
            if book_session.session_key != session_key:
                # Different session key - client is continuing with their session
                # but we need to adjust our position based on their perspective
                logger.info(
                    f"Session key mismatch for {email}/{book_title}: "
                    f"client={session_key}, db={book_session.session_key}. "
                    f"Updating to use client's session key and position."
                )
                book_session.session_key = session_key

            # Always update position to track where the client thinks they are
            book_session.position = position
            # Update last accessed time
            book_session.last_accessed = datetime.now(timezone.utc)
            self.session.commit()
        else:
            # Create new session
            book_session = BookSession(
                user_id=user.id,
                book_title=book_title,
                session_key=session_key,
                position=position,
                last_accessed=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(book_session)
            self.session.commit()
            logger.info(f"Created new book session for {email}/{book_title} with key {session_key}")

        return book_session

    def update_position(self, email: str, book_title: str, new_position: int) -> Optional[BookSession]:
        """Update the position for a book session.

        Args:
            email: User's email address
            book_title: Title of the book
            new_position: New position to set

        Returns:
            Updated BookSession or None if not found
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            logger.warning(f"User not found: {email}")
            return None

        # Find the session
        book_session = (
            self.session.query(BookSession).filter_by(user_id=user.id, book_title=book_title).first()
        )

        if book_session:
            book_session.position = new_position
            book_session.last_accessed = datetime.now(timezone.utc)
            self.session.commit()
            logger.debug(f"Updated position for {email}/{book_title} to {new_position}")
            return book_session
        else:
            logger.warning(f"No book session found for {email}/{book_title}")
            return None

    def get_session(self, email: str, book_title: str) -> Optional[BookSession]:
        """Get a book session for a user and book.

        Args:
            email: User's email address
            book_title: Title of the book

        Returns:
            BookSession or None if not found
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            return None

        return self.session.query(BookSession).filter_by(user_id=user.id, book_title=book_title).first()

    def reset_session(self, email: str, book_title: str, new_session_key: str) -> Optional[BookSession]:
        """Reset a book session with a new session key and position 0.
        Used when /open-book is called.

        Args:
            email: User's email address
            book_title: Title of the book
            new_session_key: New session key to set

        Returns:
            Updated BookSession or newly created one
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            raise ValueError(f"User not found: {email}")

        # Find existing session or create new one
        book_session = (
            self.session.query(BookSession).filter_by(user_id=user.id, book_title=book_title).first()
        )

        if book_session:
            # Reset existing session
            book_session.session_key = new_session_key
            book_session.position = 0
            book_session.last_accessed = datetime.now(timezone.utc)
            logger.info(f"Reset book session for {email}/{book_title} with new key {new_session_key}")
        else:
            # Create new session
            book_session = BookSession(
                user_id=user.id,
                book_title=book_title,
                session_key=new_session_key,
                position=0,
                last_accessed=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(book_session)
            logger.info(f"Created new book session for {email}/{book_title} with key {new_session_key}")

        self.session.commit()
        return book_session

    def calculate_position_adjustment(
        self, email: str, book_title: str, client_session_key: str, client_position: int
    ) -> int:
        """Calculate the position adjustment needed when session keys don't match.

        This is used when the client thinks they're at position X but we've reopened
        the book (losing their context). We need to navigate to where they think they are.

        Args:
            email: User's email address
            book_title: Title of the book
            client_session_key: Client's session key
            client_position: Position the client thinks they're at

        Returns:
            The adjustment needed (positive = forward, negative = backward)
        """
        session = self.get_session(email, book_title)

        if not session:
            # No existing session - this shouldn't happen during navigation
            # The session should have been created when the book was opened
            logger.warning(
                f"No session found for {email}/{book_title} with key {client_session_key}. "
                f"Cannot calculate adjustment."
            )
            return 0  # No adjustment if no session exists

        if session.session_key == client_session_key:
            # Same session - the absolute position is correct, no adjustment needed
            # We're already at the right position
            return 0
        else:
            # Different session - client is continuing but we restarted
            # Client thinks they're at position X, but we know from our last session
            # they were at position Y. The difference is what we need to navigate.
            adjustment = client_position - session.position
            logger.info(
                f"Session key mismatch for {email}/{book_title}. "
                f"Client at position {client_position}, we last saw {session.position}. "
                f"Need to navigate {adjustment} pages."
            )
            return adjustment
