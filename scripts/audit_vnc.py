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
logging.basicConfig(level=logging.INFO, format="%(message)s")
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
    print("\n" + "=" * 60)
    print("VNC Instance Audit (DRY RUN)")
    print("=" * 60 + "\n")

    server_name = socket.gethostname()
    print(f"Server: {server_name}")
    print("=" * 60 + "\n")

    # Get repository instance
    repository = VNCInstanceRepository()

    # Get all instances for THIS server only (repository already filters by server_name)
    local_instances = repository.get_all_instances()
    print(f"Found {len(local_instances)} VNC instances on THIS server\n")

    # Get list of actually running emulators on THIS machine
    running_emulators = get_running_emulators()
    print(f"Found {len(running_emulators)} running emulators locally: {running_emulators}\n")

    # Track what would be cleaned
    stale_emulator_ids = []
    stale_assignments = []
    orphaned_instances = []
    healthy_instances = []

    print("Checking local VNC instances:")
    print("-" * 40)

    for instance in local_instances:
        status_parts = []
        is_stale = False

        # Basic info
        info = f"Instance {instance.id} (Display :{instance.display}, Port {instance.emulator_port})"

        # Check different states
        if instance.assigned_profile:
            status_parts.append(f"Profile: {instance.assigned_profile}")

            if instance.emulator_id:
                if instance.emulator_id in running_emulators:
                    # Healthy: has profile and running emulator
                    status_parts.append(f"✓ Emulator {instance.emulator_id} running")
                    healthy_instances.append(instance)
                else:
                    # Stale: has profile but emulator_id not running
                    status_parts.append(f"✗ Emulator {instance.emulator_id} NOT running (stale)")
                    stale_emulator_ids.append(instance)
                    is_stale = True
            else:
                # Stale: has profile but no emulator_id
                status_parts.append("⚠ No emulator ID (stale assignment)")
                stale_assignments.append(instance)
                is_stale = True
        else:
            status_parts.append("No profile")
            if instance.emulator_id:
                # Orphaned: no profile but has emulator_id
                status_parts.append(f"⚠ Has emulator {instance.emulator_id} (orphaned)")
                orphaned_instances.append(instance)
                is_stale = True
            else:
                # Available: no profile, no emulator
                status_parts.append("Available")

        print(f"{info}")
        if is_stale:
            print(f"  {', '.join(status_parts)} [STALE]")
        else:
            print(f"  {', '.join(status_parts)}")

    print("\n" + "=" * 60)
    print("DRY RUN RESULTS:")
    print("=" * 60 + "\n")

    total_issues = len(stale_emulator_ids) + len(stale_assignments) + len(orphaned_instances)

    if total_issues == 0:
        print("✓ All local VNC instances are in a valid state - nothing to clean!")
        print(f"  • {len(healthy_instances)} healthy instances with running emulators")
        available = len(local_instances) - len(healthy_instances) - len(stale_assignments)
        if available > 0:
            print(f"  • {available} available instances for new assignments")
        return

    # Report issues found
    print(f"Found {total_issues} issues to address:\n")

    # Report stale emulator IDs
    if stale_emulator_ids:
        print(f"1. Stale emulator IDs ({len(stale_emulator_ids)} instances):")
        print("   These have emulator_ids that are not running\n")
        for instance in stale_emulator_ids:
            print(f"  • Instance {instance.id} (Display :{instance.display})")
            print(f"    - Profile: {instance.assigned_profile}")
            print(f"    - Would clear: {instance.emulator_id}")
        print()

    # Report stale assignments
    if stale_assignments:
        print(f"2. Stale assignments ({len(stale_assignments)} instances):")
        print("   These have profiles assigned but no running emulator\n")
        for instance in stale_assignments:
            print(f"  • Instance {instance.id} (Display :{instance.display})")
            print(f"    - Profile: {instance.assigned_profile}")
            print(f"    - Status: No emulator running (assignment preserved)")
        print()

    # Report orphaned instances
    if orphaned_instances:
        print(f"3. Orphaned instances ({len(orphaned_instances)} instances):")
        print("   These have no profile but still have emulator_id\n")
        for instance in orphaned_instances:
            print(f"  • Instance {instance.id}")
            print(f"    - Would clear: {instance.emulator_id}")
        print()

    print("=" * 60)
    print("DRY RUN COMPLETE - No changes were made")
    print("=" * 60)
    print(f"\nTo apply cleanup (clears stale emulator_ids), run: make db-audit")
    print("Note: Profile assignments are preserved even if emulator is not running")


def main():
    parser = argparse.ArgumentParser(description="Audit VNC instances on this server")
    parser.add_argument(
        "--dry", action="store_true", help="Dry run mode - show what would be done without making changes"
    )

    args = parser.parse_args()

    try:
        if args.dry:
            # Do dry run analysis
            audit_vnc_dry_run()
        else:
            # Use the existing audit method from VNCInstanceManager
            print("\n" + "=" * 60)
            print("VNC Instance Audit")
            print("=" * 60 + "\n")

            server_name = socket.gethostname()
            print(f"Server: {server_name}")
            print("=" * 60 + "\n")

            vnc_manager = VNCInstanceManager.get_instance()
            print("Running audit_and_cleanup_stale_instances()...")
            print("This will audit ONLY local instances on this server.\n")

            # Run the existing audit method (already filters by server)
            vnc_manager.audit_and_cleanup_stale_instances()

            print("\n" + "=" * 60)
            print("AUDIT COMPLETE")
            print("=" * 60)
            print("\nCheck logs for detailed cleanup information")

    except KeyboardInterrupt:
        print("\n\nAudit cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Audit failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
