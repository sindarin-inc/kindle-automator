"""Log timeline resource for aggregating and displaying log entries.

This resource provides an endpoint to retrieve and aggregate log entries from multiple log files,
including the main server.log and email-specific log files. It supports filtering by email, log level,
and time range.

Endpoint: GET /logs/timeline

Query Parameters:
- email: Filter logs for a specific email (optional)
- limit: Maximum number of log entries to return (default: 1000)
- level: Minimum log level to include (DEBUG, INFO, WARNING, ERROR)
- start_time: ISO format timestamp to filter logs after this time
- end_time: ISO format timestamp to filter logs before this time

Example usage:
    # Get last 50 INFO+ logs for a specific email
    GET /logs/timeline?email=kindle@solreader.com&limit=50&level=INFO
    
    # Get all ERROR logs from the last hour
    GET /logs/timeline?level=ERROR&start_time=2024-12-30T14:00:00
"""

import gzip
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from flask import request
from flask_restful import Resource

logger = logging.getLogger(__name__)


class LogTimelineResource(Resource):
    """Resource for retrieving aggregated log entries from multiple log files."""

    def __init__(self, server_instance=None):
        """Initialize the log timeline resource.

        Args:
            server_instance: The AutomationServer instance (ignored, not used)
        """
        # Accept server_instance for backwards compatibility but don't use it
        self.logs_dir = Path("logs")
        # Regex pattern to parse log entries
        # Format: [LEVEL] [date time TZ] filepath:line [email] message
        # The email part is optional for backward compatibility
        self.log_pattern = re.compile(
            r"\[(\w+)\s*\]\s*\[(\d+-\d+-\d+\s+\d+:\d+:\d+\s+\w+)\]\s*([^:]+):(\d+)\s*(?:\[([^]]+)\]\s*)?(.+)"
        )
        # Pattern to strip ANSI escape codes
        self.ansi_pattern = re.compile(r'\033\[[0-9;]+m')
        super().__init__()

    def get(self):
        """Get aggregated log entries from all log files.

        Query parameters:
            - email: Filter logs for a specific email (optional)
            - limit: Maximum number of log entries to return (default: 1000)
            - level: Minimum log level to include (DEBUG, INFO, WARNING, ERROR)
            - start_time: ISO format timestamp to filter logs after this time
            - end_time: ISO format timestamp to filter logs before this time
        """
        # Get query parameters
        email_filter = request.args.get("email")
        limit = int(request.args.get("limit", 1000))
        level_filter = request.args.get("level", "DEBUG").upper()
        start_time = request.args.get("start_time")
        end_time = request.args.get("end_time")

        # Parse time filters if provided
        start_dt = datetime.fromisoformat(start_time) if start_time else None
        end_dt = datetime.fromisoformat(end_time) if end_time else None

        # Define log level hierarchy
        log_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        min_level = log_levels.get(level_filter, 10)

        # Collect all log entries
        all_entries = []

        try:
            # Get list of log files to process
            log_files = []

            # Always include the main server.log and its rotations
            server_log = self.logs_dir / "server.log"
            if server_log.exists():
                log_files.append(server_log)

            # Add rotated server logs
            for rotated_log in sorted(self.logs_dir.glob("server.log.*")):
                log_files.append(rotated_log)

            # If email filter is specified, only include that email's log
            if email_filter:
                # Check in email_logs subdirectory
                email_log = self.logs_dir / "email_logs" / f"{email_filter}.log"
                if email_log.exists():
                    log_files.append(email_log)

                # Also check in main logs directory for backward compatibility
                email_log_main = self.logs_dir / f"{email_filter}.log"
                if email_log_main.exists():
                    log_files.append(email_log_main)

                # Add rotated email logs from email_logs
                for rotated_log in sorted((self.logs_dir / "email_logs").glob(f"{email_filter}.log.*")):
                    log_files.append(rotated_log)
                # Add rotated email logs from main dir
                for rotated_log in sorted(self.logs_dir.glob(f"{email_filter}.log.*")):
                    log_files.append(rotated_log)
            else:
                # Include all email-specific logs from email_logs subdirectory
                email_logs_dir = self.logs_dir / "email_logs"
                if email_logs_dir.exists():
                    for log_file in email_logs_dir.glob("*.log"):
                        if "@" in log_file.name:
                            log_files.append(log_file)

                    # Add rotated email logs from email_logs
                    for log_file in email_logs_dir.glob("*.log.*"):
                        if "@" in log_file.name.split(".log")[0]:
                            log_files.append(log_file)

                # Also check main logs directory for backward compatibility
                for log_file in self.logs_dir.glob("*.log"):
                    if log_file.name != "server.log" and "@" in log_file.name:
                        log_files.append(log_file)

                # Add rotated email logs from main dir
                for log_file in self.logs_dir.glob("*.log.*"):
                    if "@" in log_file.name.split(".log")[0]:
                        log_files.append(log_file)

            # Process each log file
            for log_file in log_files:
                if str(log_file).endswith(".gz"):
                    entries = self._parse_compressed_log_file(
                        log_file, min_level, start_dt, end_dt, limit - len(all_entries)
                    )
                else:
                    entries = self._parse_log_file(
                        log_file, min_level, start_dt, end_dt, limit - len(all_entries)
                    )
                all_entries.extend(entries)

                # Stop if we've reached the limit
                if len(all_entries) >= limit:
                    break

            # Sort all entries by timestamp (newest first)
            all_entries.sort(key=lambda x: x["timestamp"], reverse=True)

            # Apply final limit
            all_entries = all_entries[:limit]

            return {
                "success": True,
                "total_entries": len(all_entries),
                "filters": {
                    "email": email_filter,
                    "level": level_filter,
                    "start_time": start_time,
                    "end_time": end_time,
                    "limit": limit,
                },
                "entries": all_entries,
            }, 200

        except Exception as e:
            logger.error(f"Error retrieving log timeline: {e}", exc_info=True)
            return {"error": f"Failed to retrieve logs: {str(e)}"}, 500

    def _parse_log_file(self, log_file, min_level, start_dt, end_dt, max_entries):
        """Parse a single log file and extract entries matching criteria.

        Args:
            log_file: Path to the log file
            min_level: Minimum log level value to include
            start_dt: Start datetime filter (optional)
            end_dt: End datetime filter (optional)
            max_entries: Maximum number of entries to return from this file

        Returns:
            List of parsed log entries
        """
        # Determine the source from the filename
        if log_file.name == "server.log" or "server.log" in str(log_file):
            source = "server"
        else:
            # Remove .log extension and handle email_logs subdirectory
            source = log_file.stem

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                return self._parse_log_lines(f, source, min_level, start_dt, end_dt, max_entries)
        except Exception as e:
            logger.error(f"Error parsing log file {log_file}: {e}", exc_info=True)
            return []

    def _parse_log_lines(self, file_obj, source, min_level, start_dt, end_dt, max_entries):
        """Parse log lines from a file object.

        Args:
            file_obj: File object to read lines from
            source: Source identifier for the log
            min_level: Minimum log level value to include
            start_dt: Start datetime filter (optional)
            end_dt: End datetime filter (optional)
            max_entries: Maximum number of entries to return

        Returns:
            List of parsed log entries
        """
        entries = []
        log_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
        current_entry = None

        for line in file_obj:
            # Strip ANSI escape codes from the line
            clean_line = self.ansi_pattern.sub('', line)
            
            # Try to match the log pattern
            match = self.log_pattern.match(clean_line)

            if match:
                # If we had a previous entry, add it
                if current_entry and len(entries) < max_entries:
                    entries.append(current_entry)

                # Parse the new entry
                level, timestamp_str, filepath, line_no, email, message = match.groups()

                # Check log level
                if log_levels.get(level, 0) < min_level:
                    current_entry = None
                    continue

                # Parse timestamp
                try:
                    # Handle the specific format: "12-30-24 15:30:45 PST"
                    timestamp = datetime.strptime(
                        timestamp_str.replace(" PST", "").replace(" PDT", ""), "%m-%d-%y %H:%M:%S"
                    )
                    # Add current year century (20xx)
                    timestamp = timestamp.replace(year=timestamp.year + 2000)
                except ValueError:
                    current_entry = None
                    continue

                # Apply time filters
                if start_dt and timestamp < start_dt:
                    current_entry = None
                    continue
                if end_dt and timestamp > end_dt:
                    current_entry = None
                    continue

                # Create new entry
                current_entry = {
                    "timestamp": timestamp.isoformat(),
                    "level": level,
                    "source": source,
                    "file": filepath,
                    "line": int(line_no),
                    "message": message.strip(),
                }

                # Add email if present (new format)
                if email:
                    current_entry["user"] = email

            elif current_entry and clean_line.strip():
                # This is a continuation of the previous log entry (multi-line)
                current_entry["message"] += "\n" + clean_line.strip()

        # Don't forget the last entry
        if current_entry and len(entries) < max_entries:
            entries.append(current_entry)

        return entries

    def _parse_compressed_log_file(self, log_file, min_level, start_dt, end_dt, max_entries):
        """Parse a gzip compressed log file and extract entries matching criteria.

        Args:
            log_file: Path to the compressed log file
            min_level: Minimum log level value to include
            start_dt: Start datetime filter (optional)
            end_dt: End datetime filter (optional)
            max_entries: Maximum number of entries to return from this file

        Returns:
            List of parsed log entries
        """
        try:
            with gzip.open(log_file, "rt", encoding="utf-8", errors="ignore") as f:
                # Determine the source from the filename
                source = "server" if "server.log" in str(log_file) else log_file.stem.split(".")[0]
                return self._parse_log_lines(f, source, min_level, start_dt, end_dt, max_entries)
        except Exception as e:
            logger.error(f"Error parsing compressed log file {log_file}: {e}", exc_info=True)
            return []
