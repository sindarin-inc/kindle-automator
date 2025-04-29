#!/bin/bash
#
# Default VNC-enabled emulator launcher for Kindle Automator
# This script launches Android emulator and makes it available on the configured VNC display
#

# Use the default display :1 if not specified
export DISPLAY=:1

# Directory where Android SDK is installed
ANDROID_HOME=/opt/android-sdk

# Get the assigned VNC instance for this profile if possible
EMAIL_ARG=""
for arg in "$@"; do
  if [[ "$arg" == "-avd" ]]; then
    # Get the next argument after -avd which is the AVD name
    AVD_NAME_INDEX=1
  elif [[ -n "$AVD_NAME_INDEX" ]]; then
    AVD_NAME="$arg"
    # Try to extract email from AVD name
    if [[ "$AVD_NAME" == *"_"*"_"* ]]; then
      EMAIL_PART=$(echo "$AVD_NAME" | cut -d'_' -f2)
      if [[ "$EMAIL_PART" == *"_"* ]]; then
        EMAIL_PART=$(echo "$EMAIL_PART" | tr '_' '.')
      fi
      if [[ "$EMAIL_PART" == *"@"* ]]; then
        EMAIL_ARG="$EMAIL_PART"
      else
        DOMAIN_PART=$(echo "$AVD_NAME" | cut -d'_' -f3)
        if [[ -n "$DOMAIN_PART" ]]; then
          EMAIL_ARG="${EMAIL_PART}@${DOMAIN_PART}"
        fi
      fi
    fi
    AVD_NAME_INDEX=""
  fi
done

# If we found an email from the AVD name, try to get its VNC instance
if [[ -n "$EMAIL_ARG" ]]; then
  echo "Extracted email from AVD name: $EMAIL_ARG"
  
  # Try to get VNC instance from instance map
  if [[ -f "/opt/vnc_instance_map.json" ]]; then
    echo "Checking for assigned VNC instance for $EMAIL_ARG"
    INSTANCE_ID=$(jq -r ".instances[] | select(.assigned_profile == \"$EMAIL_ARG\") | .id" /opt/vnc_instance_map.json)
    
    if [[ -n "$INSTANCE_ID" && "$INSTANCE_ID" != "null" ]]; then
      DISPLAY_NUM=$(jq -r ".instances[] | select(.assigned_profile == \"$EMAIL_ARG\") | .display" /opt/vnc_instance_map.json)
      
      if [[ -n "$DISPLAY_NUM" && "$DISPLAY_NUM" != "null" ]]; then
        echo "Using assigned VNC display :$DISPLAY_NUM for profile $EMAIL_ARG"
        export DISPLAY=":$DISPLAY_NUM"
        
        # Make sure the VNC service is running for this display
        systemctl is-active --quiet vnc@$INSTANCE_ID || {
          echo "Starting VNC service for instance $INSTANCE_ID..."
          systemctl start vnc@$INSTANCE_ID
        }
      fi
    fi
  fi
fi

# If standalone VNC is running, use display 99 or 100 by default
if systemctl is-active --quiet standalone-vnc; then
  # Check which display the standalone service is using
  for DISP in 100 101; do
    if pgrep -f "Xvfb :$DISP" > /dev/null; then
      echo "Found standalone VNC on display :$DISP"
      export DISPLAY=":$DISP"
      break
    fi
  done
fi

echo "Using display $DISPLAY for emulator"

# Extra options for VNC display operation
EMULATOR_OPTS="-gpu swiftshader_indirect -no-boot-anim"

# Execute the emulator command with the virtual display
# This script accepts all normal emulator arguments
# Usage: vnc-emulator-launcher.sh -avd <avd_name> [other options]
"$ANDROID_HOME/emulator/emulator" $EMULATOR_OPTS "$@"