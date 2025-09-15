"""Repository for managing reading session operations."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from database.models import ReadingSession, User

logger = logging.getLogger(__name__)


class ReadingSessionRepository:
    """Repository for reading session operations."""

    def __init__(self, session: Session):
        """Initialize the repository with a database session.

        Args:
            session: SQLAlchemy session
        """
        self.session = session

    def start_session(
        self,
        email: str,
        book_title: str,
        session_key: Optional[str] = None,
        start_position: int = 0,
        firmware_version: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> ReadingSession:
        """Start a new reading session when a book is opened.

        Args:
            email: User's email address
            book_title: Title of the book being opened
            session_key: Client's session key (if provided)
            start_position: Starting position (usually 0, but could be different if resuming)
            firmware_version: Glasses/Sindarin firmware version from user agent
            user_agent: Full user agent string from request header

        Returns:
            ReadingSession object
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            raise ValueError(f"User not found: {email}")

        # Close any existing active sessions for this user/book
        existing_sessions = (
            self.session.query(ReadingSession)
            .filter_by(user_id=user.id, book_title=book_title, is_active=True)
            .all()
        )
        for session_obj in existing_sessions:
            session_obj.is_active = False
            session_obj.ended_at = datetime.now(timezone.utc)
            logger.info(f"Closed existing session {session_obj.id} for {email}/{book_title}")

        # Create new reading session
        reading_session = ReadingSession(
            user_id=user.id,
            book_title=book_title,
            session_key=session_key,
            start_position=start_position,
            current_position=start_position,
            max_position=start_position,
            firmware_version=firmware_version,
            user_agent=user_agent,
            started_at=datetime.now(timezone.utc),
            last_activity_at=datetime.now(timezone.utc),
            is_active=True,
        )

        self.session.add(reading_session)
        self.session.commit()

        logger.info(f"Started new reading session for {email}/{book_title} with session_key={session_key}")
        return reading_session

    def update_session_navigation(
        self,
        email: str,
        book_title: str,
        new_position: int,
        pages_navigated: int,
        session_key: Optional[str] = None,
    ) -> Optional[ReadingSession]:
        """Update session when user navigates.

        Args:
            email: User's email address
            book_title: Title of the book being navigated
            new_position: New position after navigation
            pages_navigated: Number of pages navigated (positive for forward, negative for backward)
            session_key: Client's session key to find the right session

        Returns:
            Updated ReadingSession or None if not found
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            logger.warning(f"User not found: {email}")
            return None

        # Find active session
        query = self.session.query(ReadingSession).filter_by(
            user_id=user.id, book_title=book_title, is_active=True
        )

        # If session_key provided, prefer that session
        if session_key:
            query = query.filter_by(session_key=session_key)

        reading_session = query.first()

        if not reading_session:
            logger.warning(f"No active reading session found for {email}/{book_title}")
            return None

        # Update position and stats
        reading_session.current_position = new_position
        reading_session.max_position = max(reading_session.max_position, new_position)
        reading_session.navigation_count += 1
        reading_session.last_activity_at = datetime.now(timezone.utc)

        # Update navigation stats
        if pages_navigated > 0:
            reading_session.total_pages_forward += pages_navigated
        else:
            reading_session.total_pages_backward += abs(pages_navigated)

        self.session.commit()

        logger.debug(
            f"Updated session for {email}/{book_title}: "
            f"position={new_position}, pages_navigated={pages_navigated}, "
            f"total_forward={reading_session.total_pages_forward}, "
            f"total_backward={reading_session.total_pages_backward}"
        )

        return reading_session

    def get_active_session(
        self, email: str, book_title: str, session_key: Optional[str] = None
    ) -> Optional[ReadingSession]:
        """Get the active reading session for a user and book.

        Args:
            email: User's email address
            book_title: Title of the book
            session_key: Optional session key to find specific session

        Returns:
            Active ReadingSession or None if not found
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            return None

        query = self.session.query(ReadingSession).filter_by(
            user_id=user.id, book_title=book_title, is_active=True
        )

        if session_key:
            query = query.filter_by(session_key=session_key)

        return query.first()

    def close_session(self, email: str, book_title: str) -> Optional[ReadingSession]:
        """Close an active reading session.

        Args:
            email: User's email address
            book_title: Title of the book

        Returns:
            Closed ReadingSession or None if not found
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            return None

        reading_session = (
            self.session.query(ReadingSession)
            .filter_by(user_id=user.id, book_title=book_title, is_active=True)
            .first()
        )

        if reading_session:
            reading_session.is_active = False
            reading_session.ended_at = datetime.now(timezone.utc)
            self.session.commit()
            logger.info(f"Closed reading session for {email}/{book_title}")

        return reading_session

    def close_timed_out_sessions(self, timeout_minutes: int = 30):
        """Close sessions that haven't had activity for a specified time.

        Args:
            timeout_minutes: Minutes of inactivity before closing session
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

        timed_out_sessions = (
            self.session.query(ReadingSession)
            .filter(
                and_(
                    ReadingSession.is_active == True,
                    ReadingSession.last_activity_at < cutoff_time,
                )
            )
            .all()
        )

        for session_obj in timed_out_sessions:
            session_obj.is_active = False
            session_obj.ended_at = datetime.now(timezone.utc)
            logger.info(
                f"Closed timed-out session {session_obj.id} (last activity: {session_obj.last_activity_at})"
            )

        if timed_out_sessions:
            self.session.commit()

        return len(timed_out_sessions)

    def get_user_reading_stats(self, email: str, days: int = 30):
        """Get reading statistics for a user.

        Args:
            email: User's email address
            days: Number of days to look back

        Returns:
            Dictionary with reading statistics
        """
        # Get user
        user = self.session.query(User).filter_by(email=email).first()
        if not user:
            return None

        # Calculate start date
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Get all sessions for this user in time period
        sessions = (
            self.session.execute(
                select(ReadingSession)
                .where(ReadingSession.user_id == user.id)
                .where(ReadingSession.started_at >= start_date)
                .order_by(ReadingSession.started_at.desc())
            )
            .scalars()
            .all()
        )

        # Calculate statistics
        total_sessions = len(sessions)
        active_sessions = sum(1 for s in sessions if s.is_active)
        unique_books = len(set(s.book_title for s in sessions))
        total_pages_read = sum(s.total_pages_forward for s in sessions)
        total_navigations = sum(s.navigation_count for s in sessions)
        reading_days = len(set(s.started_at.date() for s in sessions))

        # Calculate average session duration for completed sessions
        completed_sessions = [s for s in sessions if s.ended_at]
        if completed_sessions:
            total_duration = sum((s.ended_at - s.started_at).total_seconds() for s in completed_sessions)
            avg_session_minutes = round(total_duration / len(completed_sessions) / 60, 1)
        else:
            avg_session_minutes = 0

        return {
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "unique_books": unique_books,
            "total_pages_read": total_pages_read,
            "total_navigations": total_navigations,
            "reading_days": reading_days,
            "avg_pages_per_day": round(total_pages_read / max(reading_days, 1), 1),
            "avg_session_minutes": avg_session_minutes,
        }
