"""User activity timeline resource for displaying readable activity logs."""

import gzip
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from flask import make_response, request
from flask_restful import Resource

from server.logging_config import logger


class UserActivityResource(Resource):
    """Resource for generating a user-friendly activity timeline from logs."""

    def __init__(self):
        """Initialize the user activity resource."""
        # Get the project root directory (parent of server directory)
        current_file = os.path.abspath(__file__)
        server_dir = os.path.dirname(os.path.dirname(current_file))
        project_root = os.path.dirname(server_dir)
        self.log_dir = os.path.join(project_root, "logs", "email_logs")
        super().__init__()

    def get(self):
        """Generate a human-readable timeline of user activities."""
        try:
            user_email = request.args.get("user_email")
            if not user_email:
                return {"success": False, "error": "user_email parameter is required"}, 400

            # Check if JSON response is requested
            return_json = request.args.get("json", "0") == "1"

            # Parse logs for this user
            activities = self._parse_user_activities(user_email)

            if not activities:
                if return_json:
                    return {
                        "success": True,
                        "user_email": user_email,
                        "message": f"No activity found for {user_email}",
                        "activities": [],
                    }
                else:
                    response = make_response(f"No activity found for {user_email}")
                    response.headers["Content-Type"] = "text/plain; charset=utf-8"
                    return response

            # Format the timeline
            timeline = self._format_timeline(activities, user_email)

            if return_json:
                return {
                    "success": True,
                    "user_email": user_email,
                    "timeline": timeline,
                    "activities": activities,
                }
            else:
                # Return plain text for easy copy/paste
                response = make_response(timeline)
                response.headers["Content-Type"] = "text/plain; charset=utf-8"
                return response

        except Exception as e:
            logger.error(f"Error generating user activity timeline: {str(e)}")
            if request.args.get("json", "0") == "1":
                return {"success": False, "error": str(e)}, 500
            else:
                response = make_response(f"Error generating timeline: {str(e)}")
                response.headers["Content-Type"] = "text/plain; charset=utf-8"
                return response

    def _strip_ansi_codes(self, text):
        """Remove ANSI color codes from text."""
        # Remove literal color codes like [35m, [0m, [33;2m etc.
        text = re.sub(r"\[\d+(?:;\d+)*m", "", text)
        # Also remove escape sequences if any
        ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
        return ansi_escape.sub("", text)

    def _parse_user_activities(self, user_email):
        """Parse log files to extract user activities."""
        activities = []

        # Check user-specific log file and its rotated versions
        user_log_name = f"{user_email}.log"
        self._process_log_with_rotations(activities, user_log_name, user_email)

        # Sort by timestamp
        activities.sort(key=lambda x: x["timestamp_obj"])

        # Remove timestamp_obj before returning (not needed in response)
        for activity in activities:
            activity.pop("timestamp_obj", None)

        return activities

    def _process_log_with_rotations(self, activities, log_name, user_email):
        """Process a log file and all its rotated versions."""
        log_base_path = os.path.join(self.log_dir, log_name)

        # Process current log file
        if os.path.exists(log_base_path):
            activities.extend(self._parse_log_file(log_base_path, user_email))
        else:
            logger.warning(f"Log file {log_base_path} does not exist for user {user_email}")

        # Process rotated log files (uncompressed)
        rotation_num = 1
        while True:
            rotated_log = f"{log_base_path}.{rotation_num}"
            if os.path.exists(rotated_log):
                activities.extend(self._parse_log_file(rotated_log, user_email))
                rotation_num += 1
            else:
                # Check for compressed version
                compressed_log = f"{rotated_log}.gz"
                if os.path.exists(compressed_log):
                    activities.extend(self._parse_compressed_log_file(compressed_log, user_email))
                    rotation_num += 1
                else:
                    # No more rotated files
                    break

    def _parse_log_file(self, log_file, user_email):
        """Parse a single log file for user activities."""
        try:
            logger.info(f"Parsing log file: {log_file} for user: {user_email}")
            with open(log_file, "r") as f:
                return self._parse_log_lines(f, user_email)
        except Exception as e:
            logger.error(f"Error parsing log file {log_file}: {str(e)}")
            return []

    def _parse_log_lines(self, file_obj, user_email):
        """Parse log lines from a file object for user activities."""
        activities = []

        # Patterns to extract key events
        patterns = {
            "open_book": r'REQUEST \[GET /open-book\].*?"title":\s*"([^"]+)"',
            "books_stream": r"REQUEST \[GET /books-stream\]",
            "books_stream_response": r"RESPONSE \[GET /books-stream\]",
            "book_opened": r"Opening book:\s*(.+?)$",
            "book_already_open": r"Already reading book.*?:\s*(.+?),",
            "navigate": r"REQUEST \[GET /navigate\].*?(\{[^}]+\})",
            "preview_forward": r"Previewing (\d+) pages? forward",
            "preview_complete": r"Successfully previewed (\d+) pages? forward",
            "emulator_start": r"Starting emulator for (.+?) - will use",
            "emulator_ready": r"Emulator (emulator-\d+) is fully booted",
            "book_download": r"Book is not downloaded yet, initiating download",
            "search_book": r"Proceeding to search for \'(.+?)\'",
            "book_found": r"Successfully found book \'(.+?)\' using search",
            "response_time": r"RESPONSE \[GET /([^\]]+?)(?:\s+[\d.]+s)?\].*?User:\s*([^|]+)",
            "launch_time_start": r"Launching emulator for (.+?)$",
            "launch_time_end": r"Emulator (emulator-\d+) launched successfully",
            "appium_start": r"Starting Appium server for",
            "appium_fail": r"Failed to start Appium server",
            "request": r"REQUEST \[(\w+) ([^\]]+)\].*?: (.+)$",
            "response": r"RESPONSE \[(\w+) ([^\]]+?)(?:\s+([\d.]+)s)?\].*?: (.+)$",
        }

        current_activity = None
        launch_start_time = None

        for line in file_obj:
            # Skip lines not for this user
            if user_email not in line:
                continue

            # Extract timestamp - try multiple formats
            timestamp = None

            # Try full date format: [5-29-25 22:41:49 PDT]
            timestamp_match = re.search(r"\[(\d+-\d+-\d+ \d+:\d+:\d+)", line)
            if timestamp_match:
                timestamp_str = timestamp_match.group(1)
                timestamp = datetime.strptime(timestamp_str, "%m-%d-%y %H:%M:%S")
            else:
                # Try time-only format: [11:38:58]
                timestamp_match = re.search(r"\[(\d+:\d+:\d+)\]", line)
                if timestamp_match:
                    time_str = timestamp_match.group(1)
                    # Use today's date with the time
                    today = datetime.now().date()
                    timestamp = datetime.combine(today, datetime.strptime(time_str, "%H:%M:%S").time())

            if not timestamp:
                continue

            # Track emulator launch time
            if "launch_time_start" in patterns and re.search(patterns["launch_time_start"], line):
                launch_start_time = timestamp

            # Check each pattern
            for event_type, pattern in patterns.items():
                match = re.search(pattern, line)
                if match:
                    activity = {
                        "timestamp": timestamp.isoformat(),  # Convert to string for JSON serialization
                        "timestamp_obj": timestamp,  # Keep datetime object for sorting
                        "type": event_type,
                        "raw_line": self._strip_ansi_codes(line.strip()),
                    }

                    if event_type == "open_book":
                        activity["title"] = match.group(1)
                        activity["action"] = "requested_book"
                    elif event_type == "book_opened":
                        activity["title"] = match.group(1)
                        activity["action"] = "opening_book"
                    elif event_type == "book_already_open":
                        activity["title"] = match.group(1)
                        activity["action"] = "book_already_open"
                    elif event_type == "navigate":
                        import json

                        try:
                            params_dict = json.loads(match.group(1))
                            preview = params_dict.get("preview", "0")
                            navigate = params_dict.get("navigate", "0")
                            # Handle both string and int values
                            preview = int(preview) if preview else 0
                            navigate = int(navigate) if navigate else 0

                            activity["navigate_count"] = navigate
                            activity["preview_count"] = preview
                            activity["action"] = "navigation_request"
                        except:
                            activity["action"] = "navigation_request"
                    elif event_type == "preview_forward":
                        activity["pages"] = int(match.group(1))
                        activity["action"] = "previewing_pages"
                    elif event_type == "preview_complete":
                        activity["pages"] = int(match.group(1))
                        activity["action"] = "preview_complete"
                    elif event_type == "emulator_start":
                        activity["action"] = "starting_emulator"
                    elif event_type == "emulator_ready":
                        activity["emulator_id"] = match.group(1)
                        activity["action"] = "emulator_ready"
                        if launch_start_time:
                            activity["boot_time"] = (timestamp - launch_start_time).total_seconds()
                            launch_start_time = None
                    elif event_type == "book_download":
                        activity["action"] = "downloading_book"
                    elif event_type == "search_book":
                        activity["title"] = match.group(1)
                        activity["action"] = "searching_book"
                    elif event_type == "book_found":
                        activity["title"] = match.group(1)
                        activity["action"] = "book_found"
                    elif event_type == "books_stream":
                        activity["action"] = "requesting_books"
                    elif event_type == "books_stream_response":
                        activity["action"] = "books_received"
                        if current_activity and current_activity.get("type") == "books_stream":
                            duration = (timestamp - current_activity["timestamp_obj"]).total_seconds()
                            activity["duration"] = duration
                    elif event_type == "appium_start":
                        activity["action"] = "appium_starting"
                    elif event_type == "appium_fail":
                        activity["action"] = "appium_failed"
                    elif event_type == "request":
                        activity["method"] = match.group(1)
                        activity["endpoint"] = match.group(2)
                        activity["params"] = self._strip_ansi_codes(match.group(3))
                        activity["action"] = "api_request"
                    elif event_type == "response":
                        activity["method"] = match.group(1)
                        activity["endpoint"] = match.group(2)
                        # Check if elapsed time was captured (group 3)
                        if match.group(3) is not None:  # This is the elapsed time
                            activity["duration"] = float(match.group(3))
                            activity["body"] = self._strip_ansi_codes(match.group(4))
                        else:
                            # No elapsed time in the log, use the last group as body
                            # When no elapsed time, group 4 is the body
                            activity["body"] = self._strip_ansi_codes(match.group(4))
                            # Fall back to calculating duration
                            if (
                                current_activity
                                and current_activity.get("action") == "api_request"
                                and current_activity.get("endpoint") == activity["endpoint"]
                            ):
                                duration = (timestamp - current_activity["timestamp_obj"]).total_seconds()
                                activity["duration"] = duration
                        activity["action"] = "api_response"
                        # Always get request params if available
                        if current_activity and current_activity.get("endpoint") == activity["endpoint"]:
                            activity["request_params"] = current_activity.get("params", "")
                    elif event_type == "response_time" and "RESPONSE" in line:
                        # Calculate request duration
                        if current_activity and current_activity.get("type") in [
                            "open_book",
                            "books_stream",
                        ]:
                            duration = (timestamp - current_activity["timestamp_obj"]).total_seconds()
                            current_activity["duration"] = duration
                            activity["action"] = "request_complete"
                            activity["endpoint"] = match.group(1)
                            activity["duration"] = duration

                    activities.append(activity)

                    # Track current activity for duration calculation
                    if event_type in ["open_book", "navigate", "books_stream", "request"]:
                        current_activity = activity

        return activities

    def _parse_compressed_log_file(self, log_file, user_email):
        """Parse a gzip compressed log file for user activities."""
        try:
            with gzip.open(log_file, "rt", encoding="utf-8", errors="ignore") as f:
                # Use the same parsing logic by passing the file object
                return self._parse_log_lines(f, user_email)
        except Exception as e:
            logger.error(f"Error parsing compressed log file {log_file}: {str(e)}")
            return []

    def _format_timeline(self, activities, user_email):
        """Format activities into a compressed timeline focusing on API requests."""
        if not activities:
            return f"No activities found for {user_email}"

        timeline_parts = []

        # Get date range if we have activities
        if activities:
            first_date = datetime.fromisoformat(activities[0]["timestamp"]).strftime("%b %-d, %Y")
            last_date = datetime.fromisoformat(activities[-1]["timestamp"]).strftime("%b %-d, %Y")
            if first_date == last_date:
                timeline_parts.append(f"API Activity Timeline for {user_email} on {first_date}:\n")
            else:
                timeline_parts.append(
                    f"API Activity Timeline for {user_email} from {first_date} to {last_date}:\n"
                )
        else:
            timeline_parts.append(f"API Activity Timeline for {user_email}:\n")

        # Group activities by request/response pairs
        request_map = {}
        formatted_lines = []

        for activity in activities:
            # Parse timestamp back from ISO format
            timestamp = datetime.fromisoformat(activity["timestamp"])
            # Include date for the first entry and when date changes
            if not formatted_lines or timestamp.date() != formatted_lines[-1][0].date():
                time_str = timestamp.strftime("%b %-d, %-I:%M:%S %p")
            else:
                time_str = timestamp.strftime("%-I:%M:%S %p")

            action = activity.get("action")

            if action == "api_request":
                # Store request for matching with response
                endpoint = activity.get("endpoint", "")
                request_map[endpoint] = activity
            elif action == "api_response":
                endpoint = activity.get("endpoint", "")
                duration = activity.get("duration", 0)
                params = activity.get("request_params", "")
                body = activity.get("body", "")

                # Create compressed description based on endpoint
                if "/open-book" in endpoint:
                    import json

                    try:
                        params_dict = json.loads(params)
                        title = params_dict.get("title", "Unknown")
                        desc = f'opened book "{title}"'
                    except:
                        desc = "opened book"
                elif "/navigate" in endpoint:
                    import json

                    try:
                        params_dict = json.loads(params)
                        preview = params_dict.get("preview", "0")
                        navigate = params_dict.get("navigate", "0")
                        # Handle both string and int values
                        preview = int(preview) if preview else 0
                        navigate = int(navigate) if navigate else 0

                        # Default navigate to 1 if preview is set but navigate isn't
                        if preview > 0 and navigate == 0:
                            navigate = 1

                        # Build description with parameters
                        desc_parts = []
                        if navigate > 0:
                            desc_parts.append(f"navigate={navigate}")
                        if preview > 0:
                            desc_parts.append(f"preview={preview}")

                        if desc_parts:
                            desc = "navigation request (" + ", ".join(desc_parts) + ")"
                        else:
                            desc = "navigation request"
                    except:
                        desc = "navigation request"
                elif "/books-stream" in endpoint:
                    desc = "requested book library"
                elif "/auth" in endpoint:
                    desc = "authenticated"
                elif "/screenshot" in endpoint:
                    desc = "captured screenshot"
                elif "/state" in endpoint:
                    desc = "checked app state"
                else:
                    desc = f"{activity.get('method', 'GET')} {self._strip_ansi_codes(endpoint)}"

                # Check if request succeeded or failed
                if "error" in body.lower() or "failed" in body.lower():
                    status = "FAILED"
                else:
                    status = "OK"

                # Format the line
                line = f"{time_str} - {desc} ({duration:.1f}s) [{status}]"

                # Add truncated response if it's an error
                if status == "FAILED":
                    # Truncate long error messages
                    if len(body) > 100:
                        body = body[:100] + "..."
                    line += f" - {body}"

                formatted_lines.append((timestamp, line))
            elif action in ["appium_starting", "appium_failed"]:
                # Include appium status in timeline
                if action == "appium_starting":
                    line = f"{time_str} - starting automation service..."
                else:
                    line = f"{time_str} - automation service failed to start"
                formatted_lines.append((timestamp, line))

        # Sort by timestamp and format with time gaps
        formatted_lines.sort(key=lambda x: x[0])

        last_timestamp = None
        for timestamp, line in formatted_lines:
            # Add time gap if significant
            if last_timestamp:
                time_diff = timestamp - last_timestamp
                if time_diff > timedelta(minutes=30):
                    if time_diff < timedelta(hours=1):
                        gap = f"{int(time_diff.total_seconds() / 60)}m"
                    else:
                        gap = f"{int(time_diff.total_seconds() / 3600)}h"
                    timeline_parts.append(f"\n[{gap} later]\n")

            timeline_parts.append(line)
            last_timestamp = timestamp

        return "\n".join(timeline_parts)
