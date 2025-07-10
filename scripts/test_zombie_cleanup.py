#!/usr/bin/env python3
"""
Test script to verify zombie emulator cleanup works on prod.
This can be run directly on the prod server without deploying.
"""

import sys
import os

# Add the parent directory to Python path so we can import from server.utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.utils.zombie_emulator_cleanup import ZombieEmulatorCleaner


def test_zombie_detection():
    """Test zombie detection by checking all emulator ports."""
    cleaner = ZombieEmulatorCleaner()
    
    print("=== Checking all emulator ports ===")
    # Check all possible emulator ports (5554-5584 covers 16 emulators)
    for port in range(5554, 5586, 2):
        listening = cleaner._is_port_listening(port)
        in_adb = cleaner._is_emulator_in_adb(port)
        if not listening and not in_adb:
            # Check if there's a process using this port
            cmd = f"ps aux | grep 'qemu-system-x86_64.*-port {port}' | grep -v grep"
            result = cleaner._run_command(cmd, check=False)
            if result:
                print(f"Port {port}: ZOMBIE (not listening, not in ADB, but process exists)")
                # Extract PID and AVD name from the process
                for line in result.splitlines():
                    parts = line.split()
                    if len(parts) > 11:
                        pid = parts[1]
                        import re
                        avd_match = re.search(r'-avd ([\w_]+)', ' '.join(parts[10:]))
                        avd_name = avd_match.group(1) if avd_match else "unknown"
                        print(f"  -> PID: {pid}, AVD: {avd_name}")
            else:
                if listening or in_adb:
                    print(f"Port {port}: OK (listening={listening}, in_adb={in_adb})")


def test_cleanup_specific_avd(avd_name):
    """Test cleanup of a specific AVD."""
    cleaner = ZombieEmulatorCleaner()
    
    print(f"\n=== Testing cleanup for AVD: {avd_name} ===")
    if cleaner.is_avd_zombie(avd_name):
        print(f"AVD {avd_name} is a zombie, attempting cleanup...")
        success = cleaner.clean_zombie_for_avd(avd_name)
        if success:
            print(f"Successfully cleaned up zombie for AVD {avd_name}")
        else:
            print(f"Failed to clean up zombie for AVD {avd_name}")
    else:
        print(f"AVD {avd_name} is not a zombie, no cleanup needed")


def test_cleanup_display(display_num):
    """Test cleanup of all zombies on a display."""
    cleaner = ZombieEmulatorCleaner()
    
    print(f"\n=== Testing cleanup for display :{display_num} ===")
    cleaned = cleaner.clean_all_zombies_on_display(display_num)
    print(f"Cleaned {cleaned} zombie emulators on display :{display_num}")


def main():
    """Main test function."""
    if os.geteuid() != 0:
        print("This script must be run as root")
        sys.exit(1)
    
    import argparse
    parser = argparse.ArgumentParser(description="Test zombie emulator cleanup")
    parser.add_argument("--cleanup", help="AVD name to clean up", metavar="AVD_NAME")
    parser.add_argument("--cleanup-display", help="Display number to clean up", type=int, metavar="DISPLAY_NUM")
    parser.add_argument("--dry-run", action="store_true", help="Only detect, don't clean")
    args = parser.parse_args()
    
    if args.cleanup:
        if args.dry_run:
            cleaner = ZombieEmulatorCleaner()
            is_zombie = cleaner.is_avd_zombie(args.cleanup)
            print(f"AVD {args.cleanup}: {'ZOMBIE (would clean)' if is_zombie else 'OK'}")
        else:
            test_cleanup_specific_avd(args.cleanup)
    elif args.cleanup_display:
        test_cleanup_display(args.cleanup_display)
    else:
        # Just run detection
        test_zombie_detection()


if __name__ == "__main__":
    main()