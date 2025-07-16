import argparse
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback

from driver import Driver
from server.utils.request_utils import get_sindarin_email
from server.utils.screenshot_utils import take_secure_screenshot
from views.core.app_state import AppState
from views.state_machine import KindleStateMachine

logger = logging.getLogger(__name__)


class KindleAutomator:
    def __init__(self):
        self.driver = None
        self.state_machine = None
        self.device_id = None  # Will be set during initialization
        self.profile_manager = None  # Will be set by server.py
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def cleanup(self, skip_driver_quit=False):
        """Cleanup resources.

        Args:
            skip_driver_quit: If True, skip calling driver.quit() (used during shutdown when emulator is already gone)
        """
        import time as _time

        cleanup_start = _time.time()

        if self.driver:
            if skip_driver_quit:
                logger.info("Skipping driver.quit() as requested (emulator already stopped)")
                self.driver = None
                self.device_id = None
            else:
                try:
                    # Get the Driver instance from the driver attribute (which is the Appium driver)
                    # We need to find the Driver instance that contains this Appium driver
                    if hasattr(self, "_driver_instance"):
                        # If we stored a reference to the Driver instance
                        logger.info("Calling quit on Driver instance")
                        quit_start = _time.time()
                        self._driver_instance.quit()
                        logger.info(f"Driver quit took {_time.time() - quit_start:.1f}s")
                    else:
                        # Otherwise, try to quit the Appium driver directly
                        logger.info("Calling quit on Appium driver directly")
                        quit_start = _time.time()
                        self.driver.quit()
                        logger.info(f"Appium driver quit took {_time.time() - quit_start:.1f}s")
                except Exception as e:
                    logger.warning(f"Error during driver cleanup: {e}", exc_info=True)
                    logger.info(f"Driver cleanup error after {_time.time() - cleanup_start:.1f}s")
                finally:
                    finally_start = _time.time()
                    self.driver = None
                    self.device_id = None
                    logger.info(f"Finally block took {_time.time() - finally_start:.1f}s")

        logger.info(f"Total automator.cleanup() took {_time.time() - cleanup_start:.1f}s")

    def initialize_driver(self):
        """Initialize the Appium driver and Kindle app."""
        # Check if we're already in initialization to prevent infinite recursion
        if hasattr(self, "_initializing_driver") and self._initializing_driver:
            logger.error("Already initializing driver, avoiding infinite recursion", exc_info=True)
            return False

        self._initializing_driver = True
        try:
            # Create and initialize driver
            driver = Driver()
            # Set the automator reference in the driver
            driver.automator = self
            if not driver.initialize():
                logger.error("Failed to initialize driver", exc_info=True)
                return False

            self.driver = driver.get_appium_driver_instance()
            if not self.driver:
                logger.error("Failed to get Appium driver instance", exc_info=True)
                return False

            # Store reference to the Driver instance for cleanup
            self._driver_instance = driver

            # Make sure the driver instance also has a reference to this automator
            # This ensures auth_handler can access it
            if self.driver and not hasattr(self.driver, "automator"):
                self.driver.automator = self
        finally:
            self._initializing_driver = False

        # Get device ID from driver
        self.device_id = driver.get_device_id()

        # Verify the device ID matches what's assigned in VNC instance manager
        email = get_sindarin_email()
        try:
            from server.utils.vnc_instance_manager import VNCInstanceManager

            vnc_manager = VNCInstanceManager.get_instance()
            vnc_emulator_id = vnc_manager.get_emulator_id(email)
            if vnc_emulator_id and vnc_emulator_id != self.device_id:
                logger.warning(
                    f"Device ID mismatch: driver has {self.device_id}, VNC instance has {vnc_emulator_id} for {email}"
                )
                return False
        except Exception as e:
            logger.warning(f"Could not verify device ID from VNC instance manager: {e}")

        # Initialize state machine without credentials or captcha
        self.state_machine = KindleStateMachine(self.driver)

        # Ensure the view_inspector has the device_id directly
        if self.device_id and hasattr(self.state_machine, "view_inspector"):
            self.state_machine.view_inspector.device_id = self.device_id

        # The profile_manager reference is set on the automator instance
        # The reader_handler will access it via driver.automator.profile_manager

        # Verify app is in foreground - sometimes it quits after driver connects
        try:
            current_activity = self.driver.current_activity

            # If we're not in the Kindle app, try to relaunch it
            # Check for both com.amazon.kindle and com.amazon.kcp activities (both are valid Kindle app activities)
            # Also accept the Google Play review dialog which can appear over the Kindle app
            if not (
                current_activity.startswith("com.amazon")
                or current_activity == "com.google.android.finsky.inappreviewdialog.InAppReviewActivity"
            ):
                logger.warning("App is not in foreground after initialization, trying to launch it")
                if self.state_machine.view_inspector.ensure_app_foreground():
                    # Verify we're back in the app
                    current_activity = self.driver.current_activity

                    if not (
                        current_activity.startswith("com.amazon")
                        or current_activity
                        == "com.google.android.finsky.inappreviewdialog.InAppReviewActivity"
                    ):
                        logger.error(
                            "Failed to bring Kindle app to foreground after relaunch attempt", exc_info=True
                        )
                        return False
        except Exception as e:
            logger.warning(f"Error checking app state after initialization: {e}", exc_info=True)
            # Continue anyway, the state machine will handle errors later

        return True

    def store_current_page_source(self):
        """Store the current page source as a screenshot"""
        # Get the current page source
        page_source = self.driver.page_source

        # Store the page source in a file named after the current state
        state_name = self.state_machine.current_state.name
        file_name = f"{state_name}.xml"
        file_path = os.path.join(self.screenshots_dir, file_name)
        with open(file_path, "w") as file:
            file.write(page_source)
        logger.info(f"Saved current page source ({state_name}) to {file_path}")

    def take_diagnostic_snapshot(self, operation_name="unknown"):
        """Capture a diagnostic snapshot including screenshot and page source for debugging.

        Args:
            operation_name: Name of the operation being performed (for filename)

        Returns:
            bool: True if snapshot was taken successfully, False otherwise
        """
        timestamp = int(time.time())
        try:
            # Take a screenshot first
            screenshot_path = os.path.join(self.screenshots_dir, f"{operation_name}_{timestamp}.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Diagnostic screenshot saved to {screenshot_path}")

            # Then get page source
            try:
                page_source = self.driver.page_source
                xml_path = os.path.join(self.screenshots_dir, f"{operation_name}_{timestamp}.xml")
                with open(xml_path, "w") as f:
                    f.write(page_source)
                logger.info(f"Diagnostic page source saved to {xml_path}")
            except Exception as ps_e:
                logger.warning(f"Could not capture page source for diagnostic snapshot: {ps_e}")

            # Get current activity name
            try:
                current_activity = self.driver.current_activity
                logger.info(f"Current activity during {operation_name}: {current_activity}")
            except Exception as act_e:
                logger.warning(f"Could not get current activity: {act_e}")

            return True
        except Exception as e:
            logger.warning(f"Failed to take diagnostic snapshot for {operation_name}: {e}")
            return False

    def transition_to_library(self):
        """Handles the initial app setup and ensures we reach the library view"""
        return self.state_machine.transition_to_library()

    def ensure_driver_running(self):
        """Ensure the driver is healthy and running, reinitialize if needed."""
        try:
            if not self.driver:
                logger.info("Driver not initialized - initializing now")
                return self.initialize_driver()

            # Basic health check - try to get current activity
            try:
                # Try a simple operation to verify UiAutomator2 is responsive
                try:
                    self.driver.current_activity
                except Exception as activity_error:
                    # Check specifically for UiAutomator2 crash indicators
                    error_message = str(activity_error)
                    if (
                        "instrumentation process is not running" in error_message
                        or "UiAutomator2 server" in error_message
                        or "An unknown server-side error occurred" in error_message
                    ):
                        logger.error(f"UiAutomator2 server crashed: {error_message}", exc_info=True)
                        raise activity_error

                # Quick check for app not responding dialog without full state determination
                if self.state_machine:
                    try:
                        # Just check for the specific dialog elements
                        from views.common.dialog_strategies import (
                            APP_NOT_RESPONDING_DIALOG_IDENTIFIERS,
                        )

                        for strategy, locator in APP_NOT_RESPONDING_DIALOG_IDENTIFIERS:
                            try:
                                element = self.driver.find_element(strategy, locator)
                                if element.is_displayed():
                                    logger.info("Detected app not responding dialog - handling it")
                                    # Get the handler for APP_NOT_RESPONDING state
                                    handler = self.state_machine.transitions.get_handler_for_state(
                                        AppState.APP_NOT_RESPONDING
                                    )
                                    if handler:
                                        result = handler()
                                        if result:
                                            logger.info("Successfully handled app not responding state")
                                            return True
                                    # If handler failed, reinitialize
                                    logger.error(
                                        "Failed to handle app not responding state, reinitializing driver"
                                    )
                                    self.cleanup()
                                    return self.initialize_driver()
                            except Exception:
                                # Element not found, continue checking
                                continue
                    except Exception as e:
                        logger.debug(f"Error checking for app not responding dialog: {e}")

                # Try checking app activity
                try:
                    current_activity = self.driver.current_activity
                    # If we're not in the Kindle app, try to relaunch it
                    if not current_activity.startswith("com.amazon"):
                        logger.warning("App is not in Kindle foreground, trying to relaunch")
                        if hasattr(self.state_machine, "view_inspector") and hasattr(
                            self.state_machine.view_inspector, "ensure_app_foreground"
                        ):
                            self.state_machine.view_inspector.ensure_app_foreground()
                            logger.info("Relaunched Kindle app")
                except Exception as e:
                    logger.warning(f"Failed to check current activity: {e}")
                    # Continue anyway, the app might still be usable

                return True
            except Exception as e:
                logger.error(f"Driver is unhealthy ({e}, exc_info=True), reinitializing...")
                # Clean up the old driver
                self.cleanup()
                # Tell the middleware that Appium may need to be restarted
                if "instrumentation process is not running" in str(e) or "UiAutomator2 server" in str(e):
                    logger.critical("UiAutomator2 crash detected - Appium server needs restarting")
                return self.initialize_driver()
        except Exception as outer_e:
            logger.error(f"Unexpected error in ensure_driver_running: {outer_e}", exc_info=True)
            self.cleanup()
            return False

    # Removed update_credentials method - no longer needed

    def restart_kindle_app(self):
        """Restart the Kindle app to return to sign-in state"""
        logger.info("Restarting Kindle app to return to sign-in state")
        try:
            # Check if driver is active
            if not self.driver:
                logger.warning("No driver available to restart app - reinitializing driver")
                if self.initialize_driver():
                    logger.info("Successfully initialized driver for app restart")
                else:
                    logger.error("Failed to initialize driver for app restart", exc_info=True)
                    return False

            # Force stop the app more reliably with ADB command
            try:
                if self.device_id:
                    logger.info(f"Force stopping Kindle app with ADB on device {self.device_id}")
                    subprocess.run(
                        ["adb", "-s", self.device_id, "shell", "am", "force-stop", "com.amazon.kindle"],
                        check=False,
                        timeout=5,
                    )
                    time.sleep(1)
            except Exception as adb_error:
                logger.warning(f"Error using ADB to stop app: {adb_error}. Falling back to driver method.")

            # Stop the app using driver method as backup
            try:
                self.driver.terminate_app("com.amazon.kindle")
                time.sleep(1)
            except Exception as driver_error:
                logger.warning(f"Error using driver to terminate app: {driver_error}")

            # Start the app again using driver method
            try:
                self.driver.activate_app("com.amazon.kindle")
                logger.info("Activated Kindle app with driver method")
            except Exception as activate_error:
                logger.warning(f"Error using driver to activate app: {activate_error}. Trying ADB method.")
                # Try ADB method as fallback
                if self.device_id:
                    try:
                        subprocess.run(
                            [
                                "adb",
                                "-s",
                                self.device_id,
                                "shell",
                                "am",
                                "start",
                                "-n",
                                "com.amazon.kindle/com.amazon.kindle.UpgradePage",
                            ],
                            check=False,
                            timeout=5,
                        )
                        logger.info("Started Kindle app with ADB fallback method")
                    except Exception as adb_start_error:
                        logger.error(f"Error using ADB to start app: {adb_start_error}", exc_info=True)
                        return False

            # Wait for app to initialize
            time.sleep(3)

            # Update the state machine
            if self.state_machine:
                self.state_machine.update_current_state()

            logger.info(
                f"App restart completed, current state: {self.state_machine.current_state if self.state_machine else 'unknown'}"
            )
            return True
        except Exception as e:
            logger.error(f"Error restarting Kindle app: {e}", exc_info=True)
            return False

    # Keep original method for backward compatibility
    def restart_app(self):
        """Restart the Kindle app (alias for restart_kindle_app)"""
        return self.restart_kindle_app()

    def take_secure_screenshot(self, output_path=None, force_secure=False):
        """Wrapper method for backward compatibility with take_secure_screenshot.

        Delegates to the utility function in screenshot_utils.py

        Args:
            output_path (str, optional): Path to save the screenshot.
            force_secure (bool, optional): If True, always use scrcpy method.

        Returns:
            str: Path to the saved screenshot or None if screenshot failed
        """
        # Get current state for the screenshot method selection
        current_state = None
        if hasattr(self, "state_machine") and self.state_machine:
            current_state = self.state_machine.current_state

        return take_secure_screenshot(
            device_id=self.device_id,
            output_path=output_path,
            screenshots_dir=self.screenshots_dir,
            force_secure=force_secure,
            current_state=current_state,
        )
