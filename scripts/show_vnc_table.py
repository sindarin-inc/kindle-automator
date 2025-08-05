#!/usr/bin/env python
"""Display the VNC instances table in a compact, readable format."""

import os
import sys
from datetime import datetime, timezone

# Add parent directory to path to import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import db_connection
from database.models import VNCInstance


def format_datetime(dt):
    """Format datetime to short string."""
    if not dt:
        return "-"
    # Show relative time for recent updates
    now = datetime.now(timezone.utc)
    # Ensure dt is timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    if diff.total_seconds() < 3600:  # Less than 1 hour
        mins = int(diff.total_seconds() / 60)
        return f"{mins}m ago"
    elif diff.total_seconds() < 86400:  # Less than 1 day
        hours = int(diff.total_seconds() / 3600)
        return f"{hours}h ago"
    else:
        return dt.strftime("%m/%d %H:%M")


def truncate(text, length):
    """Truncate text to specified length."""
    if not text:
        return "-"
    if len(text) <= length:
        return text
    return text[:length - 2] + ".."


def main():
    """Display VNC instances table."""
    with db_connection.get_session() as session:
        instances = session.query(VNCInstance).order_by(VNCInstance.id).all()
        
        if not instances:
            print("No VNC instances found")
            return
        
        # Print header - fits in 140 chars
        print("┌────┬─────┬──────┬───────┬──────────────┬─────────────────────────────┬─────────┬────────────┬─────────────┐")
        print("│ ID │ Dsp │ VNC  │ Emu   │ Emulator ID  │ Profile                     │ Appium  │ Updated    │ Created     │")
        print("├────┼─────┼──────┼───────┼──────────────┼─────────────────────────────┼─────────┼────────────┼─────────────┤")
        
        for inst in instances:
            # Format fields
            id_str = str(inst.id).center(4)
            display = str(inst.display).center(5)
            vnc_port = str(inst.vnc_port).center(6)
            emu_port = str(inst.emulator_port).center(7)
            emu_id = truncate(inst.emulator_id, 14).ljust(14) if inst.emulator_id else "-".center(14)
            profile = truncate(inst.assigned_profile, 29).ljust(29) if inst.assigned_profile else "-".center(29)
            
            # Appium status
            if inst.appium_running:
                appium = "✓ Run".center(9)
            elif inst.appium_pid:
                appium = f"PID:{inst.appium_pid}".center(9)
            else:
                appium = "-".center(9)
            
            updated = format_datetime(inst.updated_at).center(12)
            created = format_datetime(inst.created_at).center(13)
            
            # Print row
            print(f"│{id_str}│{display}│{vnc_port}│{emu_port}│{emu_id}│{profile}│{appium}│{updated}│{created}│")
        
        print("└────┴─────┴──────┴───────┴──────────────┴─────────────────────────────┴─────────┴────────────┴─────────────┘")
        
        # Summary
        total = len(instances)
        assigned = sum(1 for i in instances if i.assigned_profile)
        with_emu = sum(1 for i in instances if i.emulator_id)
        orphaned = sum(1 for i in instances if not i.assigned_profile and not i.emulator_id)
        
        print(f"\nTotal: {total} | Assigned: {assigned} | With Emulator: {with_emu} | Orphaned: {orphaned}")


if __name__ == "__main__":
    main()