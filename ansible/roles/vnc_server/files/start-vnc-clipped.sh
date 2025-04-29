#!/bin/bash
#
# Script to start x11vnc with app-only clipping region
#

# Constants
DISPLAY=:1
VNC_PORT=5900
VNC_PASSWORD_FILE="$HOME/.vnc/passwd"
LOG_FILE="/var/log/x11vnc.log"

# Use the app finder script to get the clip region
APP_FINDER="/usr/local/bin/find-app-position.sh"

# Check if we should try to find the app position
if [ "$1" == "auto" ]; then
  echo "Attempting to automatically find app position..."
  if [ -x "$APP_FINDER" ]; then
    CLIP_REGION=$($APP_FINDER)
    echo "Using clip region: $CLIP_REGION"
  else
    echo "App finder script not found or not executable, using default clip"
    CLIP_REGION="360x640+0+0"
  fi
else
  # Use fixed position from center of screen
  # Get screen dimensions
  export DISPLAY=:1
  SCREEN_INFO=$(xdpyinfo | grep dimensions)
  SCREEN_WIDTH=$(echo $SCREEN_INFO | awk '{print $2}' | cut -d 'x' -f 1)
  SCREEN_HEIGHT=$(echo $SCREEN_INFO | awk '{print $2}' | cut -d 'x' -f 2)
  
  # Calculate center position
  X_POS=$(( ($SCREEN_WIDTH - 360) / 2 ))
  Y_POS=$(( ($SCREEN_HEIGHT - 640) / 2 ))
  
  CLIP_REGION="360x640+${X_POS}+${Y_POS}"
  echo "Using centered clip region: $CLIP_REGION"
fi

# Start x11vnc with the clip region
exec /usr/bin/x11vnc -display $DISPLAY \
  -forever \
  -shared \
  -rfbport $VNC_PORT \
  -rfbauth $VNC_PASSWORD_FILE \
  -clip $CLIP_REGION \
  -cursor arrow \
  -noxdamage \
  -noxfixes \
  -desktop "Kindle App" \
  -o $LOG_FILE
