#!/usr/bin/env python3
"""
Manually set up WireGuard VPN on a running emulator.
Usage: python setup_wireguard.py
"""

import os
import subprocess
import sys

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

from server.utils.mullvad_wireguard_manager import get_mullvad_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    # Check for required environment variables
    if not os.getenv("MULLVAD_ACCOUNT_NUMBER"):
        print("Error: MULLVAD_ACCOUNT_NUMBER not set in environment")
        sys.exit(1)

    # Get Android SDK path
    android_home = os.getenv("ANDROID_HOME", os.path.expanduser("~/Library/Android/sdk"))
    if not os.path.exists(android_home):
        print(f"Error: Android SDK not found at {android_home}")
        sys.exit(1)

    # Get list of running emulators
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)

        devices = []
        for line in result.stdout.strip().split("\n")[1:]:
            if line and "emulator" in line:
                device_id = line.split()[0]
                devices.append(device_id)

        if not devices:
            print("No running emulators found")
            sys.exit(1)

        print(f"Found {len(devices)} running emulator(s): {devices}")

        # Set up WireGuard on each emulator
        wireguard_manager = get_mullvad_manager(android_home)
        server_location = os.getenv("MULLVAD_LOCATION", "us")

        for device_id in devices:
            print(f"\nSetting up WireGuard on {device_id}...")

            if wireguard_manager.setup_wireguard_on_emulator(device_id, server_location):
                print(f"✓ WireGuard configured for location: {server_location}")

                # Wait for config import
                import time

                time.sleep(2)

                # Connect to VPN
                if wireguard_manager.connect_vpn(device_id):
                    print(f"✓ Connected to Mullvad VPN via WireGuard")

                    # Test connection
                    test_result = subprocess.run(
                        ["adb", "-s", device_id, "shell", "curl", "-s", "https://am.i.mullvad.net/connected"],
                        capture_output=True,
                        text=True,
                    )

                    if "You are connected" in test_result.stdout:
                        print(f"✓ VPN connection verified!")
                    else:
                        print(f"⚠ VPN may not be working properly")
                else:
                    print(f"✗ Failed to connect to VPN")
            else:
                print(f"✗ Failed to set up WireGuard")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
