#!/bin/bash
#
# Script to restart VNC server for a specific profile to apply app clipping
# This script is called when a user accesses the VNC URL for a profile
#
# Usage: restart-vnc-for-profile.sh <email>
#

EMAIL="$1"

if [ -z "$EMAIL" ]; then
  echo "Error: Profile email is required"
  exit 1
fi

# Get VNC instance map
VNC_MAP="/opt/vnc_instance_map.json"

if [ ! -f "$VNC_MAP" ]; then
  echo "Error: VNC instance map not found at $VNC_MAP"
  exit 1
fi

# Find instance ID for this profile
INSTANCE_ID=$(jq -r '.instances[] | select(.assigned_profile == "'"$EMAIL"'") | .id' "$VNC_MAP")
VNC_PORT=$(jq -r '.instances[] | select(.assigned_profile == "'"$EMAIL"'") | .vnc_port' "$VNC_MAP")
DISPLAY_NUM=$(jq -r '.instances[] | select(.assigned_profile == "'"$EMAIL"'") | .display' "$VNC_MAP")

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "null" ]; then
  echo "Error: No VNC instance found for profile $EMAIL"
  exit 1
fi

echo "Found VNC instance $INSTANCE_ID for profile $EMAIL on display :$DISPLAY_NUM and port $VNC_PORT"

# Kill only the x11vnc process for this display
echo "Killing x11vnc process for port $VNC_PORT..."
pkill -f "x11vnc.*rfbport $VNC_PORT" || true
sleep 1

# Calculate clip position (center app in the display)
X_POS=$((400 - 360/2))
Y_POS=$((300 - 640/2))
CLIP_REGION="360x640+${X_POS}+${Y_POS}"

# Restart just the x11vnc process with the proper clipping
echo "Restarting x11vnc for display :$DISPLAY_NUM with app clipping..."
/usr/bin/x11vnc -display :$DISPLAY_NUM -forever -shared -rfbport $VNC_PORT \
  -rfbauth /home/root/.vnc/passwd -clip "$CLIP_REGION" \
  -cursor arrow -noxdamage -noxfixes -noipv6 \
  -desktop "Kindle App ($INSTANCE_ID)" -o "/var/log/x11vnc-${INSTANCE_ID}.log" -bg

echo "VNC service restarted for instance $INSTANCE_ID"
exit 0
