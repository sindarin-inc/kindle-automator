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

# Check which VNC instance map to use (legacy or new format)
LEGACY_VNC_MAP="/opt/vnc_instance_map.json"
NEW_VNC_MAP="/opt/kindle-automator/vnc-instance-mapping.json"

# First try the new format
if [ -f "$NEW_VNC_MAP" ]; then
  echo "Using new VNC instance mapping at $NEW_VNC_MAP"
  VNC_MAP="$NEW_VNC_MAP"
  
  # Get instance info from new format
  INSTANCE_ID=$(jq -r --arg email "$EMAIL" '.[$email].instance // empty' "$VNC_MAP")
  DISPLAY_NUM=$(jq -r --arg email "$EMAIL" '.[$email].display // empty' "$VNC_MAP")
  VNC_PORT=$(jq -r --arg email "$EMAIL" '.[$email].port // empty' "$VNC_MAP")
  
  # If no entry found, try to create one
  if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "null" ]; then
    echo "No VNC instance found for profile $EMAIL in new format, creating one..."
    
    # Find an available instance (1-10)
    USED_INSTANCES=$(jq -r '.[] | .instance' "$VNC_MAP" 2>/dev/null | sort)
    
    for i in {1..10}; do
      if ! echo "$USED_INSTANCES" | grep -q "^$i$"; then
        # This instance is available
        INSTANCE_ID="$i"
        DISPLAY_NUM="$i"
        VNC_PORT=$((5900 + i))
        
        # Create a temporary file for the update
        TEMP_FILE=$(mktemp)
        
        # Add mapping for this email to the available instance
        jq --arg email "$EMAIL" --arg instance "$INSTANCE_ID" \
          '.[$email] = {"instance": $instance|tonumber, "display": $instance|tonumber, "port": (5900+$instance|tonumber)}' \
          "$VNC_MAP" > "$TEMP_FILE"
        
        # Replace the original file with the updated one
        mv "$TEMP_FILE" "$VNC_MAP"
        chmod 666 "$VNC_MAP"
        
        echo "Created new VNC instance $INSTANCE_ID for profile $EMAIL"
        break
      fi
    done
  fi
# Fall back to legacy format if new format not found or no entry created
elif [ -f "$LEGACY_VNC_MAP" ]; then
  echo "Using legacy VNC instance mapping at $LEGACY_VNC_MAP"
  VNC_MAP="$LEGACY_VNC_MAP"
  
  # Find instance ID for this profile in legacy format
  INSTANCE_ID=$(jq -r '.instances[] | select(.assigned_profile == "'"$EMAIL"'") | .id' "$VNC_MAP")
  VNC_PORT=$(jq -r '.instances[] | select(.assigned_profile == "'"$EMAIL"'") | .vnc_port' "$VNC_MAP")
  DISPLAY_NUM=$(jq -r '.instances[] | select(.assigned_profile == "'"$EMAIL"'") | .display' "$VNC_MAP")
else
  echo "Error: No VNC instance map found"
  exit 1
fi

# Verify we have the required information
if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "null" ]; then
  echo "Error: No VNC instance found for profile $EMAIL"
  exit 1
fi

echo "Found VNC instance $INSTANCE_ID for profile $EMAIL on display :$DISPLAY_NUM and port $VNC_PORT"

# Kill only the x11vnc process for this display
echo "Killing x11vnc process for port $VNC_PORT..."
pkill -f "x11vnc.*rfbport $VNC_PORT" || true
sleep 1

# Use the app finder to get the clip region if available
APP_FINDER="/usr/local/bin/find-app-position.sh"
if [ -x "$APP_FINDER" ]; then
  echo "Using app finder to determine clip region..."
  export DISPLAY=:$DISPLAY_NUM
  CLIP_REGION=$($APP_FINDER ":$DISPLAY_NUM")
  
  # Verify we got a valid clip region
  if [ -z "$CLIP_REGION" ] || [[ ! "$CLIP_REGION" =~ [0-9]+x[0-9]+\+[0-9]+\+[0-9]+ ]]; then
    echo "Invalid clip region from app finder: $CLIP_REGION, using default"
    # Calculate clip position (center app in the display)
    X_POS=$((400 - 360/2))
    Y_POS=$((300 - 640/2))
    CLIP_REGION="360x640+${X_POS}+${Y_POS}"
  fi
else
  echo "App finder not available, using default clip position"
  # Calculate clip position (center app in the display)
  X_POS=$((400 - 360/2))
  Y_POS=$((300 - 640/2))
  CLIP_REGION="360x640+${X_POS}+${Y_POS}"
fi

echo "Using clip region: $CLIP_REGION"

# Make sure Xvfb is running for this display
if ! ps aux | grep -v grep | grep -q "Xvfb :${DISPLAY_NUM}"; then
  echo "Xvfb not running for display :$DISPLAY_NUM, starting it..."
  systemctl start xvfb@${DISPLAY_NUM}.service
  sleep 2
fi

# Restart just the x11vnc process with the proper clipping
echo "Restarting x11vnc for display :$DISPLAY_NUM with app clipping..."
/usr/bin/x11vnc -display :$DISPLAY_NUM -forever -shared -rfbport $VNC_PORT \
  -rfbauth /home/{{ ansible_user|default('root') }}/.vnc/passwd -clip "$CLIP_REGION" \
  -cursor arrow -noxdamage -noxfixes -noipv6 \
  -desktop "Kindle App ($EMAIL)" -o "/var/log/x11vnc-${INSTANCE_ID}.log" -bg

echo "VNC service restarted for profile $EMAIL (instance $INSTANCE_ID)"
exit 0
