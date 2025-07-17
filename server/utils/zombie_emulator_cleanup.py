"""
Detect and clean up zombie emulator processes that block new emulator launches.

This module is called when emulator launch fails with "Running multiple emulators with the same AVD"
to clean up crashed emulators that are no longer functional but still holding resources.
"""

import logging
import os
import re
import signal
import subprocess
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ZombieEmulatorCleaner:
    """Handles detection and cleanup of zombie emulator processes."""

    def __init__(self):
        self.cleaned_zombies = []

    def _run_command(self, cmd: str, check: bool = True) -> str:
        """Run a shell command and return output."""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if check:
                logger.error(f"Command failed: {cmd}, error: {e.stderr}", exc_info=True)
                raise
            return e.stdout.strip() if e.stdout else ""

    def _get_emulator_process_by_avd(self, avd_name: str) -> Optional[Dict]:
        """Get emulator process info for a specific AVD."""
        cmd = f"ps aux | grep 'qemu-system-.*-avd {avd_name}' | grep -v grep"
        output = self._run_command(cmd, check=False)

        if not output:
            return None

        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 11:
                continue

            pid = int(parts[1])
            cmd_line = " ".join(parts[10:])

            # Extract port from command line
            port_match = re.search(r"-port (\d+)", cmd_line)
            if port_match:
                port = int(port_match.group(1))

                return {"pid": pid, "port": port, "avd_name": avd_name, "cmd_line": cmd_line}

        return None

    def _is_port_listening(self, port: int) -> bool:
        """Check if a port has a listening process."""
        cmd = f"lsof -i :{port} 2>/dev/null | grep LISTEN"
        output = self._run_command(cmd, check=False)
        return bool(output)

    def _is_emulator_in_adb(self, port: int) -> bool:
        """Check if emulator is connected to ADB."""
        emulator_id = f"emulator-{port}"
        cmd = "adb devices"
        output = self._run_command(cmd, check=False)
        return emulator_id in output

    def _clean_lock_files(self, avd_name: str) -> None:
        """Clean up lock files for a specific AVD."""
        avd_dir = f"/opt/android-sdk/avd/{avd_name}.avd"
        if not os.path.exists(avd_dir):
            return

        lock_files = [
            "hardware-qemu.ini.lock",
            "multiinstance.lock",
            "snapshot.lock",
            "cache.img.lock",
            "userdata-qemu.img.lock",
        ]

        for lock_file in lock_files:
            lock_path = os.path.join(avd_dir, lock_file)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                    logger.info(f"Removed lock file: {lock_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove {lock_path}: {e}")

    def _kill_process_and_children(self, pid: int) -> bool:
        """Kill a process and its children."""
        try:
            # First try SIGTERM
            os.kill(pid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to PID {pid}")
            time.sleep(2)

            # Check if still running
            try:
                os.kill(pid, 0)  # This doesn't kill, just checks if process exists
                # Still running, use SIGKILL
                os.kill(pid, signal.SIGKILL)
                logger.info(f"Sent SIGKILL to PID {pid}")
            except ProcessLookupError:
                logger.info(f"Process {pid} terminated successfully")

            # Kill any associated crashpad handlers
            try:
                self._run_command(f"pkill -P {pid} crashpad_handler 2>/dev/null || true", check=False)
            except:
                pass

            return True
        except Exception as e:
            logger.error(f"Error killing process {pid}: {e}", exc_info=True)
            return False

    def is_avd_zombie(self, avd_name: str) -> bool:
        """Check if a specific AVD has a zombie emulator process."""
        proc = self._get_emulator_process_by_avd(avd_name)
        if not proc:
            return False

        # A zombie is: process running, but port not listening and not in ADB
        port_listening = self._is_port_listening(proc["port"])
        in_adb = self._is_emulator_in_adb(proc["port"])

        is_zombie = not port_listening and not in_adb

        if is_zombie:
            logger.warning(
                f"AVD {avd_name} has zombie emulator: PID {proc['pid']}, "
                f"port {proc['port']} not listening and not in ADB"
            )

        return is_zombie

    def clean_zombie_for_avd(self, avd_name: str) -> bool:
        """Clean up zombie emulator for a specific AVD if it exists."""
        proc = self._get_emulator_process_by_avd(avd_name)
        if not proc:
            logger.debug(f"No emulator process found for AVD {avd_name}")
            return True

        # Check if it's actually a zombie
        if not self.is_avd_zombie(avd_name):
            logger.debug(f"AVD {avd_name} emulator is healthy, no cleanup needed")
            return True

        logger.info(f"Cleaning up zombie emulator for AVD {avd_name} (PID: {proc['pid']})")

        # Kill the zombie process
        if self._kill_process_and_children(proc["pid"]):
            # Clean up lock files
            self._clean_lock_files(avd_name)

            self.cleaned_zombies.append({"avd_name": avd_name, "pid": proc["pid"], "port": proc["port"]})

            logger.info(f"Successfully cleaned up zombie emulator for AVD {avd_name}")
            return True
        else:
            logger.error(f"Failed to clean up zombie emulator for AVD {avd_name}", exc_info=True)
            return False

    def clean_all_zombies_on_port(self, port: int) -> int:
        """Clean all zombie emulators on a specific port."""
        cmd = f"ps aux | grep 'qemu-system-.*-port {port}' | grep -v grep"
        output = self._run_command(cmd, check=False)

        cleaned_count = 0
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 11:
                continue

            pid = int(parts[1])

            # Check if it's a zombie (not listening and not in ADB)
            if not self._is_port_listening(port) and not self._is_emulator_in_adb(port):
                logger.info(f"Found zombie emulator on port {port} (PID: {pid})")
                if self._kill_process_and_children(pid):
                    cleaned_count += 1

        return cleaned_count

    def clean_all_zombies_on_display(self, display_num: int) -> int:
        """Clean all zombie emulators on a specific display."""
        # Find all emulator processes running on this display
        cmd = f"ps aux | grep 'qemu-system-' | grep -v grep"
        output = self._run_command(cmd, check=False)

        cleaned_count = 0
        pids_to_check = []

        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 11:
                continue

            pid = int(parts[1])

            # Check if this process is on the target display
            try:
                env_output = self._run_command(
                    f"cat /proc/{pid}/environ 2>/dev/null | tr '\\0' '\\n' | grep DISPLAY", check=False
                )
                if f"DISPLAY=:{display_num}" in env_output:
                    pids_to_check.append(pid)
            except:
                continue

        # Check each PID to see if it's a zombie
        for pid in pids_to_check:
            # Get the port from the process command line
            try:
                cmd_line = self._run_command(f"ps -p {pid} -o args --no-headers", check=False)
                port_match = re.search(r"-port (\d+)", cmd_line)
                if port_match:
                    port = int(port_match.group(1))

                    # Check if it's a zombie
                    if not self._is_port_listening(port) and not self._is_emulator_in_adb(port):
                        logger.info(
                            f"Found zombie emulator on display :{display_num} (PID: {pid}, port: {port})"
                        )

                        # Extract AVD name for lock cleanup
                        avd_match = re.search(r"-avd ([\w_]+)", cmd_line)
                        if avd_match:
                            avd_name = avd_match.group(1)
                            self._clean_lock_files(avd_name)

                        if self._kill_process_and_children(pid):
                            cleaned_count += 1
            except:
                continue

        if cleaned_count > 0:
            logger.info(f"Cleaned {cleaned_count} zombie emulators on display :{display_num}")

        return cleaned_count


def cleanup_zombie_emulator_for_avd(avd_name: str) -> bool:
    """
    Convenience function to clean up zombie emulator for a specific AVD.

    This should be called when emulator launch fails with
    "Running multiple emulators with the same AVD" error.

    Args:
        avd_name: The AVD name to check and clean

    Returns:
        True if cleanup was successful or no zombie found, False on error
    """
    cleaner = ZombieEmulatorCleaner()
    return cleaner.clean_zombie_for_avd(avd_name)


def cleanup_zombies_on_port(port: int) -> int:
    """
    Clean up all zombie emulators on a specific port.

    Args:
        port: The emulator port to clean (e.g., 5554)

    Returns:
        Number of zombies cleaned
    """
    cleaner = ZombieEmulatorCleaner()
    return cleaner.clean_all_zombies_on_port(port)


def cleanup_zombies_on_display(display_num: int) -> int:
    """
    Clean up all zombie emulators on a specific display.

    Args:
        display_num: The display number (e.g., 1 for :1)

    Returns:
        Number of zombies cleaned
    """
    cleaner = ZombieEmulatorCleaner()
    return cleaner.clean_all_zombies_on_display(display_num)
