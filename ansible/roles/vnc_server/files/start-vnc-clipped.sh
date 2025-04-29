#!/bin/bash
#
# Script to start x11vnc with app-only clipping region
# Usage: start-vnc-clipped.sh [auto|center] [display] [port] [password] [instance_id]
#

# Get mode
MODE="${1:-auto}"

# Get display number
DISPLAY_ARG="${2:-:1}"
DISPLAY="$DISPLAY_ARG"

# Get VNC port
VNC_PORT="${3:-5900}"

# Get password
VNC_PASSWORD="${4:-changeme}"

# Get instance ID for log file
INSTANCE_ID="${5:-1}"
LOG_FILE="/var/log/x11vnc-${INSTANCE_ID}.log"

# Use the app finder script to get the clip region
APP_FINDER="/usr/local/bin/find-app-position.sh"

# Check if we should try to find the app position
if [ "$MODE" == "auto" ]; then
  echo "Attempting to automatically find app position on $DISPLAY..."
  if [ -x "$APP_FINDER" ]; then
    export DISPLAY="$DISPLAY_ARG"
    CLIP_REGION=$($APP_FINDER "$DISPLAY_ARG")
    echo "Using clip region: $CLIP_REGION"
  else
    echo "App finder script not found or not executable, using default clip"
    CLIP_REGION="360x640+0+0"
  fi
else
  # Use fixed position from center of screen
  # Get screen dimensions
  export DISPLAY="$DISPLAY_ARG"
  SCREEN_INFO=$(xdpyinfo | grep dimensions)
  SCREEN_WIDTH=$(echo $SCREEN_INFO | awk '{print $2}' | cut -d 'x' -f 1)
  SCREEN_HEIGHT=$(echo $SCREEN_INFO | awk '{print $2}' | cut -d 'x' -f 2)
  
  # Calculate center position
  X_POS=$(( ($SCREEN_WIDTH - 360) / 2 ))
  Y_POS=$(( ($SCREEN_HEIGHT - 640) / 2 ))
  
  CLIP_REGION="360x640+${X_POS}+${Y_POS}"
  echo "Using centered clip region: $CLIP_REGION"
fi

# Create temporary password file if password provided directly
if [ -n "$VNC_PASSWORD" ] && [ "$VNC_PASSWORD" != "changeme" ]; then
  TEMP_PASSWORD_FILE=$(mktemp)
  echo "$VNC_PASSWORD" > $TEMP_PASSWORD_FILE
  PASSWORD_OPTION="-passwd $TEMP_PASSWORD_FILE"
else
  # Use default password file
  PASSWORD_OPTION="-passwd $HOME/.vnc/passwd"
fi

# Check if x11vnc is already running on this port
if pgrep -f "x11vnc.*rfbport $VNC_PORT" > /dev/null; then
  echo "x11vnc is already running on port $VNC_PORT, killing it..."
  pkill -f "x11vnc.*rfbport $VNC_PORT"
  sleep 1
fi

# Start x11vnc with the clip region
echo "Starting x11vnc for display $DISPLAY_ARG on port $VNC_PORT with clip region $CLIP_REGION"
exec /usr/bin/x11vnc -display "$DISPLAY_ARG" \
  -forever \
  -shared \
  -rfbport "$VNC_PORT" \
  $PASSWORD_OPTION \
  -clip "$CLIP_REGION" \
  -cursor arrow \
  -noxdamage \
  -noxfixes \
  -noipv6 \
  -desktop "Kindle App ($INSTANCE_ID)" \
  -o "$LOG_FILE"
