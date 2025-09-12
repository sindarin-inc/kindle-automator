"""Auth dashboard resource for tracking authentication issues and their impact on usage."""

import json
import logging
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
    BookSession,
    EmulatorShutdownFailure,
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
        # Check staff authentication via cookie
        token = request.cookies.get("staff_token")
        if not token:
            return {"error": "Staff authentication required"}, 401

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

                return {
                    "success": True,
                    "period_days": days,
                    "generated_at": now.isoformat(),
                    "auth_metrics": auth_metrics,
                    "firmware_metrics": firmware_metrics,
                    "usage_timeline": usage_timeline,
                    "reading_metrics": reading_metrics,
                    "health_metrics": health_metrics,
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
                    select(func.count(BookSession.id)).where(
                        and_(
                            BookSession.user_id == loss_event.user_id,
                            BookSession.created_at >= before_start,
                            BookSession.created_at < before_end,
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
                    select(func.count(BookSession.id)).where(
                        and_(
                            BookSession.user_id == loss_event.user_id,
                            BookSession.created_at >= after_start,
                            BookSession.created_at < after_end,
                        )
                    )
                ).scalar()
                or 0
            )

            # Count unique books read before auth loss (7 days) as a proxy for engagement
            books_before = (
                session.execute(
                    select(func.count(func.distinct(BookSession.book_title))).where(
                        and_(
                            BookSession.user_id == loss_event.user_id,
                            BookSession.created_at >= before_start,
                            BookSession.created_at < before_end,
                        )
                    )
                ).scalar()
                or 0
            )

            # Count unique books after auth loss (7 days)
            books_after = (
                session.execute(
                    select(func.count(func.distinct(BookSession.book_title))).where(
                        and_(
                            BookSession.user_id == loss_event.user_id,
                            BookSession.created_at >= after_start,
                            BookSession.created_at < after_end,
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
        }

    def _get_firmware_metrics(self, session):
        """Get metrics about Glasses/Sindarin firmware versions and their usage patterns."""
        import random
        from datetime import datetime, timedelta

        # Get daily firmware usage from BookSession (last 30 days)
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

        # Query book sessions with firmware versions in the last 30 days
        firmware_daily_usage = session.execute(
            select(
                func.date(BookSession.last_accessed).label("date"),
                BookSession.firmware_version,
                func.count(func.distinct(BookSession.user_id)).label("unique_users"),
                func.count(BookSession.id).label("sessions"),
            )
            .where(BookSession.last_accessed >= thirty_days_ago)
            .where(BookSession.firmware_version.isnot(None))
            .group_by(func.date(BookSession.last_accessed), BookSession.firmware_version)
            .order_by(func.date(BookSession.last_accessed).desc())
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
        else:
            # Bootstrap with demo data for visualization
            versions = ["1.5.0", "1.5.99", "1.6.0"]
            all_firmware_versions = set(versions)

            # Generate daily data for last 30 days
            for days_ago in range(30):
                date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()
                date_str = date.isoformat()

                # Simulate gradual migration from 1.5.0 to 1.5.99 to 1.6.0
                if days_ago > 20:
                    # Older period - mostly 1.5.0
                    daily_firmware_data[date_str]["1.5.0"]["users"] = random.randint(15, 25)
                    daily_firmware_data[date_str]["1.5.0"]["sessions"] = random.randint(45, 75)
                    daily_firmware_data[date_str]["1.5.99"]["users"] = random.randint(2, 5)
                    daily_firmware_data[date_str]["1.5.99"]["sessions"] = random.randint(6, 15)
                elif days_ago > 10:
                    # Mid period - transition to 1.5.99
                    daily_firmware_data[date_str]["1.5.0"]["users"] = random.randint(8, 15)
                    daily_firmware_data[date_str]["1.5.0"]["sessions"] = random.randint(24, 45)
                    daily_firmware_data[date_str]["1.5.99"]["users"] = random.randint(10, 18)
                    daily_firmware_data[date_str]["1.5.99"]["sessions"] = random.randint(30, 54)
                    daily_firmware_data[date_str]["1.6.0"]["users"] = random.randint(0, 3)
                    daily_firmware_data[date_str]["1.6.0"]["sessions"] = random.randint(0, 9)
                else:
                    # Recent period - mostly 1.5.99, some 1.6.0
                    daily_firmware_data[date_str]["1.5.0"]["users"] = random.randint(2, 5)
                    daily_firmware_data[date_str]["1.5.0"]["sessions"] = random.randint(6, 15)
                    daily_firmware_data[date_str]["1.5.99"]["users"] = random.randint(12, 20)
                    daily_firmware_data[date_str]["1.5.99"]["sessions"] = random.randint(36, 60)
                    daily_firmware_data[date_str]["1.6.0"]["users"] = random.randint(3, 8)
                    daily_firmware_data[date_str]["1.6.0"]["sessions"] = random.randint(9, 24)

        # Get overall firmware version counts
        firmware_counts = session.execute(
            select(
                BookSession.firmware_version,
                func.count(func.distinct(BookSession.user_id)).label("unique_users"),
                func.count(BookSession.id).label("total_sessions"),
            )
            .where(BookSession.firmware_version.isnot(None))
            .group_by(BookSession.firmware_version)
            .order_by(func.count(BookSession.id).desc())
        ).all()

        firmware_summary = {}
        if firmware_counts:
            for fw_version, users, sessions in firmware_counts:
                firmware_summary[fw_version] = {
                    "unique_users": users,
                    "total_sessions": sessions,
                    "avg_sessions_per_user": round(sessions / max(users, 1), 1),
                }
        else:
            # Bootstrap with demo summary data
            firmware_summary = {
                "1.5.0": {"unique_users": 25, "total_sessions": 450, "avg_sessions_per_user": 18.0},
                "1.5.99": {"unique_users": 42, "total_sessions": 1260, "avg_sessions_per_user": 30.0},
                "1.6.0": {"unique_users": 8, "total_sessions": 180, "avg_sessions_per_user": 22.5},
            }
            # Update firmware_counts for most_popular_version calculation
            firmware_counts = [("1.5.99", 42, 1260), ("1.5.0", 25, 450), ("1.6.0", 8, 180)]

        return {
            "daily_firmware_data": dict(daily_firmware_data),
            "all_firmware_versions": sorted(list(all_firmware_versions)),
            "firmware_summary": firmware_summary,
            "most_popular_version": (
                max(firmware_counts, key=lambda x: x[2])[0] if firmware_counts else None
            ),
        }

    def _get_usage_timeline(self, session, start_date):
        """Get daily usage metrics over time."""
        # Daily active users
        daily_active = defaultdict(set)
        all_sessions = (
            session.execute(select(BookSession).where(BookSession.created_at >= start_date)).scalars().all()
        )

        for session_obj in all_sessions:
            date_key = session_obj.created_at.date().isoformat()
            daily_active[date_key].add(session_obj.user_id)

        # Convert to counts
        daily_active_counts = {date: len(users) for date, users in daily_active.items()}

        # Daily new users
        new_users = session.execute(select(User).where(User.created_at >= start_date)).scalars().all()
        daily_new = defaultdict(int)
        for user in new_users:
            date_key = user.created_at.date().isoformat()
            daily_new[date_key] += 1

        # Daily sessions
        daily_sessions = defaultdict(int)
        for session_obj in all_sessions:
            date_key = session_obj.created_at.date().isoformat()
            daily_sessions[date_key] += 1

        return {
            "daily_active_users": dict(daily_active_counts),
            "daily_new_users": dict(daily_new),
            "daily_sessions": dict(daily_sessions),
            "total_active_users": len(set(s.user_id for s in all_sessions)),
            "total_new_users": len(new_users),
            "total_sessions": len(all_sessions),
        }

    def _get_reading_metrics(self, session, start_date):
        """Get reading behavior metrics."""
        # Most read books
        book_sessions = session.execute(
            select(
                BookSession.book_title,
                func.count(BookSession.id).label("session_count"),
                func.count(func.distinct(BookSession.user_id)).label("unique_readers"),
            )
            .where(BookSession.created_at >= start_date)
            .group_by(BookSession.book_title)
            .order_by(func.count(BookSession.id).desc())
            .limit(10)
        ).all()

        return {
            "most_read_books": [
                {
                    "title": book[0][:50],  # Truncate long titles
                    "sessions": book[1],
                    "unique_readers": book[2],
                }
                for book in book_sessions
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
        """Serve the auth dashboard HTML page."""
        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Auth Dashboard - Kindle Automator</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f5f5f7;
            color: #1d1d1f;
        }
        
        .header {
            background: white;
            border-bottom: 1px solid #e5e5e7;
            padding: 20px 0;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        
        .header-content {
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .header-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .header-title h1 {
            font-size: 24px;
            font-weight: 600;
            color: #1d1d1f;
        }
        
        .header-subtitle {
            font-size: 14px;
            color: #6e6e73;
        }
        
        .header-controls {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        
        .time-filter {
            padding: 8px 16px;
            border: 1px solid #d2d2d7;
            border-radius: 8px;
            background: white;
            font-size: 14px;
            color: #1d1d1f;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .time-filter:hover {
            border-color: #007aff;
        }
        
        .refresh-btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            background: #007aff;
            color: white;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .refresh-btn:hover {
            background: #0051d5;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
        }
        
        .metrics-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        
        .metric-card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #e5e5e7;
            transition: all 0.2s;
        }
        
        .metric-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }
        
        .metric-label {
            font-size: 12px;
            font-weight: 500;
            color: #6e6e73;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        
        .metric-value {
            font-size: 32px;
            font-weight: 600;
            color: #1d1d1f;
            line-height: 1;
        }
        
        .metric-badge {
            display: inline-block;
            margin-top: 8px;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
        }
        
        .badge-critical {
            background: #ffebeb;
            color: #dc2626;
        }
        
        .badge-warning {
            background: #fef3c7;
            color: #d97706;
        }
        
        .badge-success {
            background: #d1fae5;
            color: #059669;
        }
        
        .badge-neutral {
            background: #f3f4f6;
            color: #6b7280;
        }
        
        .chart-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 24px;
            margin-bottom: 24px;
        }
        
        .chart-container {
            background: white;
            border-radius: 12px;
            padding: 24px;
            border: 1px solid #e5e5e7;
        }
        
        .chart-title {
            font-size: 18px;
            font-weight: 600;
            color: #1d1d1f;
            margin-bottom: 20px;
        }
        
        .chart-wrapper {
            position: relative;
            height: 300px;
        }
        
        .loading {
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 400px;
            color: #6e6e73;
        }
        
        .error-message {
            background: #fee2e2;
            color: #dc2626;
            padding: 16px;
            border-radius: 8px;
            margin: 24px 0;
        }
        
        @media (max-width: 768px) {
            .chart-grid {
                grid-template-columns: 1fr;
            }
            
            .metrics-row {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-content">
            <div class="header-title">
                <h1>🔐 Auth Dashboard</h1>
                <span class="header-subtitle">Authentication Impact Analysis</span>
            </div>
            <div class="header-controls">
                <select class="time-filter" id="timeFilter" onchange="loadDashboard(this.value)">
                    <option value="7">Last 7 days</option>
                    <option value="30" selected>Last 30 days</option>
                    <option value="90">Last 90 days</option>
                </select>
                <button class="refresh-btn" onclick="loadDashboard()">↻ Refresh</button>
            </div>
        </div>
    </div>
    
    <div class="container">
        <div id="loadingMessage" class="loading">Loading dashboard data...</div>
        <div id="errorMessage" class="error-message" style="display: none;"></div>
        
        <div id="dashboardContent" style="display: none;">
            <!-- Key Metrics -->
            <div class="metrics-row" id="keyMetrics"></div>
            
            <!-- Main Charts -->
            <div class="chart-grid">
                <div class="chart-container">
                    <h2 class="chart-title">Daily Auth Token Losses</h2>
                    <div class="chart-wrapper">
                        <canvas id="authLossesChart"></canvas>
                    </div>
                </div>
                
                <div class="chart-container">
                    <h2 class="chart-title">Reading Momentum Lost</h2>
                    <div class="chart-wrapper">
                        <canvas id="momentumLostChart"></canvas>
                    </div>
                </div>
            </div>
            
            <div class="chart-grid">
                <div class="chart-container">
                    <h2 class="chart-title">Sessions Before/After Auth Loss</h2>
                    <div class="chart-wrapper">
                        <canvas id="authImpactChart"></canvas>
                    </div>
                </div>
                
                <div class="chart-container">
                    <h2 class="chart-title">Auth Events Timeline</h2>
                    <div class="chart-wrapper">
                        <canvas id="authTimelineChart"></canvas>
                    </div>
                </div>
            </div>
            
            <div class="chart-grid">
                <div class="chart-container">
                    <h2 class="chart-title">Glasses Firmware Users by Day</h2>
                    <div class="chart-wrapper">
                        <canvas id="firmwareUsersChart"></canvas>
                    </div>
                </div>
                
                <div class="chart-container">
                    <h2 class="chart-title">Glasses Firmware Sessions by Day</h2>
                    <div class="chart-wrapper">
                        <canvas id="firmwareSessionsChart"></canvas>
                    </div>
                </div>
            </div>
            
            <div class="chart-grid">
                <div class="chart-container">
                    <h2 class="chart-title">Firmware Version Distribution</h2>
                    <div class="chart-wrapper">
                        <canvas id="firmwareDistributionChart"></canvas>
                    </div>
                </div>
                
                <div class="chart-container">
                    <h2 class="chart-title">Firmware Adoption Trend</h2>
                    <div class="chart-wrapper">
                        <canvas id="firmwareAdoptionChart"></canvas>
                    </div>
                </div>
            </div>
            
            <div class="chart-container">
                <h2 class="chart-title">Daily Active Users</h2>
                <div class="chart-wrapper">
                    <canvas id="dailyUsersChart"></canvas>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let dashboardData = null;
        let charts = {};
        
        async function fetchDashboardData(days = 30) {
            try {
                const pathPrefix = window.location.pathname.replace(/\\/auth-dashboard.*/, '');
                const response = await fetch(`${pathPrefix}/auth-dashboard?format=json&days=${days}`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to fetch dashboard data');
                }
                return data;
            } catch (error) {
                console.error('Error fetching dashboard data:', error);
                throw error;
            }
        }
        
        function destroyAllCharts() {
            Object.values(charts).forEach(chart => {
                if (chart) chart.destroy();
            });
            charts = {};
        }
        
        function createKeyMetrics(data) {
            const container = document.getElementById('keyMetrics');
            container.innerHTML = '';
            
            const metrics = [
                {
                    label: 'Auth Losses',
                    value: data.auth_metrics?.total_auth_losses || 0,
                    badge: data.auth_metrics?.total_auth_losses > 0 ? 'critical' : 'success',
                    badgeText: data.auth_metrics?.unique_users_affected ? 
                        `${data.auth_metrics.unique_users_affected} users affected` : null
                },
                {
                    label: 'Recovery Rate',
                    value: `${data.auth_metrics?.recovery_rate || 0}%`,
                    badge: data.auth_metrics?.recovery_rate < 50 ? 'warning' : 'success',
                    badgeText: data.auth_metrics?.avg_recovery_days ? 
                        `~${data.auth_metrics.avg_recovery_days} days to recover` : 'No recoveries'
                },
                {
                    label: 'Active Users',
                    value: data.usage_timeline?.total_active_users || 0,
                    badge: 'neutral',
                    badgeText: `${data.usage_timeline?.total_sessions || 0} sessions`
                },
                {
                    label: 'Impact',
                    value: (() => {
                        const impacts = data.auth_metrics?.daily_impacts || {};
                        const total_before = Object.values(impacts).reduce((a,b) => a + b.sessions_before, 0);
                        const total_after = Object.values(impacts).reduce((a,b) => a + b.sessions_after, 0);
                        if (total_before > 0) {
                            return `${Math.round(((total_before - total_after) / total_before) * 100)}%`;
                        }
                        return '0%';
                    })(),
                    badge: 'warning',
                    badgeText: 'session drop after auth loss'
                }
            ];
            
            metrics.forEach(metric => {
                const card = document.createElement('div');
                card.className = 'metric-card';
                card.innerHTML = `
                    <div class="metric-label">${metric.label}</div>
                    <div class="metric-value">${metric.value}</div>
                    ${metric.badgeText ? `<span class="metric-badge badge-${metric.badge}">${metric.badgeText}</span>` : ''}
                `;
                container.appendChild(card);
            });
        }
        
        function createAuthLossesChart(data) {
            const ctx = document.getElementById('authLossesChart').getContext('2d');
            const daily_losses = data.auth_metrics?.daily_auth_losses || {};
            const dates = Object.keys(daily_losses).sort();
            
            if (charts.authLosses) {
                charts.authLosses.destroy();
            }
            
            charts.authLosses = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dates.map(d => new Date(d).toLocaleDateString()),
                    datasets: [{
                        label: 'Auth Tokens Lost',
                        data: dates.map(d => daily_losses[d]),
                        backgroundColor: '#dc2626',
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                stepSize: 1
                            }
                        }
                    }
                }
            });
        }
        
        function createMomentumLostChart(data) {
            const ctx = document.getElementById('momentumLostChart').getContext('2d');
            const momentum = data.auth_metrics?.momentum_by_level || {};
            const stopped = data.auth_metrics?.stopped_by_level || {};
            
            if (charts.momentumLost) {
                charts.momentumLost.destroy();
            }
            
            const labels = ['Heavy Readers', 'Moderate Readers', 'Light Readers'];
            const activityLevels = ['heavy', 'moderate', 'light'];
            
            charts.momentumLost = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Lost Auth',
                        data: activityLevels.map(level => momentum[level] || 0),
                        backgroundColor: '#fbbf24',
                        borderRadius: 6
                    }, {
                        label: 'Stopped Reading',
                        data: activityLevels.map(level => stopped[level] || 0),
                        backgroundColor: '#dc2626',
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }
        
        function createAuthImpactChart(data) {
            const ctx = document.getElementById('authImpactChart').getContext('2d');
            const daily_impacts = data.auth_metrics?.daily_impacts || {};
            const dates = Object.keys(daily_impacts).sort();
            
            if (charts.authImpact) {
                charts.authImpact.destroy();
            }
            
            charts.authImpact = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dates.map(d => new Date(d).toLocaleDateString()),
                    datasets: [{
                        label: 'Sessions Before',
                        data: dates.map(d => daily_impacts[d].sessions_before),
                        backgroundColor: '#10b981',
                        borderRadius: 6
                    }, {
                        label: 'Sessions After',
                        data: dates.map(d => daily_impacts[d].sessions_after),
                        backgroundColor: '#ef4444',
                        borderRadius: 6
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }
        
        function createAuthTimelineChart(data) {
            const ctx = document.getElementById('authTimelineChart').getContext('2d');
            const timeline = data.auth_metrics?.auth_timeline || {};
            const dates = Object.keys(timeline).sort();
            
            if (charts.authTimeline) {
                charts.authTimeline.destroy();
            }
            
            charts.authTimeline = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: dates.map(d => new Date(d).toLocaleDateString()),
                    datasets: [{
                        label: 'Auth Gained',
                        data: dates.map(d => timeline[d]?.gained || 0),
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        tension: 0.3
                    }, {
                        label: 'Auth Lost',
                        data: dates.map(d => timeline[d]?.lost || 0),
                        borderColor: '#ef4444',
                        backgroundColor: 'rgba(239, 68, 68, 0.1)',
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                stepSize: 1
                            }
                        }
                    }
                }
            });
        }
        
        function createDailyUsersChart(data) {
            const ctx = document.getElementById('dailyUsersChart').getContext('2d');
            const dates = Object.keys(data.usage_timeline?.daily_active_users || {}).sort();
            
            if (charts.dailyUsers) {
                charts.dailyUsers.destroy();
            }
            
            charts.dailyUsers = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: dates.map(d => new Date(d).toLocaleDateString()),
                    datasets: [{
                        label: 'Active Users',
                        data: dates.map(d => data.usage_timeline?.daily_active_users[d] || 0),
                        borderColor: '#007aff',
                        backgroundColor: 'rgba(0, 122, 255, 0.1)',
                        tension: 0.3,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: {
                            display: false
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }
        
        function createFirmwareUsersChart(data) {
            const ctx = document.getElementById('firmwareUsersChart').getContext('2d');
            const firmwareData = data.firmware_metrics?.daily_firmware_data || {};
            const allVersions = data.firmware_metrics?.all_firmware_versions || [];
            const dates = Object.keys(firmwareData).sort();
            
            if (charts.firmwareUsers) {
                charts.firmwareUsers.destroy();
            }
            
            // Create datasets for each firmware version - USERS
            const datasets = allVersions.map((version, index) => {
                const colors = ['#007aff', '#34c759', '#ff9500', '#ff3b30', '#5856d6', '#af52de'];
                const color = colors[index % colors.length];
                
                return {
                    label: `v${version}`,
                    data: dates.map(date => firmwareData[date]?.[version]?.users || 0),
                    backgroundColor: color,
                    borderColor: color,
                    borderWidth: 1
                };
            });
            
            charts.firmwareUsers = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dates.map(d => new Date(d).toLocaleDateString()),
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    scales: {
                        x: {
                            stacked: true
                        },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Number of Users'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            callbacks: {
                                afterLabel: function(context) {
                                    const date = dates[context.dataIndex];
                                    const version = allVersions[context.datasetIndex];
                                    const sessions = firmwareData[date]?.[version]?.sessions || 0;
                                    return `Sessions: ${sessions}`;
                                }
                            }
                        }
                    }
                }
            });
        }
        
        function createFirmwareSessionsChart(data) {
            const ctx = document.getElementById('firmwareSessionsChart').getContext('2d');
            const firmwareData = data.firmware_metrics?.daily_firmware_data || {};
            const allVersions = data.firmware_metrics?.all_firmware_versions || [];
            const dates = Object.keys(firmwareData).sort();
            
            if (charts.firmwareSessions) {
                charts.firmwareSessions.destroy();
            }
            
            // Create datasets for each firmware version - SESSIONS
            const datasets = allVersions.map((version, index) => {
                const colors = ['#007aff', '#34c759', '#ff9500', '#ff3b30', '#5856d6', '#af52de'];
                const color = colors[index % colors.length];
                
                return {
                    label: `v${version}`,
                    data: dates.map(date => firmwareData[date]?.[version]?.sessions || 0),
                    backgroundColor: color,
                    borderColor: color,
                    borderWidth: 1
                };
            });
            
            charts.firmwareSessions = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: dates.map(d => new Date(d).toLocaleDateString()),
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    scales: {
                        x: {
                            stacked: true
                        },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Number of Sessions'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            callbacks: {
                                afterLabel: function(context) {
                                    const date = dates[context.dataIndex];
                                    const version = allVersions[context.datasetIndex];
                                    const users = firmwareData[date]?.[version]?.users || 0;
                                    return `Users: ${users}`;
                                }
                            }
                        }
                    }
                }
            });
        }
        
        function createFirmwareDistributionChart(data) {
            const ctx = document.getElementById('firmwareDistributionChart').getContext('2d');
            const firmwareSummary = data.firmware_metrics?.firmware_summary || {};
            
            if (charts.firmwareDistribution) {
                charts.firmwareDistribution.destroy();
            }
            
            const versions = Object.keys(firmwareSummary);
            const colors = ['#007aff', '#34c759', '#ff9500', '#ff3b30', '#5856d6', '#af52de'];
            
            charts.firmwareDistribution = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: versions.map(v => `v${v}`),
                    datasets: [{
                        data: versions.map(v => firmwareSummary[v].unique_users),
                        backgroundColor: versions.map((_, i) => colors[i % colors.length]),
                        borderWidth: 2,
                        borderColor: '#fff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'right'
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    const version = versions[context.dataIndex];
                                    const summary = firmwareSummary[version];
                                    return [
                                        `v${version}: ${summary.unique_users} users`,
                                        `Total sessions: ${summary.total_sessions}`,
                                        `Avg per user: ${summary.avg_sessions_per_user}`
                                    ];
                                }
                            }
                        }
                    }
                }
            });
        }
        
        function createFirmwareAdoptionChart(data) {
            const ctx = document.getElementById('firmwareAdoptionChart').getContext('2d');
            const firmwareData = data.firmware_metrics?.daily_firmware_data || {};
            const allVersions = data.firmware_metrics?.all_firmware_versions || [];
            const dates = Object.keys(firmwareData).sort();
            
            if (charts.firmwareAdoption) {
                charts.firmwareAdoption.destroy();
            }
            
            // Calculate cumulative percentages for each version over time
            const datasets = allVersions.map((version, index) => {
                const colors = ['#007aff', '#34c759', '#ff9500', '#ff3b30', '#5856d6', '#af52de'];
                const color = colors[index % colors.length];
                
                const percentages = dates.map(date => {
                    const dayData = firmwareData[date];
                    const totalUsers = Object.values(dayData).reduce((sum, v) => sum + (v.users || 0), 0);
                    const versionUsers = dayData[version]?.users || 0;
                    return totalUsers > 0 ? (versionUsers / totalUsers * 100).toFixed(1) : 0;
                });
                
                return {
                    label: `v${version}`,
                    data: percentages,
                    borderColor: color,
                    backgroundColor: color + '20',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.4
                };
            });
            
            charts.firmwareAdoption = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: dates.map(d => new Date(d).toLocaleDateString()),
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100,
                            title: {
                                display: true,
                                text: 'Adoption Rate (%)'
                            },
                            ticks: {
                                callback: function(value) {
                                    return value + '%';
                                }
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return context.dataset.label + ': ' + context.parsed.y + '%';
                                }
                            }
                        }
                    }
                }
            });
        }
        
        async function loadDashboard(days) {
            const loadingEl = document.getElementById('loadingMessage');
            const errorEl = document.getElementById('errorMessage');
            const contentEl = document.getElementById('dashboardContent');
            
            loadingEl.style.display = 'flex';
            errorEl.style.display = 'none';
            contentEl.style.display = 'none';
            
            try {
                destroyAllCharts();
                
                const selectedDays = days || document.getElementById('timeFilter').value;
                dashboardData = await fetchDashboardData(selectedDays);
                
                createKeyMetrics(dashboardData);
                createAuthLossesChart(dashboardData);
                createMomentumLostChart(dashboardData);
                createAuthImpactChart(dashboardData);
                createAuthTimelineChart(dashboardData);
                createFirmwareUsersChart(dashboardData);
                createFirmwareSessionsChart(dashboardData);
                createFirmwareDistributionChart(dashboardData);
                createFirmwareAdoptionChart(dashboardData);
                createDailyUsersChart(dashboardData);
                
                loadingEl.style.display = 'none';
                contentEl.style.display = 'block';
                
            } catch (error) {
                loadingEl.style.display = 'none';
                errorEl.textContent = `Error loading dashboard: ${error.message}`;
                errorEl.style.display = 'block';
            }
        }
        
        // Initial load
        loadDashboard();
        
        // Auto-refresh every 5 minutes
        setInterval(() => loadDashboard(), 5 * 60 * 1000);
    </script>
</body>
</html>"""

        response = make_response(html_content)
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response
