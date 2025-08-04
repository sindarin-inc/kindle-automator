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
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.automators = {}  # Dictionary to track multiple automators by email
        self.pid_dir = "logs"
        self.current_books = {}  # Track the currently open book title for each email
        self.last_activity = {}  # Track last activity time for each email
        os.makedirs(self.pid_dir, exist_ok=True)

        # Initialize the AVD profile manager
        self.android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
        self.profile_manager = AVDProfileManager.get_instance(base_dir=self.android_home)

    @classmethod
    def get_instance(cls):
        """Get the singleton instance of AutomationServer."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # automator property has been removed - use get_automator(email) instead

    def get_automator(self, email):
        """Get automator for a specific email.

        Args:
            email: The email address to get the automator for

        Returns:
            The automator instance for the given email, or None if not found
        """
        if not email:
            logger.warning("Attempted to get automator with empty email")
            return None

        return self.automators.get(email)

    def initialize_automator(self, email):
        """Initialize automator for VNC-based manual authentication.

        Args:
            email: The profile ID for which to initialize an automator. REQUIRED.

        Returns:
            The automator instance or None if no email provided
        """
        if not email:
            logger.error("Email parameter is required for initialize_automator", exc_info=True)
            return None

        # Check if we already have an automator for this profile
        if email in self.automators and self.automators[email]:
            logger.info(f"Using existing automator for profile {email}")
            return self.automators[email]

        # Set email context for this thread so logs go to the right file
        from server.logging_config import EmailContext

        with EmailContext(email):
            # Initialize a new automator
            logger.info(f"Creating new KindleAutomator for email={email}")
            automator = KindleAutomator()
            logger.info(f"Created automator={id(automator)} for email={email}")
            # Connect profile manager to automator for device ID tracking
            automator.profile_manager = self.profile_manager
            # Add server reference so automator can access current book info
            automator.server_ref = self

            # Pass emulator_manager to automator for VNC integration
            automator.emulator_manager = self.profile_manager.emulator_manager

            # Store the automator
            self.automators[email] = automator
            # Set initial activity time
            self.update_activity(email)

            automator.initialize_driver()

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
        if not email:
            logger.error("Email parameter is required for switch_profile", exc_info=True)
            return False, "Email parameter is required"

        # Set email context for this thread so logs go to the right file
        from server.logging_config import EmailContext
        from server.utils.request_utils import email_override

        with EmailContext(email), email_override(email):
            return self._switch_profile_impl(email, force_new_emulator)

    def _switch_profile_impl(self, email: str, force_new_emulator: bool = False) -> Tuple[bool, str]:
        """Internal implementation of switch_profile with email context already set."""
        # current_email field has been removed
        # Always use explicit email parameters in all operations

        # Check if there's a running emulator for this profile
        is_running, emulator_id, avd_name = self.profile_manager.find_running_emulator_for_email(email)

        # On local development, check if this emulator is already in use by another profile
        import platform

        if platform.system() == "Darwin" and emulator_id:  # macOS development environment
            # Check if any other profile is using this emulator
            # Create a list copy to avoid dictionary modification during iteration
            for other_email, other_automator in list(self.automators.items()):
                if other_email != email and other_automator and hasattr(other_automator, "device_id"):
                    if other_automator.device_id == emulator_id:
                        # Check if the other automator is actually active
                        if hasattr(other_automator, "driver") and other_automator.driver:
                            logger.warning(f"Emulator {emulator_id} is already in use by {other_email}")
                            logger.info(
                                f"On local development, only one profile can use an emulator at a time"
                            )
                            # Clean up the other automator
                            logger.info(f"Cleaning up automator for {other_email} to free up {emulator_id}")
                            try:
                                other_automator.cleanup()
                            except Exception as e:
                                logger.warning(f"Error cleaning up automator for {other_email}: {e}")
                            self.automators[other_email] = None

        # Check if we already have an automator for this email
        if email in self.automators and self.automators[email]:
            # Ensure existing automator has the emulator_manager property
            if not hasattr(self.automators[email], "emulator_manager"):
                logger.info(f"Adding missing emulator_manager to existing automator for {email}")
                self.automators[email].emulator_manager = self.profile_manager.emulator_manager

            # Check if the automator's device is actually available via ADB
            device_available = False
            if hasattr(self.automators[email], "device_id") and self.automators[email].device_id:
                # Try to verify if the device is actually available in ADB
                device_id = self.automators[email].device_id
                logger.info(f"Verifying if automator's device {device_id} is actually available")
                try:
                    # This will throw an exception if the device isn't recognized by ADB
                    result = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "-s", device_id, "get-state"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    device_available = result.returncode == 0 and "device" in result.stdout
                    logger.info(
                        f"Device {device_id} verification: available={device_available}, result={result.stdout.strip()}"
                    )
                except Exception as e:
                    logger.warning(f"Error checking device {device_id} availability: {e}")
                    device_available = False

            # Handle different scenarios based on emulator state
            if is_running and not force_new_emulator and device_available:
                logger.info(
                    f"Automator already exists with running emulator for profile {email}, skipping profile switch"
                )
                return True, f"Already using profile for {email} with running emulator"
            elif not is_running or not device_available:
                # Either the emulator isn't running or the device isn't available in ADB
                if not is_running:
                    logger.info(f"Emulator not running for {email} according to ADB")
                if not device_available:
                    logger.info(
                        f"Device ID {self.automators[email].device_id} no longer available in ADB: {self.automators[email]}"
                    )

                if not force_new_emulator:
                    # We need to force a new emulator since the old one is no longer available
                    logger.info(f"Emulator for {email} no longer available, forcing new emulator creation")
                    # Cleanup existing automator
                    self.automators[email].cleanup()
                    self.automators[email] = None
                    # Force a new emulator
                    force_new_emulator = True
                else:
                    # Need to recreate the automator since force_new_emulator is True
                    logger.info(f"Force new emulator requested for {email}, cleaning up existing automator")
                    self.automators[email].cleanup()
                    self.automators[email] = None

        # Switch to the profile for this email - this will not stop other emulators
        success, message = self.profile_manager.switch_profile_and_start_emulator(
            email, force_new_emulator=force_new_emulator
        )
        if not success:
            logger.error(f"Failed to switch profile: {message}", exc_info=True)
            return False, message

        # Clear current book since we're switching profiles
        self.clear_current_book(email)

        # Update activity timestamp
        self.update_activity(email)

        return True, message

    def set_current_book(self, book_title, email):
        """Set the currently open book title for a specific email

        Args:
            book_title: The title of the book
            email: The email to associate with this book. REQUIRED.
        """
        if not email:
            logger.error("Email parameter is required for set_current_book", exc_info=True)
            return

        self.current_books[email] = book_title
        logger.info(f"Set current book for {email} to: {book_title}")

    def clear_current_book(self, email):
        """Clear the currently open book tracking variable for a specific email

        Args:
            email: The email for which to clear the book. REQUIRED.
        """
        if not email:
            logger.error("Email parameter is required for clear_current_book", exc_info=True)
            return

        if email in self.current_books:
            logger.info(f"Cleared current book for {email}: {self.current_books[email]}")
            del self.current_books[email]

    def get_current_book(self, email):
        """Get the current book for the specified email.

        Args:
            email: The email to get the current book for. REQUIRED.

        Returns:
            str: The title of the current book, or None if no book is open
        """
        if not email:
            logger.error("Email parameter is required for get_current_book", exc_info=True)
            return None

        return self.current_books.get(email)

    # current_book property has been removed - use get_current_book(email) instead

    def save_pid(self, name: str, pid: int):
        """Save process ID to file for Flask process."""
        pid_file = os.path.join(self.pid_dir, f"{name}.pid")
        try:
            with open(pid_file, "w") as f:
                f.write(str(pid))
            os.chmod(pid_file, 0o644)
        except Exception as e:
            logger.error(f"Error saving PID file: {e}", exc_info=True)

    def kill_existing_process(self, name: str):
        """Kill existing Flask process if running on port 4098."""
        if name == "flask":
            try:
                # Use lsof to find process on port 4098
                pid = subprocess.check_output(["lsof", "-t", "-i:4098"]).decode().strip()
                if pid:
                    os.kill(int(pid), signal.SIGTERM)
                    logger.info(f"Killed existing flask process with PID {pid}")

                    # Wait for port to be released (up to 20 seconds)
                    import time

                    for i in range(200):  # 200 * 0.1s = 20s max
                        try:
                            # Check if port is still in use
                            subprocess.check_output(["lsof", "-t", "-i:4098"], stderr=subprocess.DEVNULL)
                            time.sleep(0.1)
                        except subprocess.CalledProcessError:
                            # Port is free
                            logger.info(f"Port 4098 is now free after {(i+1)*0.1:.1f}s")
                            break
                    else:
                        logger.warning("Port 4098 still in use after 20 seconds")
            except subprocess.CalledProcessError:
                logger.info("No existing flask process found")
            except Exception as e:
                logger.error(f"Error killing flask process: {e}", exc_info=True)

    def update_activity(self, email):
        """Update the last activity timestamp for an email.

        Args:
            email: The email address to update activity for
        """
        if email:
            self.last_activity[email] = time.time()

    def get_last_activity_time(self, email):
        """Get the last activity timestamp for an email.

        Args:
            email: The email address to get activity time for

        Returns:
            The last activity timestamp or None if not found
        """
        return self.last_activity.get(email)

    def ensure_seed_clone_prepared(self):
        """Ensure the seed clone AVD is prepared for fast user initialization.

        This method will be called lazily when the first new user needs to be created.
        It ensures that a seed clone AVD exists with a pre-boot snapshot.

        Returns:
            bool: True if seed clone is ready, False otherwise
        """
        try:
            logger.info("Checking if seed clone AVD needs to be prepared...")
            success, message = self.profile_manager.ensure_seed_clone_ready()

            if success:
                logger.info(f"Seed clone AVD is ready: {message}")
            else:
                logger.error(f"Failed to prepare seed clone AVD: {message}", exc_info=True)

            return success

        except Exception as e:
            logger.error(f"Error preparing seed clone AVD: {e}", exc_info=True)
            return False
