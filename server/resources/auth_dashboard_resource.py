"""Auth dashboard resource for tracking authentication issues and their impact on usage."""

import json
import logging
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import make_response, request
from flask_restful import Resource
from sqlalchemy import and_, func, select

from database.connection import db_connection
from database.models import (
    AuthTokenHistory,
    BookPosition,
    EmulatorShutdownFailure,
    ReadingSession,
    User,
    VNCInstance,
)

logger = logging.getLogger(__name__)


class AuthDashboardResource(Resource):
    """Resource for authentication-focused dashboard with impact metrics."""

    def get(self):
        """
        Get auth dashboard data or HTML page.

        Query params:
        - format: 'json' for data, 'html' for page (default: html)
        - days: Number of days to look back (default: 30)
        """
        # Note: Authentication is handled by the proxy server, not here
        # Check requested format
        response_format = request.args.get("format", "html").lower()
        days = int(request.args.get("days", 30))

        if response_format == "json":
            return self._get_dashboard_data(days)
        else:
            return self._get_dashboard_html()

    def _get_dashboard_data(self, days=30):
        """Get comprehensive dashboard data as JSON."""
        try:
            with db_connection.get_session() as session:
                now = datetime.now(timezone.utc)
                start_date = now - timedelta(days=days)

                # 1. Auth Token Metrics (primary focus)
                auth_metrics = self._get_auth_token_metrics(session, start_date)

                # 2. Firmware Version Metrics
                firmware_metrics = self._get_firmware_metrics(session)

                # 3. Usage Over Time
                usage_timeline = self._get_usage_timeline(session, start_date)

                # 4. Reading Activity Metrics
                reading_metrics = self._get_reading_metrics(session, start_date)

                # 5. System Health Metrics
                health_metrics = self._get_health_metrics(session, start_date)

                # Check if we're in development environment
                environment = os.getenv("ENVIRONMENT", "dev").upper()
                is_development = environment not in ["PROD", "STAGING"]

                return {
                    "success": True,
                    "period_days": days,
                    "generated_at": now.isoformat(),
                    "auth_metrics": auth_metrics,
                    "firmware_metrics": firmware_metrics,
                    "usage_timeline": usage_timeline,
                    "reading_metrics": reading_metrics,
                    "health_metrics": health_metrics,
                    "is_development": is_development,
                }, 200

        except Exception as e:
            logger.error(f"Error getting auth dashboard data: {e}", exc_info=True)
            return {"success": False, "error": str(e)}, 500

    def _get_auth_token_metrics(self, session, start_date):
        """Get metrics about auth token gains/losses and their impact using history table."""
        # Get all auth events in the period
        auth_events = (
            session.execute(
                select(AuthTokenHistory)
                .where(AuthTokenHistory.event_date >= start_date)
                .order_by(AuthTokenHistory.event_date)
            )
            .scalars()
            .all()
        )

        # Get auth loss events specifically
        auth_losses = [e for e in auth_events if e.event_type == "lost"]
        auth_gains = [e for e in auth_events if e.event_type == "gained"]

        # Calculate impact on usage for each auth loss
        auth_loss_impacts = []
        reading_momentum_lost = []  # Track heavy readers who stopped

        for loss_event in auth_losses:
            # Get usage 7 days before auth loss
            before_start = loss_event.event_date - timedelta(days=7)
            before_end = loss_event.event_date

            sessions_before = (
                session.execute(
                    select(func.count(ReadingSession.id)).where(
                        and_(
                            ReadingSession.user_id == loss_event.user_id,
                            ReadingSession.started_at >= before_start,
                            ReadingSession.started_at < before_end,
                        )
                    )
                ).scalar()
                or 0
            )

            # Get usage 7 days after auth loss
            after_start = loss_event.event_date
            after_end = loss_event.event_date + timedelta(days=7)

            sessions_after = (
                session.execute(
                    select(func.count(ReadingSession.id)).where(
                        and_(
                            ReadingSession.user_id == loss_event.user_id,
                            ReadingSession.started_at >= after_start,
                            ReadingSession.started_at < after_end,
                        )
                    )
                ).scalar()
                or 0
            )

            # Count unique books read before auth loss (7 days) as a proxy for engagement
            books_before = (
                session.execute(
                    select(func.count(func.distinct(ReadingSession.book_title))).where(
                        and_(
                            ReadingSession.user_id == loss_event.user_id,
                            ReadingSession.started_at >= before_start,
                            ReadingSession.started_at < before_end,
                        )
                    )
                ).scalar()
                or 0
            )

            # Count unique books after auth loss (7 days)
            books_after = (
                session.execute(
                    select(func.count(func.distinct(ReadingSession.book_title))).where(
                        and_(
                            ReadingSession.user_id == loss_event.user_id,
                            ReadingSession.started_at >= after_start,
                            ReadingSession.started_at < after_end,
                        )
                    )
                ).scalar()
                or 0
            )

            # Check if user recovered (re-authenticated) and when
            recovery_event = session.execute(
                select(AuthTokenHistory)
                .where(
                    and_(
                        AuthTokenHistory.user_id == loss_event.user_id,
                        AuthTokenHistory.event_type == "gained",
                        AuthTokenHistory.event_date > loss_event.event_date,
                    )
                )
                .order_by(AuthTokenHistory.event_date)
            ).scalar()

            recovery_days = None
            if recovery_event:
                recovery_days = (recovery_event.event_date - loss_event.event_date).days

            auth_loss_impacts.append(
                {
                    "date": loss_event.event_date.date().isoformat(),
                    "sessions_before": sessions_before,
                    "sessions_after": sessions_after,
                    "recovery_days": recovery_days,
                    "books_before": books_before,
                    "books_after": books_after,
                }
            )

            # Categorize by reading activity level before auth loss based on sessions
            activity_level = "light"  # < 3 sessions/week
            if sessions_before >= 10:
                activity_level = "heavy"  # 10+ sessions/week (1.5+ per day)
            elif sessions_before >= 3:
                activity_level = "moderate"  # 3-9 sessions/week

            reading_momentum_lost.append(
                {
                    "date": loss_event.event_date.date().isoformat(),
                    "activity_level": activity_level,
                    "sessions_before": sessions_before,
                    "sessions_after": sessions_after,
                    "books_before": books_before,
                    "books_after": books_after,
                    "stopped_reading": sessions_after == 0,
                }
            )

        # Group by date for aggregated view
        daily_impacts = defaultdict(lambda: {"sessions_before": 0, "sessions_after": 0, "count": 0})
        for impact in auth_loss_impacts:
            daily_impacts[impact["date"]]["sessions_before"] += impact["sessions_before"]
            daily_impacts[impact["date"]]["sessions_after"] += impact["sessions_after"]
            daily_impacts[impact["date"]]["count"] += 1

        # Create timeline of all auth events
        auth_timeline = defaultdict(lambda: {"gained": 0, "lost": 0})
        for event in auth_events:
            date_key = event.event_date.date().isoformat()
            auth_timeline[date_key][event.event_type] += 1

        # Group auth losses by day for simple histogram
        daily_auth_losses = defaultdict(int)
        for loss_event in auth_losses:
            date_key = loss_event.event_date.date().isoformat()
            daily_auth_losses[date_key] += 1

        # Analyze reading momentum lost by activity level
        momentum_by_level = {"heavy": 0, "moderate": 0, "light": 0}
        stopped_by_level = {"heavy": 0, "moderate": 0, "light": 0}

        for momentum in reading_momentum_lost:
            level = momentum["activity_level"]
            momentum_by_level[level] += 1
            if momentum["stopped_reading"]:
                stopped_by_level[level] += 1

        # Calculate recovery rate
        total_losses = len(auth_losses)
        recovered_count = len([i for i in auth_loss_impacts if i["recovery_days"] is not None])
        recovery_rate = round((recovered_count / max(total_losses, 1)) * 100, 1)

        # Average recovery time
        recovery_times = [i["recovery_days"] for i in auth_loss_impacts if i["recovery_days"] is not None]
        avg_recovery_days = round(sum(recovery_times) / len(recovery_times), 1) if recovery_times else 0

        # Calculate total users affected
        unique_users_affected = len(set(e.user_id for e in auth_losses))

        return {
            "total_auth_losses": len(auth_losses),
            "total_auth_gains": len(auth_gains),
            "unique_users_affected": unique_users_affected,
            "daily_impacts": dict(daily_impacts),
            "auth_timeline": dict(auth_timeline),
            "daily_auth_losses": dict(daily_auth_losses),
            "reading_momentum_lost": reading_momentum_lost,
            "momentum_by_level": momentum_by_level,
            "stopped_by_level": stopped_by_level,
            "recovery_rate": recovery_rate,
            "avg_recovery_days": avg_recovery_days,
            "auth_loss_impacts": auth_loss_impacts,
            "recent_auth_events": self._get_recent_auth_events(session, start_date),
        }

    def _get_recent_auth_events(self, session, start_date):
        """Get lists of users who recently gained or lost auth tokens."""
        # Get recent auth gained events with user details
        auth_gained = session.execute(
            select(AuthTokenHistory, User)
            .join(User, AuthTokenHistory.user_id == User.id)
            .where(
                and_(
                    AuthTokenHistory.event_type == "gained",
                    AuthTokenHistory.event_date >= start_date,
                )
            )
            .order_by(AuthTokenHistory.event_date.desc())
            .limit(50)
        ).all()

        # Get recent auth lost events with user details
        auth_lost = session.execute(
            select(AuthTokenHistory, User)
            .join(User, AuthTokenHistory.user_id == User.id)
            .where(
                and_(
                    AuthTokenHistory.event_type == "lost",
                    AuthTokenHistory.event_date >= start_date,
                )
            )
            .order_by(AuthTokenHistory.event_date.desc())
            .limit(50)
        ).all()

        # Format the results
        now = datetime.now(timezone.utc)
        gained_list = []
        for event, user in auth_gained:
            # Ensure event_date is timezone-aware
            event_date = event.event_date
            if event_date.tzinfo is None:
                event_date = event_date.replace(tzinfo=timezone.utc)

            gained_list.append(
                {
                    "email": user.email,
                    "date": event_date.isoformat(),
                    "date_formatted": event_date.strftime("%b %d, %Y %I:%M %p"),
                    "days_ago": (now - event_date).days,
                }
            )

        lost_list = []
        for event, user in auth_lost:
            # Ensure event_date is timezone-aware
            event_date = event.event_date
            if event_date.tzinfo is None:
                event_date = event_date.replace(tzinfo=timezone.utc)

            lost_list.append(
                {
                    "email": user.email,
                    "date": event_date.isoformat(),
                    "date_formatted": event_date.strftime("%b %d, %Y %I:%M %p"),
                    "days_ago": (now - event_date).days,
                }
            )

        return {
            "gained": gained_list,
            "lost": lost_list,
        }

    def _get_firmware_metrics(self, session):
        """Get metrics about Glasses/Sindarin firmware versions and their usage patterns."""
        import os
        import random
        from datetime import datetime, timedelta

        # Check if we're in development environment - NEVER show fake data in production or staging
        environment = os.getenv("ENVIRONMENT", "dev").upper()
        is_development = environment not in ["PROD", "STAGING"]

        # Get daily firmware usage from ReadingSession (last 30 days)
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

        # Query reading sessions with firmware versions in the last 30 days
        firmware_daily_usage = session.execute(
            select(
                func.date(ReadingSession.started_at).label("date"),
                ReadingSession.firmware_version,
                func.count(func.distinct(ReadingSession.user_id)).label("unique_users"),
                func.count(ReadingSession.id).label("sessions"),
            )
            .where(ReadingSession.started_at >= thirty_days_ago)
            .where(ReadingSession.firmware_version.isnot(None))
            .group_by(func.date(ReadingSession.started_at), ReadingSession.firmware_version)
            .order_by(func.date(ReadingSession.started_at).desc())
        ).all()

        # Organize by date and version
        daily_firmware_data = defaultdict(lambda: defaultdict(lambda: {"users": 0, "sessions": 0}))
        all_firmware_versions = set()

        # If we have real data, use it
        if firmware_daily_usage:
            for date, fw_version, users, sessions in firmware_daily_usage:
                date_str = date.isoformat() if hasattr(date, "isoformat") else str(date)
                daily_firmware_data[date_str][fw_version]["users"] = users
                daily_firmware_data[date_str][fw_version]["sessions"] = sessions
                all_firmware_versions.add(fw_version)
        elif is_development:
            # Bootstrap with demo data for visualization (ONLY IN DEVELOPMENT)
            versions = ["2.5.0", "2.5.99", "2.6.0"]
            all_firmware_versions = set(versions)

            # Generate daily data for last 30 days
            for days_ago in range(30):
                date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()
                date_str = date.isoformat()

                # Simulate gradual migration from 2.5.0 to 2.5.99 to 2.6.0
                if days_ago > 20:
                    # Older period - mostly 2.5.0
                    daily_firmware_data[date_str]["2.5.0"]["users"] = random.randint(15, 25)
                    daily_firmware_data[date_str]["2.5.0"]["sessions"] = random.randint(45, 75)
                    daily_firmware_data[date_str]["2.5.99"]["users"] = random.randint(2, 5)
                    daily_firmware_data[date_str]["2.5.99"]["sessions"] = random.randint(6, 15)
                elif days_ago > 10:
                    # Mid period - transition to 2.5.99
                    daily_firmware_data[date_str]["2.5.0"]["users"] = random.randint(8, 15)
                    daily_firmware_data[date_str]["2.5.0"]["sessions"] = random.randint(24, 45)
                    daily_firmware_data[date_str]["2.5.99"]["users"] = random.randint(10, 18)
                    daily_firmware_data[date_str]["2.5.99"]["sessions"] = random.randint(30, 54)
                    daily_firmware_data[date_str]["2.6.0"]["users"] = random.randint(0, 3)
                    daily_firmware_data[date_str]["2.6.0"]["sessions"] = random.randint(0, 9)
                else:
                    # Recent period - mostly 2.5.99, some 2.6.0
                    daily_firmware_data[date_str]["2.5.0"]["users"] = random.randint(2, 5)
                    daily_firmware_data[date_str]["2.5.0"]["sessions"] = random.randint(6, 15)
                    daily_firmware_data[date_str]["2.5.99"]["users"] = random.randint(12, 20)
                    daily_firmware_data[date_str]["2.5.99"]["sessions"] = random.randint(36, 60)
                    daily_firmware_data[date_str]["2.6.0"]["users"] = random.randint(3, 8)
                    daily_firmware_data[date_str]["2.6.0"]["sessions"] = random.randint(9, 24)

        # Calculate minutes read per firmware version
        # Using COALESCE to handle None values in ended_at (use last_activity_at if ended_at is null)
        firmware_minutes_read = session.execute(
            select(
                ReadingSession.firmware_version,
                func.sum(
                    func.extract(
                        "epoch",
                        func.coalesce(ReadingSession.ended_at, ReadingSession.last_activity_at)
                        - ReadingSession.started_at,
                    )
                    / 60
                ).label("total_minutes"),
                func.avg(
                    func.extract(
                        "epoch",
                        func.coalesce(ReadingSession.ended_at, ReadingSession.last_activity_at)
                        - ReadingSession.started_at,
                    )
                    / 60
                ).label("avg_minutes_per_session"),
            )
            .where(ReadingSession.firmware_version.isnot(None))
            .where(ReadingSession.started_at >= thirty_days_ago)
            .group_by(ReadingSession.firmware_version)
            .order_by(
                func.sum(
                    func.extract(
                        "epoch",
                        func.coalesce(ReadingSession.ended_at, ReadingSession.last_activity_at)
                        - ReadingSession.started_at,
                    )
                    / 60
                ).desc()
            )
        ).all()

        # Get overall firmware version counts
        firmware_counts = session.execute(
            select(
                ReadingSession.firmware_version,
                func.count(func.distinct(ReadingSession.user_id)).label("unique_users"),
                func.count(ReadingSession.id).label("total_sessions"),
            )
            .where(ReadingSession.firmware_version.isnot(None))
            .group_by(ReadingSession.firmware_version)
            .order_by(func.count(ReadingSession.id).desc())
        ).all()

        # Process firmware minutes read data
        firmware_minutes_data = {}
        if firmware_minutes_read:
            for fw_version, total_min, avg_min in firmware_minutes_read:
                firmware_minutes_data[fw_version] = {
                    "total_minutes": round(float(total_min), 1) if total_min else 0,
                    "avg_minutes_per_session": round(float(avg_min), 1) if avg_min else 0,
                }
        elif is_development:
            # Bootstrap with demo minutes read data (ONLY IN DEVELOPMENT)
            firmware_minutes_data = {
                "2.5.0": {"total_minutes": 1250.5, "avg_minutes_per_session": 15.3},
                "2.5.99": {"total_minutes": 3780.2, "avg_minutes_per_session": 22.7},
                "2.6.0": {"total_minutes": 890.8, "avg_minutes_per_session": 18.5},
            }

        firmware_summary = {}
        if firmware_counts:
            for fw_version, users, sessions in firmware_counts:
                firmware_summary[fw_version] = {
                    "unique_users": users,
                    "total_sessions": sessions,
                    "avg_sessions_per_user": round(sessions / max(users, 1), 1),
                }
        elif is_development:
            # Bootstrap with demo summary data (ONLY IN DEVELOPMENT)
            firmware_summary = {
                "2.5.0": {"unique_users": 25, "total_sessions": 450, "avg_sessions_per_user": 18.0},
                "2.5.99": {"unique_users": 42, "total_sessions": 1260, "avg_sessions_per_user": 30.0},
                "2.6.0": {"unique_users": 8, "total_sessions": 180, "avg_sessions_per_user": 22.5},
            }
            # Update firmware_counts for most_popular_version calculation
            firmware_counts = [("2.5.99", 42, 1260), ("2.5.0", 25, 450), ("2.6.0", 8, 180)]

        return {
            "daily_firmware_data": dict(daily_firmware_data),
            "all_firmware_versions": sorted(list(all_firmware_versions)),
            "firmware_summary": firmware_summary,
            "firmware_minutes_data": firmware_minutes_data,
            "most_popular_version": (
                max(firmware_counts, key=lambda x: x[2])[0] if firmware_counts else None
            ),
        }

    def _get_usage_timeline(self, session, start_date):
        """Get daily usage metrics over time."""
        # Daily active users - based on ReadingSession activity
        daily_active = defaultdict(set)
        reading_sessions = (
            session.execute(select(ReadingSession).where(ReadingSession.started_at >= start_date))
            .scalars()
            .all()
        )

        for reading_session in reading_sessions:
            # Track both start date and last activity date
            start_date_key = reading_session.started_at.date().isoformat()
            daily_active[start_date_key].add(reading_session.user_id)

            # Also track activity date if different from start
            if reading_session.last_activity_at:
                activity_date_key = reading_session.last_activity_at.date().isoformat()
                daily_active[activity_date_key].add(reading_session.user_id)

        # Convert to counts
        daily_active_counts = {date: len(users) for date, users in daily_active.items()}

        # Daily new users
        new_users = session.execute(select(User).where(User.created_at >= start_date)).scalars().all()
        daily_new = defaultdict(int)
        for user in new_users:
            date_key = user.created_at.date().isoformat()
            daily_new[date_key] += 1

        # Daily reading sessions - count actual reading sessions
        daily_reading_sessions = defaultdict(int)
        for reading_session in reading_sessions:
            date_key = reading_session.started_at.date().isoformat()
            daily_reading_sessions[date_key] += 1

        # Daily book interactions and unique books
        daily_book_interactions = defaultdict(int)
        unique_books_read = defaultdict(set)
        for reading_session in reading_sessions:
            date_key = reading_session.started_at.date().isoformat()
            # Count navigation events as interactions
            daily_book_interactions[date_key] += 1 + reading_session.navigation_count
            unique_books_read[date_key].add(reading_session.book_title)

        return {
            "daily_active_users": dict(daily_active_counts),
            "daily_new_users": dict(daily_new),
            "daily_sessions": dict(daily_reading_sessions),  # Actual reading sessions
            "daily_book_interactions": dict(daily_book_interactions),  # Sessions + navigations
            "daily_unique_books": {date: len(books) for date, books in unique_books_read.items()},
            "total_active_users": len(set(rs.user_id for rs in reading_sessions)),
            "total_new_users": len(new_users),
            "total_sessions": len(reading_sessions),
        }

    def _get_reading_metrics(self, session, start_date):
        """Get reading behavior metrics."""
        # Most read books based on ReadingSession
        reading_sessions = session.execute(
            select(
                ReadingSession.book_title,
                func.count(ReadingSession.id).label("session_count"),
                func.count(func.distinct(ReadingSession.user_id)).label("unique_readers"),
                func.sum(ReadingSession.navigation_count).label("total_navigations"),
                func.avg(ReadingSession.navigation_count).label("avg_navigations"),
            )
            .where(ReadingSession.started_at >= start_date)
            .group_by(ReadingSession.book_title)
            .order_by(func.count(ReadingSession.id).desc())
            .limit(10)
        ).all()

        return {
            "most_read_books": [
                {
                    "title": book[0][:50],  # Truncate long titles
                    "sessions": book[1],
                    "unique_readers": book[2],
                    "total_navigations": int(book[3]) if book[3] else 0,
                    "avg_navigations": round(float(book[4]), 1) if book[4] else 0,
                }
                for book in reading_sessions
            ],
        }

    def _get_health_metrics(self, session, start_date):
        """Get system health metrics."""
        # Count active emulators
        active_emulators = (
            session.execute(
                select(func.count(func.distinct(VNCInstance.emulator_id))).where(
                    VNCInstance.created_at >= start_date
                )
            ).scalar()
            or 0
        )

        # Count shutdown failures
        failures = (
            session.execute(
                select(EmulatorShutdownFailure).where(EmulatorShutdownFailure.created_at >= start_date)
            )
            .scalars()
            .all()
        )

        # Calculate failure rate
        days = (datetime.now(timezone.utc) - start_date).days

        return {
            "active_emulators": active_emulators,
            "total_failures": len(failures),
            "failure_rate": (
                round((len(failures) / max(active_emulators * days, 1)) * 100, 2) if active_emulators else 0
            ),
        }

    def _get_dashboard_html(self):
        """Serve the auth dashboard HTML page from template."""
        import os
        from pathlib import Path

        # Get the template file path
        template_path = Path(__file__).parent.parent / "templates" / "auth_dashboard.html"

        # Read the template file
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                html_content = f.read()
        except FileNotFoundError:
            # Return error if template not found
            logger.error(f"Template file not found at {template_path}")
            return {"error": "Dashboard template not found"}, 500
        except Exception as e:
            logger.error(f"Error loading dashboard template: {e}")
            return {"error": "Failed to load dashboard template"}, 500

        response = make_response(html_content)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response
