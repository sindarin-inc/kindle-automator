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
        self,
        email: str,
        book_title: str,
        session_key: str,
        position: int = 0,
        firmware_version: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> BookSession:
        """Get existing session or create a new one.

        Args:
            email: User's email address
            book_title: Title of the book
            session_key: Client's session key
            position: Initial position if creating new session
            firmware_version: Glasses/Sindarin firmware version from user agent
            user_agent: Full user agent string from request header

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
            # Update firmware version if provided
            if firmware_version:
                book_session.firmware_version = firmware_version
            # Update user agent if provided
            if user_agent:
                book_session.user_agent = user_agent
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
                firmware_version=firmware_version,
                user_agent=user_agent,
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

    def reset_session(
        self,
        email: str,
        book_title: str,
        new_session_key: str,
        firmware_version: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[BookSession]:
        """Reset a book session with a new session key and position 0.
        Used when /open-book is called.

        Args:
            email: User's email address
            book_title: Title of the book
            new_session_key: New session key to set
            firmware_version: Optional Glasses/Sindarin firmware version from user agent
            user_agent: Optional full user agent string from request header

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
            # Store the previous session data before resetting
            # This allows us to handle navigation requests with the old session key
            book_session.previous_session_key = book_session.session_key
            book_session.previous_position = book_session.position

            # Reset to new session
            book_session.session_key = new_session_key
            book_session.position = 0
            if firmware_version:
                book_session.firmware_version = firmware_version
            if user_agent:
                book_session.user_agent = user_agent
            book_session.last_accessed = datetime.now(timezone.utc)
            logger.info(
                f"Reset book session for {email}/{book_title} with new key {new_session_key}. "
                f"Preserved old session {book_session.previous_session_key} at position {book_session.previous_position}"
            )
        else:
            # Create new session
            book_session = BookSession(
                user_id=user.id,
                book_title=book_title,
                session_key=new_session_key,
                position=0,
                firmware_version=firmware_version,
                user_agent=user_agent,
                last_accessed=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
            )
            self.session.add(book_session)
            logger.info(f"Created new book session for {email}/{book_title} with key {new_session_key}")

        self.session.commit()
        return book_session

    def calculate_position_adjustment(
        self, email: str, book_title: str, client_session_key: str, target_position: int
    ) -> tuple[int, bool, str]:
        """Calculate the position adjustment needed to reach the target position.

        This method handles three scenarios:
        1. Same session: Calculate adjustment from current position to target
        2. Client has old session key: Restore from previous session and adjust
        3. Unknown session: Reject navigation and signal client to reset

        Args:
            email: User's email address
            book_title: Title of the book
            client_session_key: Client's session key
            target_position: Position the client wants to navigate to

        Returns:
            Tuple of (adjustment, success, current_session_key):
            - adjustment: Pages to navigate (0 if failed)
            - success: Whether navigation should proceed
            - current_session_key: The server's current session key
        """
        session = self.get_session(email, book_title)

        if not session:
            # No existing session - this shouldn't happen during navigation
            # The session should have been created when the book was opened
            logger.warning(
                f"No session found for {email}/{book_title} with key {client_session_key}. "
                f"Cannot calculate adjustment."
            )
            return (0, False, "")  # Fail navigation, no session

        if session.session_key == client_session_key:
            # Same session - normal navigation
            adjustment = target_position - session.position
            if adjustment != 0:
                logger.info(
                    f"Same session for {email}/{book_title}. "
                    f"Current position {session.position}, target {target_position}. "
                    f"Need to navigate {adjustment} pages."
                )
            return (adjustment, True, session.session_key)
        elif session.previous_session_key and session.previous_session_key == client_session_key:
            # Client is using the old session key - they think they're at the old position
            # We need to restore their context by adopting their session key
            old_position = session.previous_position or 0

            # Update our session to match the client's session
            session.session_key = client_session_key
            session.position = old_position
            # Clear the previous session data since we've adopted it
            session.previous_session_key = None
            session.previous_position = None
            self.session.commit()

            # Now calculate adjustment from the restored position
            adjustment = target_position - old_position
            logger.info(
                f"Restored old session for {email}/{book_title}. "
                f"Client session {client_session_key} was at position {old_position}, "
                f"target {target_position}. Need to navigate {adjustment} pages."
            )
            return (adjustment, True, client_session_key)
        else:
            # Unknown session key - client needs to reset their position tracking
            logger.warning(
                f"Session key mismatch for {email}/{book_title}. "
                f"Client key '{client_session_key}' doesn't match current '{session.session_key}' "
                f"or previous '{session.previous_session_key}'. Navigation rejected."
            )
            # Return the current session key so client can sync
            return (0, False, session.session_key)
