#!/usr/bin/env python
"""Audit VNC instances and clean up stale entries using existing VNCInstanceManager."""

import argparse
import logging
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

# Add parent directory to path so we can import from server
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.repositories.vnc_instance_repository import VNCInstanceRepository
from server.utils.vnc_instance_manager import VNCInstanceManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_ANDROID_SDK = "/opt/android-sdk"
if platform.system() == "Darwin":
    DEFAULT_ANDROID_SDK = os.path.expanduser("~/Library/Android/sdk")

ANDROID_HOME = os.environ.get("ANDROID_HOME", DEFAULT_ANDROID_SDK)


def get_running_emulators():
    """Get list of actually running emulators using adb."""
    running_emulators = []
    try:
        result = subprocess.run(
            [f"{ANDROID_HOME}/platform-tools/adb", "devices"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            # Parse adb devices output
            for line in result.stdout.strip().split("\n")[1:]:  # Skip header
                if "\t" in line:
                    device_id = line.split("\t")[0]
                    if device_id.startswith("emulator-"):
                        running_emulators.append(device_id)
    except Exception as e:
        logger.error(f"Error getting running emulators: {e}")
    
    return running_emulators


def audit_vnc_dry_run():
    """
    Perform a dry run audit to show what would be cleaned up.
    Only audits instances on THIS server.
    """
    print("\n" + "="*60)
    print("VNC Instance Audit (DRY RUN)")
    print("="*60 + "\n")
    
    server_name = socket.gethostname()
    print(f"Server: {server_name}")
    print("="*60 + "\n")
    
    # Get repository instance
    repository = VNCInstanceRepository()
    
    # Get all instances for THIS server only (repository already filters by server_name)
    local_instances = repository.get_all_instances()
    print(f"Found {len(local_instances)} VNC instances on THIS server\n")
    
    # Get list of actually running emulators on THIS machine
    running_emulators = get_running_emulators()
    print(f"Found {len(running_emulators)} running emulators locally: {running_emulators}\n")
    
    # Track what would be cleaned
    stale_instances = []
    orphaned_instances = []
    
    print("Checking local VNC instances:")
    print("-" * 40)
    
    for instance in local_instances:
        status_parts = []
        
        # Basic info
        info = f"Instance {instance.id} (Display :{instance.display}, Port {instance.emulator_port})"
        
        # Profile assignment
        if instance.assigned_profile:
            status_parts.append(f"Profile: {instance.assigned_profile}")
        else:
            status_parts.append("No profile")
            if instance.emulator_id:
                orphaned_instances.append(instance)
        
        # Emulator status
        if instance.emulator_id:
            if instance.emulator_id in running_emulators:
                status_parts.append(f"✓ Emulator {instance.emulator_id} running")
            else:
                status_parts.append(f"✗ Emulator {instance.emulator_id} NOT running (stale)")
                stale_instances.append(instance)
        else:
            status_parts.append("No emulator ID")
        
        print(f"{info}")
        print(f"  {', '.join(status_parts)}")
    
    print("\n" + "="*60)
    print("DRY RUN RESULTS:")
    print("="*60 + "\n")
    
    if not stale_instances and not orphaned_instances:
        print("✓ All local VNC instances are in a valid state - nothing to clean!")
        return
    
    # Report what would be cleaned
    if stale_instances:
        print(f"Would clear {len(stale_instances)} stale emulator IDs:\n")
        for instance in stale_instances:
            print(f"  • Instance {instance.id} (Display :{instance.display})")
            print(f"    - Profile: {instance.assigned_profile or 'None'}")
            print(f"    - Would clear: {instance.emulator_id}")
    
    # Report orphaned instances
    if orphaned_instances:
        print(f"\n{len(orphaned_instances)} orphaned instances would become available:\n")
        for instance in orphaned_instances:
            print(f"  • Instance {instance.id} - would be available for reassignment")
    
    print("\n" + "="*60)
    print("DRY RUN COMPLETE - No changes were made")
    print("="*60)
    print(f"\nTo apply these changes, run: make db-audit")


def main():
    parser = argparse.ArgumentParser(description="Audit VNC instances on this server")
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Dry run mode - show what would be done without making changes"
    )
    
    args = parser.parse_args()
    
    try:
        if args.dry:
            # Do dry run analysis
            audit_vnc_dry_run()
        else:
            # Use the existing audit method from VNCInstanceManager
            print("\n" + "="*60)
            print("VNC Instance Audit")
            print("="*60 + "\n")
            
            server_name = socket.gethostname()
            print(f"Server: {server_name}")
            print("="*60 + "\n")
            
            vnc_manager = VNCInstanceManager.get_instance()
            print("Running audit_and_cleanup_stale_instances()...")
            print("This will audit ONLY local instances on this server.\n")
            
            # Run the existing audit method (already filters by server)
            vnc_manager.audit_and_cleanup_stale_instances()
            
            print("\n" + "="*60)
            print("AUDIT COMPLETE")
            print("="*60)
            print("\nCheck logs for detailed cleanup information")
            
    except KeyboardInterrupt:
        print("\n\nAudit cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()