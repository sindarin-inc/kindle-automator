#!/usr/bin/env python3
"""
Bootstrap script to analyze auth metrics from existing User data.

This script:
1. Reads existing User records with auth_date and auth_failed_date
2. Analyzes auth gained/lost patterns
3. Analyzes BookSession data to check firmware versions
4. Shows what metrics the dashboard will display

Run with: uv run python scripts/bootstrap_auth_metrics.py

Since AuthEvent table doesn't exist yet, this script analyzes the existing
User.auth_date and User.auth_failed_date fields to show what data we have.
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
load_dotenv(project_root / ".env")

from sqlalchemy import and_, func, select

from database.connection import DatabaseConnection
from database.models import BookSession, User


def analyze_auth_events(session):
    """Analyze auth events from existing User auth dates."""
    print("\n=== Analyzing Auth Events from User Table ===")

    # Get all users with auth_date (gained auth)
    users_with_auth = session.execute(select(User).where(User.auth_date.isnot(None))).scalars().all()

    print(f"Found {len(users_with_auth)} users with auth_date (gained auth)")

    # Get all users with auth_failed_date (lost auth)
    users_lost_auth = session.execute(select(User).where(User.auth_failed_date.isnot(None))).scalars().all()

    print(f"Found {len(users_lost_auth)} users with auth_failed_date (lost auth)")

    # Group by date for timeline analysis
    auth_gained_by_date = defaultdict(int)
    auth_lost_by_date = defaultdict(int)

    for user in users_with_auth:
        if user.auth_date:
            date_key = user.auth_date.date().isoformat()
            auth_gained_by_date[date_key] += 1

    for user in users_lost_auth:
        if user.auth_failed_date:
            date_key = user.auth_failed_date.date().isoformat()
            auth_lost_by_date[date_key] += 1

    # Show recent auth events
    print("\nRecent Auth Gained Events (last 30 days):")
    recent_date = datetime.now(timezone.utc) - timedelta(days=30)
    recent_gained = sorted(
        [
            (date, count)
            for date, count in auth_gained_by_date.items()
            if datetime.fromisoformat(date).replace(tzinfo=timezone.utc) >= recent_date
        ],
        reverse=True,
    )[:10]

    for date, count in recent_gained:
        print(f"  {date}: {count} users")

    print("\nRecent Auth Lost Events (last 30 days):")
    recent_lost = sorted(
        [
            (date, count)
            for date, count in auth_lost_by_date.items()
            if datetime.fromisoformat(date).replace(tzinfo=timezone.utc) >= recent_date
        ],
        reverse=True,
    )[:10]

    for date, count in recent_lost:
        print(f"  {date}: {count} users")

    return len(users_with_auth), len(users_lost_auth)


def analyze_existing_sessions(session):
    """Analyze existing BookSession data for firmware versions and patterns."""
    print("\n=== Analyzing Existing Sessions ===")

    # Count sessions with firmware versions
    fw_count = session.execute(
        select(func.count(BookSession.id)).where(BookSession.firmware_version.isnot(None))
    ).scalar()

    print(f"Sessions with firmware version: {fw_count}")

    if fw_count > 0:
        # Get firmware version distribution
        fw_dist = session.execute(
            select(
                BookSession.firmware_version,
                func.count(BookSession.id).label("count"),
                func.count(func.distinct(BookSession.user_id)).label("users"),
            )
            .where(BookSession.firmware_version.isnot(None))
            .group_by(BookSession.firmware_version)
            .order_by(func.count(BookSession.id).desc())
        ).all()

        print("\nFirmware Distribution:")
        for version, count, users in fw_dist:
            print(f"  v{version}: {count} sessions, {users} users")

    # Count total sessions for context
    total_sessions = session.execute(select(func.count(BookSession.id))).scalar()

    print(f"\nTotal BookSessions: {total_sessions}")

    # Get date range of sessions
    date_range = session.execute(
        select(func.min(BookSession.created_at), func.max(BookSession.created_at))
    ).first()

    if date_range and date_range[0]:
        print(f"Session date range: {date_range[0].date()} to {date_range[1].date()}")

    return fw_count, total_sessions


def generate_auth_impact_analysis(session):
    """Analyze the impact of auth losses on reading behavior."""
    print("\n=== Analyzing Auth Loss Impact ===")

    # Get all users who lost auth
    users_lost_auth = (
        session.execute(select(User).where(User.auth_failed_date.isnot(None)).order_by(User.auth_failed_date))
        .scalars()
        .all()
    )

    print(f"Analyzing {len(users_lost_auth)} users who lost auth...")

    impact_summary = {"stopped_completely": 0, "reduced_activity": 0, "no_impact": 0, "recovered": 0}

    for user in users_lost_auth:
        # Check reading activity 7 days before and after auth loss
        loss_date = user.auth_failed_date
        before_date = loss_date - timedelta(days=7)
        after_date = loss_date + timedelta(days=7)

        # Count sessions before auth loss
        sessions_before = session.execute(
            select(func.count(BookSession.id)).where(
                and_(
                    BookSession.user_id == user.id,
                    BookSession.created_at >= before_date,
                    BookSession.created_at < loss_date,
                )
            )
        ).scalar()

        # Count sessions after auth loss
        sessions_after = session.execute(
            select(func.count(BookSession.id)).where(
                and_(
                    BookSession.user_id == user.id,
                    BookSession.created_at >= loss_date,
                    BookSession.created_at < after_date,
                )
            )
        ).scalar()

        # Check if user recovered (got auth back by having a new auth_date after the loss)
        if user.auth_date and user.auth_date > user.auth_failed_date:
            impact_summary["recovered"] += 1

        if sessions_after == 0:
            impact_summary["stopped_completely"] += 1
        elif sessions_after < sessions_before * 0.5:
            impact_summary["reduced_activity"] += 1
        else:
            impact_summary["no_impact"] += 1

    print("\nAuth Loss Impact Summary:")
    for key, value in impact_summary.items():
        print(f"  {key.replace('_', ' ').title()}: {value}")

    return impact_summary


def main():
    """Main bootstrap function."""
    print("=" * 60)
    print("AUTH METRICS BOOTSTRAP SCRIPT")
    print("=" * 60)

    # Parse arguments
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***")

    # Initialize database connection
    db_connection = DatabaseConnection()
    db_connection.initialize()

    with db_connection.get_session() as session:
        try:
            # 1. Analyze auth events from User table
            auth_gained, auth_lost = analyze_auth_events(session)

            # 2. Analyze existing sessions
            fw_count, total_sessions = analyze_existing_sessions(session)

            # 3. Generate auth impact analysis
            impact_summary = generate_auth_impact_analysis(session)

            print("\n" + "=" * 60)
            print("ANALYSIS COMPLETE")
            print("=" * 60)

            print(f"\nSummary:")
            print(f"  - {auth_gained} users have gained auth")
            print(f"  - {auth_lost} users have lost auth")
            print(f"  - {total_sessions} total book sessions")
            print(f"  - {fw_count} sessions with firmware data")

            if fw_count == 0:
                print("\nNOTE: No firmware version data found in BookSessions.")
                print("Firmware charts will populate as new sessions are created.")

            print("\nThe dashboard will use User.auth_date and User.auth_failed_date")
            print("fields to display auth metrics.")

        except Exception as e:
            print(f"\nERROR: {e}")
            session.rollback()
            raise


if __name__ == "__main__":
    main()
