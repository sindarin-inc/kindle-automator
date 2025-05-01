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
from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler
from views.core.app_state import AppState
from views.state_machine import KindleStateMachine

logger = logging.getLogger(__name__)


class KindleAutomator:
    def __init__(self):
        self.captcha_solution = None
        self.driver = None
        self.state_machine = None
        self.device_id = None  # Will be set during initialization
        self.library_handler = None
        self.reader_handler = None
        self.profile_manager = None  # Will be set by server.py
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def cleanup(self):
        """Cleanup resources."""
        if self.driver:
            Driver.reset()  # This will allow reinitialization
            self.driver = None
            self.device_id = None

    def initialize_driver(self):
        """Initialize the Appium driver and Kindle app."""
        # Create and initialize driver
        driver = Driver()
        # Set the automator reference in the driver
        driver.automator = self

        if not driver.initialize():
            return False

        self.driver = driver.get_driver()
        self.device_id = driver.get_device_id()

        # Make sure the driver instance also has a reference to this automator
        # This ensures auth_handler can access it
        if self.driver and not hasattr(self.driver, "automator"):
            logger.info("Setting automator reference directly on driver object")
            self.driver.automator = self

        # Initialize state machine without credentials or captcha
        self.state_machine = KindleStateMachine(self.driver)

        # Initialize handlers
        self.library_handler = LibraryHandler(self.driver)
        self.reader_handler = ReaderHandler(self.driver)

        # Set the profile_manager reference in the reader handler
        # This allows it to access the correct profile manager to save style preferences
        if hasattr(self, "profile_manager") and self.profile_manager:
            self.reader_handler.profile_manager = self.profile_manager

        # Verify app is in foreground - sometimes it quits after driver connects
        try:
            current_activity = self.driver.current_activity
            logger.info(f"After driver initialization, current activity: {current_activity}")

            # If we're not in the Kindle app, try to relaunch it
            # Check for both com.amazon.kindle and com.amazon.kcp activities (both are valid Kindle app activities)
            # Also accept the Google Play review dialog which can appear over the Kindle app
            if not (
                current_activity.startswith("com.amazon.kindle")
                or current_activity.startswith("com.amazon.kcp")
                or current_activity == "com.google.android.finsky.inappreviewdialog.InAppReviewActivity"
            ):
                logger.warning("App is not in foreground after initialization, trying to launch it")
                if self.state_machine.view_inspector.ensure_app_foreground():
                    logger.info("Successfully launched Kindle app after initialization")

                    # Verify we're back in the app
                    current_activity = self.driver.current_activity
                    logger.info(f"New current activity after relaunch: {current_activity}")
                    if not (
                        current_activity.startswith("com.amazon.kindle")
                        or current_activity.startswith("com.amazon.kcp")
                        or current_activity
                        == "com.google.android.finsky.inappreviewdialog.InAppReviewActivity"
                    ):
                        logger.error("Failed to bring Kindle app to foreground after relaunch attempt")
                        return False
        except Exception as e:
            logger.error(f"Error checking app state after initialization: {e}")
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
                    logger.info("Driver activity check passed")
                except Exception as activity_error:
                    # Check specifically for UiAutomator2 crash indicators
                    error_message = str(activity_error)
                    if (
                        "instrumentation process is not running" in error_message
                        or "UiAutomator2 server" in error_message
                        or "An unknown server-side error occurred" in error_message
                    ):
                        logger.error(f"UiAutomator2 server crashed: {error_message}")
                        raise activity_error

                # Additional check - try to get window size
                try:
                    window_size = self.driver.get_window_size()
                    logger.info(f"Driver window size check passed: {window_size}")
                except Exception as window_error:
                    # Check specifically for UiAutomator2 crash indicators
                    error_message = str(window_error)
                    if (
                        "instrumentation process is not running" in error_message
                        or "UiAutomator2 server" in error_message
                        or "An unknown server-side error occurred" in error_message
                    ):
                        logger.error(f"UiAutomator2 server crashed during window size check: {error_message}")
                        raise window_error

                logger.info("Driver is healthy")

                # Check if we're in the app not responding state
                if self.state_machine:
                    # Skip the diagnostic page source dump here since it's redundant
                    current_state = self.state_machine.update_current_state()
                    if current_state == AppState.APP_NOT_RESPONDING:
                        logger.info("Detected app not responding dialog - restarting app")
                        # Handle the app not responding state by using the appropriate handler
                        handler = self.state_machine.transitions.get_handler_for_state(current_state)
                        if handler:
                            result = handler()
                            if result:
                                logger.info("Successfully handled app not responding state")
                                return True
                            else:
                                logger.error(
                                    "Failed to handle app not responding state, reinitializing driver"
                                )
                                self.cleanup()
                                return self.initialize_driver()

                # Try checking app activity
                try:
                    current_activity = self.driver.current_activity
                    logger.info(f"Current activity check: {current_activity}")
                    # If we're not in the Kindle app, try to relaunch it
                    if not (
                        current_activity.startswith("com.amazon.kindle")
                        or current_activity.startswith("com.amazon.kcp")
                    ):
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
                logger.error(f"Driver is unhealthy ({e}), reinitializing...")
                # Clean up the old driver
                self.cleanup()
                # Tell the middleware that Appium may need to be restarted
                if "instrumentation process is not running" in str(e) or "UiAutomator2 server" in str(e):
                    logger.critical("UiAutomator2 crash detected - Appium server needs restarting")
                return self.initialize_driver()
        except Exception as outer_e:
            logger.error(f"Unexpected error in ensure_driver_running: {outer_e}")
            self.cleanup()
            return False

    def update_captcha_solution(self, solution):
        """Update captcha solution across all components if different.

        Args:
            solution: The new captcha solution to set

        Returns:
            bool: True if solution was updated (was different), False otherwise
        """
        if solution != self.captcha_solution:
            logger.info("Updating captcha solution")
            self.captcha_solution = solution
            if self.state_machine:
                self.state_machine.auth_handler.captcha_solution = solution
            return True
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
                    logger.error("Failed to initialize driver for app restart")
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
                        logger.error(f"Error using ADB to start app: {adb_start_error}")
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
            logger.error(f"Error restarting Kindle app: {e}")
            return False

    # Keep original method for backward compatibility
    def restart_app(self):
        """Restart the Kindle app (alias for restart_kindle_app)"""
        return self.restart_kindle_app()

    def take_secure_screenshot(self, output_path=None, force_secure=False):
        """Take screenshot directly with multiple methods for FLAG_SECURE screens.

        This method uses different approaches depending on the current state:
        1. For auth screens (FLAG_SECURE): scrcpy with video capture
        2. For library/reading: Use faster ADB screencap

        Args:
            output_path (str, optional): Path to save the screenshot. If None,
                                        a path in the screenshots directory is generated.
            force_secure (bool, optional): If True, always use scrcpy method even for
                                        non-auth screens. Useful for captcha handling.

        Returns:
            str: Path to the saved screenshot or None if screenshot failed
        """
        try:
            if output_path is None:
                # Generate a filename if none provided
                filename = f"secure_screenshot_{int(time.time())}.png"
                output_path = os.path.join(self.screenshots_dir, filename)

            logger.info(f"Taking screenshot, saving to {output_path}")

            # Check if we're in a state that needs secure screenshot (FLAG_SECURE)
            # or if we can use the faster ADB method
            needs_secure = force_secure  # Honor force_secure parameter
            if not needs_secure and hasattr(self, "state_machine") and self.state_machine:
                current_state = self.state_machine.current_state
                auth_states = [
                    AppState.SIGN_IN,
                    AppState.CAPTCHA,
                    AppState.SIGN_IN_PASSWORD,
                    AppState.UNKNOWN,
                ]
                needs_secure = current_state in auth_states

            if not needs_secure:
                # Fast path: Use direct ADB screenshot for non-FLAG_SECURE screens
                logger.info("Using fast ADB screenshot for non-secure screen")
                try:
                    # Direct ADB screencap method - much faster
                    cmd = f"adb -s {self.device_id} exec-out screencap -p > {output_path}"
                    subprocess.run(cmd, shell=True, timeout=5, check=True)

                    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                        logger.info(f"Screenshot saved to {output_path} using fast ADB method")
                        return output_path
                    else:
                        logger.warning("Fast ADB screenshot failed or produced empty file")
                except Exception as e:
                    logger.error(f"Error with fast ADB screenshot: {e}")
                    # Fall through to slower methods

            # Slow path: Use scrcpy for FLAG_SECURE screens
            try:
                logger.info("Trying scrcpy video capture for FLAG_SECURE...")
                # First, set up a more compatible environment
                subprocess.run(
                    f"adb -s {self.device_id} shell settings put global window_animation_scale 0.0",
                    shell=True,
                    check=False,
                )
                subprocess.run(
                    f"adb -s {self.device_id} shell settings put global transition_animation_scale 0.0",
                    shell=True,
                    check=False,
                )
                subprocess.run(
                    f"adb -s {self.device_id} shell settings put global animator_duration_scale 0.0",
                    shell=True,
                    check=False,
                )
                # Use temp video file for scrcpy capture
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
                    video_path = temp_file.name

                    # Use simplified scrcpy 3.1 parameters for FLAG_SECURE
                    # Get absolute path to scrcpy
                    scrcpy_path = subprocess.check_output(["which", "scrcpy"], text=True).strip()
                    logger.info(f"Using scrcpy at: {scrcpy_path}")

                    # Set up environment to ensure proper execution
                    env = os.environ.copy()
                    # Add Homebrew paths if they're not already in PATH
                    brew_path = "/opt/homebrew/bin"
                    if brew_path not in env.get("PATH", ""):
                        env["PATH"] = f"{brew_path}:{env.get('PATH', '')}"
                    logger.info(f"Using PATH: {env['PATH']}")

                    # Define scrcpy command with minimal parameters
                    # Check if scrcpy version supports --no-playback
                    try:
                        has_no_playback = "--no-playback" in subprocess.check_output(
                            [scrcpy_path, "--help"], stderr=subprocess.STDOUT, text=True
                        )
                    except Exception:
                        has_no_playback = False

                    scrcpy_cmd = [
                        scrcpy_path,
                        "-s",
                        self.device_id,
                    ]

                    # Only add --no-playback if supported
                    if has_no_playback:
                        scrcpy_cmd.append("--no-playback")  # For scrcpy 3.1+

                    scrcpy_cmd.extend(
                        [
                            "--record",
                            video_path,  # Record as video
                            "--no-audio",  # No audio needed
                            "--turn-screen-off",  # Critical for FLAG_SECURE
                        ]
                    )

                    logger.info(f"Running scrcpy command: {' '.join(scrcpy_cmd)}")
                    process = subprocess.Popen(
                        scrcpy_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
                    )

                    # Wait for scrcpy to capture the video
                    time.sleep(5)
                    process.terminate()

                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass

                    # Capture and log output
                    stdout, stderr = process.communicate()
                    # if stdout:
                    #     logger.info(f"scrcpy stdout: {stdout}")
                    if stderr:
                        logger.info(f"scrcpy stderr: {stderr}")

                    # Extract first frame from video if video was created
                    if os.path.exists(video_path):
                        logger.info(
                            f"Checking video file: {video_path}, size: {os.path.getsize(video_path)} bytes"
                        )

                        if os.path.getsize(video_path) > 1000:
                            logger.info("Video captured, extracting first frame with ffmpeg...")
                            # Extract first frame as image using ffmpeg
                            try:
                                # Ensure we have enough time to read the video file
                                time.sleep(0.5)

                                # Get full paths to ensure correct execution
                                ffmpeg_path = subprocess.check_output(["which", "ffmpeg"], text=True).strip()
                                logger.info(f"Using ffmpeg at: {ffmpeg_path}")

                                # Extract the first frame
                                ffmpeg_cmd = [
                                    ffmpeg_path,
                                    "-i",
                                    video_path,
                                    "-frames:v",
                                    "1",
                                    "-y",  # Overwrite output file if it exists
                                    output_path,
                                ]

                                # Run with more detailed output and the same environment
                                result = subprocess.run(
                                    ffmpeg_cmd,
                                    check=False,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    env=env,
                                )

                                # logger.info(f"ffmpeg stdout: {result.stdout}")
                                # logger.info(f"ffmpeg stderr: {result.stderr}")

                                # Check if image extraction succeeded
                                if os.path.exists(output_path):
                                    logger.info(
                                        f"Output file created: {output_path}, size: {os.path.getsize(output_path)} bytes"
                                    )
                                    if os.path.getsize(output_path) > 1000:
                                        logger.info(
                                            f"Screenshot saved to {output_path} using scrcpy with ffmpeg extraction"
                                        )
                                        # Clean up temp file
                                        os.unlink(video_path)
                                        return output_path
                                    else:
                                        logger.error(
                                            f"Output file too small: {os.path.getsize(output_path)} bytes"
                                        )
                                else:
                                    logger.error(f"Output file was not created: {output_path}")
                            except Exception as e:
                                logger.error(f"ffmpeg frame extraction failed: {e}")
                        else:
                            logger.error(f"Video file too small: {os.path.getsize(video_path)} bytes")
                    else:
                        logger.error(f"Video file not created: {video_path}")

                    # Clean up temp file if it exists
                    if os.path.exists(video_path):
                        os.unlink(video_path)
            except Exception as e:
                logger.error(f"scrcpy video method failed: {e}")

            # Method 2: Alternative scrcpy parameters
            try:
                logger.info("Trying alternative scrcpy method...")
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
                    alt_video_path = temp_file.name

                # Alternative simplified scrcpy parameters
                alt_cmd = [
                    scrcpy_path,  # Use the path we already found
                    "-s",
                    self.device_id,
                    "--no-playback",
                    "--record",
                    alt_video_path,
                    "--legacy-paste",  # Alternative mode that might help
                ]

                logger.info(f"Running alternative scrcpy command: {' '.join(alt_cmd)}")
                alt_process = subprocess.Popen(
                    alt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
                )
                time.sleep(5)
                alt_process.terminate()

                try:
                    alt_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass

                # Capture and log output
                alt_stdout, alt_stderr = alt_process.communicate()
                if alt_stdout:
                    logger.info(f"Alternative scrcpy stdout: {alt_stdout}")
                if alt_stderr:
                    logger.info(f"Alternative scrcpy stderr: {alt_stderr}")

                # Extract frame if video was captured
                if os.path.exists(alt_video_path) and os.path.getsize(alt_video_path) > 1000:
                    try:
                        # Wait to ensure the file is accessible
                        time.sleep(0.5)

                        # Extract the first frame
                        alt_ffmpeg_cmd = ["ffmpeg", "-i", alt_video_path, "-frames:v", "1", "-y", output_path]

                        alt_ffmpeg_result = subprocess.run(
                            alt_ffmpeg_cmd,
                            check=False,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            env=env,
                        )

                        # Log ffmpeg output
                        if alt_ffmpeg_result.stdout:
                            logger.info(f"Alternative ffmpeg stdout: {alt_ffmpeg_result.stdout}")
                        if alt_ffmpeg_result.stderr:
                            logger.info(f"Alternative ffmpeg stderr: {alt_ffmpeg_result.stderr}")

                        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                            logger.info(f"Screenshot saved to {output_path} using alternative scrcpy method")
                            os.unlink(alt_video_path)
                            return output_path
                    except Exception as inner_e:
                        logger.error(f"Alternative ffmpeg extraction failed: {inner_e}")

                # Clean up temp file if it exists
                if os.path.exists(alt_video_path):
                    os.unlink(alt_video_path)
            except Exception as e:
                logger.error(f"Alternative scrcpy method failed: {e}")

            # Method 3: Direct ADB exec-out method (fallback, likely won't work with FLAG_SECURE)
            try:
                logger.info("Trying direct adb exec-out method...")
                cmd = f"adb -s {self.device_id} exec-out screencap -p > {output_path}"
                subprocess.run(cmd, shell=True, timeout=5, check=False)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    logger.info(f"Screenshot saved to {output_path} using adb exec-out")
                    return output_path
            except Exception as e:
                logger.error(f"Direct ADB method failed: {e}")

            # Method 4: ADB temp file method (fallback, likely won't work with FLAG_SECURE)
            try:
                logger.info("Trying adb temp file method...")
                device_temp = "/data/local/tmp/screenshot.png"
                subprocess.run(
                    f"adb -s {self.device_id} shell screencap -p {device_temp}",
                    shell=True,
                    check=False,
                    timeout=5,
                )
                subprocess.run(
                    f"adb -s {self.device_id} pull {device_temp} {output_path}",
                    shell=True,
                    check=False,
                    timeout=5,
                )

                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    logger.info(f"Screenshot saved to {output_path} using adb temp file")
                    return output_path
            except Exception as e:
                logger.error(f"ADB temp file method failed: {e}")

            logger.error("All screenshot methods failed")
            return None

        except Exception as e:
            logger.error(f"Error taking secure screenshot: {e}")
            return None
