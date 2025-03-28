#!/usr/bin/env python3
"""
Manual AVD registration tool for Kindle Automator.
This tool allows you to register a manually created AVD from Android Studio with
the profile management system.
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

# Add parent directory to path to import from server module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.config import ANDROID_SDK_PATH

# Path to profile data
PROFILES_DIR = os.path.join(ANDROID_SDK_PATH, "profiles")
PROFILES_INDEX_FILE = os.path.join(PROFILES_DIR, "profiles_index.json")
CURRENT_PROFILE_FILE = os.path.join(PROFILES_DIR, "current_profile.json")

def ensure_profiles_dir():
    """Ensure the profiles directory exists."""
    os.makedirs(PROFILES_DIR, exist_ok=True)

def load_profiles_index() -> Dict[str, str]:
    """Load profiles index from JSON file or create if it doesn't exist."""
    if os.path.exists(PROFILES_INDEX_FILE):
        try:
            with open(PROFILES_INDEX_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading profiles index: {e}")
            return {}
    else:
        return {}

def save_profiles_index(profiles_index: Dict[str, str]) -> None:
    """Save profiles index to JSON file."""
    try:
        with open(PROFILES_INDEX_FILE, 'w') as f:
            json.dump(profiles_index, f, indent=2)
    except Exception as e:
        print(f"Error saving profiles index: {e}")

def save_current_profile(email: str, avd_name: str) -> None:
    """Save current profile to JSON file."""
    import time
    current = {
        "email": email,
        "avd_name": avd_name,
        "last_used": int(time.time())
    }
    try:
        with open(CURRENT_PROFILE_FILE, 'w') as f:
            json.dump(current, f, indent=2)
        print(f"Set current profile to {email} with AVD {avd_name}")
    except Exception as e:
        print(f"Error saving current profile: {e}")

def list_avds() -> List[str]:
    """List all available AVDs created in Android Studio."""
    try:
        import subprocess
        result = subprocess.run(
            [f"{ANDROID_SDK_PATH}/emulator/emulator", "-list-avds"],
            capture_output=True,
            text=True,
            check=True
        )
        avds = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return avds
    except Exception as e:
        print(f"Error listing AVDs: {e}")
        return []

def register_avd(email: str, avd_name: str, set_as_current: bool = False) -> None:
    """Register a manually created AVD with a profile."""
    # Ensure profiles directory exists
    ensure_profiles_dir()
    
    # Load profiles index
    profiles_index = load_profiles_index()
    
    # Check if profile already exists and show previous AVD
    previous_avd = None
    if email in profiles_index:
        previous_avd = profiles_index[email]
        print(f"Updating profile for {email} from AVD '{previous_avd}' to '{avd_name}'")
        
    # Register AVD with profile
    profiles_index[email] = avd_name
    save_profiles_index(profiles_index)
    
    if previous_avd:
        print(f"Successfully updated AVD to '{avd_name}' for email '{email}'")
    else:
        print(f"Successfully registered AVD '{avd_name}' for email '{email}'")
    
    # Also update current profile if it's using this email
    if os.path.exists(CURRENT_PROFILE_FILE):
        try:
            with open(CURRENT_PROFILE_FILE, 'r') as f:
                current_profile = json.load(f)
                if current_profile.get("email") == email:
                    # Update the AVD name in the current profile
                    save_current_profile(email, avd_name)
                    print(f"Updated current profile for {email} to use AVD '{avd_name}'")
        except Exception as e:
            print(f"Error checking current profile: {e}")
    
    # Set as current profile if requested
    if set_as_current:
        save_current_profile(email, avd_name)

def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Register a manually created AVD with Kindle Automator's profile system"
    )
    parser.add_argument("--email", help="Email address for the profile")
    parser.add_argument("--avd", help="AVD name to register (if not provided, will list available AVDs)")
    parser.add_argument("--current", action="store_true", help="Set this as the current profile")
    parser.add_argument("--list", action="store_true", help="List available AVDs")
    args = parser.parse_args()
    
    # List AVDs if requested
    if args.list or not args.avd:
        avds = list_avds()
        print("Available AVDs (created in Android Studio):")
        for i, avd in enumerate(avds):
            print(f"  {i+1}. {avd}")
        
        if args.list:
            return
            
        # If no AVD is specified, let the user choose
        if not args.avd:
            if not avds:
                print("No AVDs found. Please create an AVD in Android Studio first.")
                return
                
            while True:
                choice = input("Select an AVD to register (number): ")
                try:
                    index = int(choice) - 1
                    if 0 <= index < len(avds):
                        avd_name = avds[index]
                        break
                    else:
                        print(f"Please enter a number between 1 and {len(avds)}")
                except ValueError:
                    print("Please enter a valid number")
        
    # If we have an AVD name from command line args, use that
    if args.avd:
        avd_name = args.avd
    
    # Get email address
    email = args.email
    while not email:
        email = input("Enter email address for this profile: ")
    
    # Register AVD with profile
    register_avd(email, avd_name, args.current)
    
    # Print instructions for usage
    print("\nRegistration complete!")
    print("You can now use this profile with Kindle Automator:")
    print(f"1. Start your AVD '{avd_name}' manually from Android Studio")
    print(f"2. Then run: make profile-switch EMAIL={email}")
    print(f"3. Start the server: make server")
    print("\nYou can also run: make auth EMAIL={email} PASSWORD=your_password")

if __name__ == "__main__":
    main()