"""Automation server core module for managing emulators and automators."""

import logging
import os
import platform
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from automator import KindleAutomator
from views.core.app_state import AppState
from views.core.avd_profile_manager import AVDProfileManager

logger = logging.getLogger(__name__)


class AutomationServer:
    def __init__(self):
        self.automators = {}  # Dictionary to track multiple automators by email
        self.appium_process = None
        self.pid_dir = "logs"
        self.current_books = {}  # Track the currently open book title for each email
        os.makedirs(self.pid_dir, exist_ok=True)

        # Initialize the AVD profile manager
        self.android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
        self.profile_manager = AVDProfileManager(base_dir=self.android_home)
        self.current_email = None  # Current active email for backward compatibility

    @property
    def automator(self):
        """Get the current automator instance for the active email.
        For backward compatibility with existing code."""
        if self.current_email and self.current_email in self.automators:
            return self.automators[self.current_email]
        return None

    def initialize_automator(self, email=None):
        """Initialize automator for VNC-based manual authentication.

        Args:
            email: The profile ID for which to initialize an automator. If None, uses current_email.

        Returns:
            The automator instance
        """
        # If no email specified, use current_email
        target_email = email or self.current_email

        if not target_email:
            logger.warning("No target profile ID provided for automator initialization")
            return None

        # Check if we already have an automator for this profile
        if target_email in self.automators and self.automators[target_email]:
            logger.info(f"Using existing automator for profile {target_email}")
            return self.automators[target_email]

        # Initialize a new automator
        logger.info(f"Initializing new automator for profile {target_email}")
        automator = KindleAutomator()
        # Connect profile manager to automator for device ID tracking
        automator.profile_manager = self.profile_manager
        
        # Pass emulator_manager to automator for VNC integration
        automator.emulator_manager = self.profile_manager.emulator_manager
        logger.info(f"Added emulator_manager to automator for profile {target_email}")

        # Store the automator
        self.automators[target_email] = automator

        # Scan for any AVDs with email patterns in their names and register them
        discovered = self.profile_manager.scan_for_avds_with_emails()
        if discovered:
            logger.info(f"Auto-discovered {len(discovered)} profile-to-AVD mappings: {discovered}")

        return automator

    def switch_profile(self, email: str, force_new_emulator: bool = False) -> Tuple[bool, str]:
        """Switch to a profile for the given email address.

        Args:
            email: The email address to switch to
            force_new_emulator: If True, always stop any emulator for this email and start a new one
                               (used with recreate=1 flag)

        Returns:
            Tuple[bool, str]: (success, message)
        """
        logger.info(f"Switching to profile for email: {email}, force_new_emulator={force_new_emulator}")

        # Set this as the current active email
        self.current_email = email

        # Check if there's a running emulator for this profile
        is_running, emulator_id, avd_name = self.profile_manager.find_running_emulator_for_email(email)

        # Check if we already have an automator for this email
        if email in self.automators and self.automators[email]:
            # Ensure existing automator has the emulator_manager property
            if not hasattr(self.automators[email], "emulator_manager"):
                logger.info(f"Adding missing emulator_manager to existing automator for {email}")
                self.automators[email].emulator_manager = self.profile_manager.emulator_manager
            
            if is_running and not force_new_emulator:
                logger.info(
                    f"Automator already exists with running emulator for profile {email}, skipping profile switch"
                )
                return True, f"Already using profile for {email} with running emulator"
            elif not is_running and not force_new_emulator:
                # We have an automator but no running emulator
                # Get current profile to check if we're actually switching between users
                current_profile = self.profile_manager.get_current_profile()
                current_email = current_profile.get("email") if current_profile else None

                # If current profile email is different from target email, we should force start a new emulator
                if current_email and current_email != email:
                    logger.info(
                        f"Current profile is for {current_email} but requested {email} - forcing new emulator"
                    )
                    # Cleanup existing automator for this email since we're starting fresh
                    self.automators[email].cleanup()
                    self.automators[email] = None
                    # Will continue below to create a new emulator
                else:
                    # Same user, just no running emulator - wait for reconnect
                    logger.info(
                        f"No running emulator for profile {email}, but have automator - will use on next reconnect"
                    )
                    return True, f"Profile {email} is already active, waiting for reconnection"
            elif force_new_emulator:
                # Need to recreate the automator
                logger.info(f"Force new emulator requested for {email}, cleaning up existing automator")
                self.automators[email].cleanup()
                self.automators[email] = None

        # Switch to the profile for this email - this will not stop other emulators
        success, message = self.profile_manager.switch_profile(email, force_new_emulator=force_new_emulator)
        if not success:
            logger.error(f"Failed to switch profile: {message}")
            return False, message

        # Clear current book since we're switching profiles
        self.clear_current_book(email)

        logger.info(f"Successfully switched to profile for {email}")
        return True, message

    def save_pid(self, name: str, pid: int):
        """Save process ID to file"""
        pid_file = os.path.join(self.pid_dir, f"{name}.pid")
        try:
            with open(pid_file, "w") as f:
                f.write(str(pid))
            # Set file permissions to be readable by all
            os.chmod(pid_file, 0o644)
        except Exception as e:
            logger.error(f"Error saving PID file: {e}")

    def kill_existing_process(self, name: str):
        """Kill existing process if running on port 4098"""
        try:
            if name == "flask":
                # Use lsof to find process on port 4098
                pid = subprocess.check_output(["lsof", "-t", "-i:4098"]).decode().strip()
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
                    logger.info(f"Killed existing flask process with PID {pid}")
            elif name == "appium":
                subprocess.run(["pkill", "-f", "appium"], check=False)
                logger.info("Killed existing appium processes")
        except subprocess.CalledProcessError:
            logger.info(f"No existing {name} process found")
        except Exception as e:
            logger.error(f"Error killing {name} process: {e}")

    def start_appium(self):
        """Start Appium server and save PID"""
        self.kill_existing_process("appium")
        try:
            self.appium_process = subprocess.Popen(
                ["appium"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            self.save_pid("appium", self.appium_process.pid)
            logger.info(f"Started Appium server with PID {self.appium_process.pid}")
            return True
        except Exception as e:
            logger.error(f"Failed to start Appium server: {e}")
            return False

    def set_current_book(self, book_title, email=None):
        """Set the currently open book title for a specific email

        Args:
            book_title: The title of the book
            email: The email to associate with this book. If None, uses current_email.
        """
        target_email = email or self.current_email
        if not target_email:
            logger.warning("No email specified for set_current_book")
            return

        self.current_books[target_email] = book_title
        logger.info(f"Set current book for {target_email} to: {book_title}")

    def clear_current_book(self, email=None):
        """Clear the currently open book tracking variable for a specific email

        Args:
            email: The email for which to clear the book. If None, uses current_email.
        """
        target_email = email or self.current_email
        if not target_email:
            logger.warning("No email specified for clear_current_book")
            return

        if target_email in self.current_books:
            logger.info(f"Cleared current book for {target_email}: {self.current_books[target_email]}")
            del self.current_books[target_email]

    @property
    def current_book(self):
        """Get the current book for the active email. For backward compatibility."""
        if self.current_email and self.current_email in self.current_books:
            return self.current_books[self.current_email]
        return None
