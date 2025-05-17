#!/bin/bash
# Idle check cron script for Kindle Automator
# Add this to crontab with: */15 * * * * /path/to/idle_check_cron.sh

# Configuration
SERVER_URL="http://kindle.sindarin.com:4098"
IDLE_TIMEOUT_MINUTES=30
LOG_FILE="/opt/kindle-automator/logs/idle-check.log"

# Get current timestamp
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

echo "[$TIMESTAMP] Running idle check..." >> "$LOG_FILE"

# Call the idle check endpoint
RESPONSE=$(curl -s -X POST "$SERVER_URL/idle-check" \
  -H "Content-Type: application/json" \
  -d "{\"idle_timeout_minutes\": $IDLE_TIMEOUT_MINUTES}")

# Log the response
echo "[$TIMESTAMP] Response: $RESPONSE" >> "$LOG_FILE"

# You can also use GET with default 30 minute timeout:
# curl -s "$SERVER_URL/idle-check" >> "$LOG_FILE"

# Rotate log file if it gets too large (over 1MB)
if [ -f "$LOG_FILE" ]; then
    FILE_SIZE=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null)
    if [ "$FILE_SIZE" -gt 1048576 ]; then
        mv "$LOG_FILE" "$LOG_FILE.old"
        echo "[$TIMESTAMP] Log rotated" > "$LOG_FILE"
    fi
fi