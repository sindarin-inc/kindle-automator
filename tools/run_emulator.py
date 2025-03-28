#!/usr/bin/env python3
"""
Emulator runner script for starting Android AVDs with different approaches.
Particularly useful for ARM Macs where running x86_64 emulators requires special handling.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from typing import Dict, List, Optional

# Add parent directory to path to import from server module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.config import ANDROID_SDK_PATH, AVAILABLE_APPROACHES, HOST_ARCHITECTURE

# Path to profile data
PROFILES_DIR = os.path.join(ANDROID_SDK_PATH, "profiles")
CURRENT_PROFILE_FILE = os.path.join(PROFILES_DIR, "current_profile.json")

def get_current_profile() -> Optional[Dict]:
    """Get the current profile from the profile manager."""
    if os.path.exists(CURRENT_PROFILE_FILE):
        try:
            with open(CURRENT_PROFILE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading current profile: {e}")
    return None

def list_avds() -> List[str]:
    """List all available AVDs."""
    try:
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

def try_approach(avd_name: str, approach: Dict) -> bool:
    """
    Try to start the emulator using a specific approach.
    
    Args:
        avd_name: The name of the AVD to start
        approach: The approach configuration to use
        
    Returns:
        bool: True if the emulator started successfully, False otherwise
    """
    print(f"Trying approach: {approach['name']} - {approach['description']}")
    
    # Set up environment
    env = os.environ.copy()
    env.update(approach.get("environment", {}))
    env["ANDROID_SDK_ROOT"] = ANDROID_SDK_PATH
    env["ANDROID_AVD_HOME"] = f"{ANDROID_SDK_PATH}/avd"
    
    # Check if this is a shell command
    is_shell_command = approach.get("shell_command", False)
    
    # Build command
    if is_shell_command:
        # For shell commands, we need to build the command in a special way
        cmd_prefix = approach.get("command_prefix", [])
        emulator_path = f"{ANDROID_SDK_PATH}/emulator/emulator"
        options = " ".join(approach.get("command_options", []))
        # The shell command to run
        shell_cmd = f"cd {ANDROID_SDK_PATH}/emulator && ./emulator @{avd_name} {options}"
        cmd = cmd_prefix + [shell_cmd]
        print(f"Running shell command: {' '.join(cmd)}")
    else:
        # Standard command construction
        cmd_prefix = approach.get("command_prefix", [])
        cmd = cmd_prefix + [f"{ANDROID_SDK_PATH}/emulator/emulator", "-avd", avd_name]
        cmd.extend(approach.get("command_options", []))
        print(f"Running command: {' '.join(cmd)}")
    
    # Try to start the emulator
    try:
        process = subprocess.Popen(
            cmd,
            env=env,
            shell=is_shell_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait a bit to see if the process starts
        time.sleep(5)
        
        # Check if process is still running
        if process.poll() is None:
            print("Process started successfully!")
            
            # Wait for emulator to boot - this can take some time
            print("Waiting for emulator to boot (may take a minute or two)...")
            deadline = time.time() + 120  # 2 minutes timeout
            while time.time() < deadline:
                try:
                    # Check if the emulator is booted
                    adb_cmd = f"{ANDROID_SDK_PATH}/platform-tools/adb"
                    boot_completed = subprocess.run(
                        [adb_cmd, "shell", "getprop", "sys.boot_completed"],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if boot_completed.stdout.strip() == "1":
                        print("\nEmulator booted successfully!")
                        print(f"AVD {avd_name} is now running.")
                        return True
                except Exception:
                    # Ignore exceptions during boot polling
                    pass
                
                # Print progress indicator
                sys.stdout.write(".")
                sys.stdout.flush()
                time.sleep(2)
                
            # If we get here, the emulator didn't boot within the timeout
            print("\nTimeout waiting for emulator to boot.")
            process.terminate()
            return False
        else:
            # Process exited prematurely
            stdout, stderr = process.communicate()
            print(f"Process exited prematurely with return code {process.returncode}")
            print(f"Stdout: {stdout.decode() if stdout else 'None'}")
            print(f"Stderr: {stderr.decode() if stderr else 'None'}")
            return False
            
    except Exception as e:
        print(f"Error running emulator: {e}")
        return False

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Run Android emulator with different approaches.")
    parser.add_argument("--avd", help="AVD name to start (optional)")
    parser.add_argument("--list", action="store_true", help="List available AVDs")
    parser.add_argument("--approach", type=int, help="Approach index to use (default: try all)")
    parser.add_argument("--current", action="store_true", help="Use the current profile's AVD (default)")
    args = parser.parse_args()
    
    if args.list:
        avds = list_avds()
        print("Available AVDs:")
        for i, avd in enumerate(avds):
            print(f"  {i+1}. {avd}")
        return
    
    # Get AVD name from command line or get current profile's AVD
    avd_name = args.avd
    
    # If no AVD is specified, try to use the current profile's AVD
    if not avd_name and (args.current or not args.avd):
        current_profile = get_current_profile()
        if current_profile and "avd_name" in current_profile:
            avd_name = current_profile["avd_name"]
            print(f"Using current profile's AVD: {avd_name} (email: {current_profile.get('email', 'unknown')})")
    
    # If we still don't have an AVD name, let the user choose
    if not avd_name:
        avds = list_avds()
        if not avds:
            print("No AVDs found. Please create an AVD first.")
            return
            
        print("Available AVDs:")
        for i, avd in enumerate(avds):
            print(f"  {i+1}. {avd}")
            
        while True:
            choice = input("Select an AVD to run (number): ")
            try:
                index = int(choice) - 1
                if 0 <= index < len(avds):
                    avd_name = avds[index]
                    break
                else:
                    print(f"Please enter a number between 1 and {len(avds)}")
            except ValueError:
                print("Please enter a valid number")
    
    print(f"Selected AVD: {avd_name}")
    print(f"Host architecture: {HOST_ARCHITECTURE}")
    
    # Get approach from command line or try all
    if args.approach is not None and 0 <= args.approach < len(AVAILABLE_APPROACHES):
        # Try only the specified approach
        approach = AVAILABLE_APPROACHES[args.approach]
        success = try_approach(avd_name, approach)
        if success:
            print(f"Successfully started AVD {avd_name} with approach {approach['name']}")
            # Keep running until user terminates
            try:
                print("Press Ctrl+C to terminate the emulator...")
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nTerminating emulator...")
                subprocess.run([f"{ANDROID_SDK_PATH}/platform-tools/adb", "emu", "kill"], check=False)
        else:
            print(f"Failed to start AVD {avd_name} with approach {approach['name']}")
    else:
        # Try all approaches
        print("Trying all available approaches...")
        for i, approach in enumerate(AVAILABLE_APPROACHES):
            print(f"\nApproach {i+1}/{len(AVAILABLE_APPROACHES)}: {approach['name']}")
            success = try_approach(avd_name, approach)
            if success:
                print(f"Successfully started AVD {avd_name} with approach {approach['name']}")
                # Keep running until user terminates
                try:
                    print("Press Ctrl+C to terminate the emulator...")
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\nTerminating emulator...")
                    subprocess.run([f"{ANDROID_SDK_PATH}/platform-tools/adb", "emu", "kill"], check=False)
                return
            else:
                print(f"Approach {approach['name']} failed, trying next approach...")
                
        print("\nAll approaches failed to start the emulator.")

if __name__ == "__main__":
    main()