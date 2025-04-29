#!/bin/bash
#
# Script to find the Kindle app position for VNC clipping
# Usage: find-app-position.sh [display]
#

# Use the specified display or default to :1
DISPLAY_ARG="${1:-:1}"
export DISPLAY="$DISPLAY_ARG"

echo "Finding app position on display $DISPLAY"

# Wait for the app to be fully visible
sleep 3

# Try to find the window with "Kindle" in the title or class
APP_WINDOW=$(xwininfo -root -tree | grep -i kindle)

if [ -z "$APP_WINDOW" ]; then
  echo "Kindle app window not found, trying generic Android app..."
  # Try to find any Android app window if Kindle isn't found by name
  APP_WINDOW=$(xwininfo -root -tree | grep -i "Android" | head -1)
fi

if [ -z "$APP_WINDOW" ]; then
  echo "No suitable app window found, using default position"
  # Default to center of screen based on resolution
  SCREEN_WIDTH=$(xdpyinfo | grep dimensions | awk '{print $2}' | cut -d 'x' -f 1)
  SCREEN_HEIGHT=$(xdpyinfo | grep dimensions | awk '{print $2}' | cut -d 'x' -f 2)
  
  # Calculate center position to place the 360x640 app
  X_POS=$(( ($SCREEN_WIDTH - 360) / 2 ))
  Y_POS=$(( ($SCREEN_HEIGHT - 640) / 2 ))
  
  # Create clip region string
  CLIP_REGION="360x640+${X_POS}+${Y_POS}"
else
  # Extract window position and size
  WINDOW_ID=$(echo "$APP_WINDOW" | awk '{print $1}')
  WINDOW_INFO=$(xwininfo -id "$WINDOW_ID")
  
  # Extract dimensions
  X_POS=$(echo "$WINDOW_INFO" | grep "Absolute upper-left X" | awk '{print $4}')
  Y_POS=$(echo "$WINDOW_INFO" | grep "Absolute upper-left Y" | awk '{print $4}')
  WIDTH=$(echo "$WINDOW_INFO" | grep "Width" | awk '{print $2}')
  HEIGHT=$(echo "$WINDOW_INFO" | grep "Height" | awk '{print $2}')
  
  # Ensure we get a reasonable size - if too small or too large, use default 360x640
  if [ "$WIDTH" -lt 300 ] || [ "$WIDTH" -gt 500 ] || [ "$HEIGHT" -lt 600 ] || [ "$HEIGHT" -gt 800 ]; then
    WIDTH=360
    HEIGHT=640
  fi
  
  # Create clip region string
  CLIP_REGION="${WIDTH}x${HEIGHT}+${X_POS}+${Y_POS}"
fi

echo "Using clip region: $CLIP_REGION"

# Return the clip region
echo "$CLIP_REGION"
