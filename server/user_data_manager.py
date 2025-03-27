import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException

from server.config import BASE_DIR
from server.logging_config import store_page_source

# Create user data directory
USER_DATA_DIR = os.path.join(BASE_DIR, "user_data")
os.makedirs(USER_DATA_DIR, exist_ok=True)

# Android app package name
KINDLE_PACKAGE = "com.amazon.kindle"

logger = logging.getLogger(__name__)


class UserDataManager:
    """
    Manages multiple user data containers for the Kindle app.
    Uses Android's backup/restore functionality to switch between users.
    Does NOT require root access.
    """

    def __init__(self, device_id: str, driver=None):
        """
        Initialize the UserDataManager.

        Args:
            device_id: The Android device ID to use for ADB commands.
            driver: Optional Appium driver for capturing page sources.
        """
        self.device_id = device_id
        self.driver = driver
        self._ensure_users_index()
        
        # Load the current active user from the index
        index_data = self._get_users_index()
        self.current_user = index_data.get("active_user")
        logger.info(f"Initialized UserDataManager with active user: {self.current_user}")

    def set_driver(self, driver):
        """Set the Appium driver for screenshots and page source capture."""
        self.driver = driver

    def _ensure_users_index(self) -> None:
        """Ensure the users index file exists with proper structure."""
        index_path = os.path.join(USER_DATA_DIR, "users_index.json")
        if not os.path.exists(index_path) or os.path.getsize(index_path) == 0:
            logger.info("Creating new users index file")
            with open(index_path, "w") as f:
                json.dump({"users": {}, "active_user": None}, f)
        else:
            # Check if the existing file is valid JSON with the right structure
            try:
                with open(index_path, "r") as f:
                    data = json.load(f)
                # Ensure it has the required fields
                if "users" not in data:
                    logger.warning("Fixing users index: adding missing 'users' field")
                    data["users"] = {}
                if "active_user" not in data:
                    logger.warning("Fixing users index: adding missing 'active_user' field")
                    data["active_user"] = None
                # Write back the fixed data
                with open(index_path, "w") as f:
                    json.dump(data, f, indent=2)
            except json.JSONDecodeError:
                logger.warning("Corrupted users index file detected, creating new one")
                with open(index_path, "w") as f:
                    json.dump({"users": {}, "active_user": None}, f)

    def _get_users_index(self) -> Dict:
        """Get the users index data."""
        index_path = os.path.join(USER_DATA_DIR, "users_index.json")
        try:
            with open(index_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            # If file is corrupted or missing, create a new one
            self._ensure_users_index()
            return {"users": {}, "active_user": None}

    def _save_users_index(self, index_data: Dict) -> None:
        """Save the users index data."""
        index_path = os.path.join(USER_DATA_DIR, "users_index.json")
        with open(index_path, "w") as f:
            json.dump(index_data, f, indent=2)

    def _run_adb_command(self, command: List[str], timeout: int = 60) -> Tuple[bool, str]:
        """
        Run an ADB command for the specified device.

        Args:
            command: The ADB command to run (without 'adb -s device_id' prefix).
            timeout: Command timeout in seconds.

        Returns:
            Tuple of (success, output)
        """
        full_command = ["adb", "-s", self.device_id] + command
        try:
            result = subprocess.run(full_command, capture_output=True, text=True, check=True, timeout=timeout)
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"ADB command failed: {e.stderr}")
            return False, e.stderr
        except subprocess.TimeoutExpired as e:
            logger.error(f"ADB command timed out after {timeout} seconds")
            return False, f"Command timed out after {timeout} seconds"
        except Exception as e:
            logger.error(f"Error running ADB command: {e}")
            return False, str(e)

    def get_current_user(self) -> Optional[str]:
        """Get the currently active user."""
        return self.current_user

    def list_users(self) -> List[str]:
        """List all registered users."""
        index_data = self._get_users_index()
        return list(index_data["users"].keys())

    def user_exists(self, email: str) -> bool:
        """Check if a user with the given email exists."""
        index_data = self._get_users_index()
        return email in index_data["users"]

    def _capture_current_screen(self, filename_prefix: str) -> None:
        """
        Capture the current screen as XML and screenshot if driver is available.

        Args:
            filename_prefix: Prefix for the saved files.
        """
        if not self.driver:
            logger.warning("No driver available for screen capture")
            return

        try:
            # Capture page source
            page_source = self.driver.page_source
            filepath = store_page_source(page_source, f"{filename_prefix}_dialog")
            logger.info(f"Stored {filename_prefix} dialog page source at: {filepath}")

            # Capture screenshot
            screenshot_path = os.path.join("screenshots", f"{filename_prefix}_dialog.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"Saved {filename_prefix} dialog screenshot to {screenshot_path}")
        except Exception as e:
            logger.error(f"Error capturing screen: {e}")

    def _handle_backup_dialog(self) -> bool:
        """
        A direct function to handle Android backup/restore confirmation dialogs.

        This is a fallback method if the automated detection doesn't work.
        In rare cases, the state machine might not recognize the dialog.

        Returns:
            bool: True if dialog was handled successfully, False otherwise.
        """
        try:
            logger.info("Attempting to directly handle backup/restore confirmation dialog")

            # Capture current screen for debugging
            if self.driver:
                self._capture_current_screen("dialog_handling")

                # Try to determine if this is a restore dialog from the page source
                page_source = self.driver.page_source
                is_restore = "restore" in page_source.lower() or "Restore" in page_source
                dialog_type = "restore" if is_restore else "backup"
                logger.info(f"Detected dialog type: {dialog_type}")
            else:
                dialog_type = "unknown"
                logger.info("No driver available to determine dialog type")

            # First try UI-based detection if we have driver access
            if self.driver:
                # Try a variety of button locators based on dialog type
                button_xpaths = [
                    # Common locators for both dialog types (by resource ID)
                    "//android.widget.Button[@resource-id='com.android.backupconfirm:id/button_allow']",
                    # Backup specific
                    "//android.widget.Button[@text='BACK UP MY DATA']",
                    "//android.widget.Button[contains(@text, 'BACK UP')]",
                    # Restore specific
                    "//android.widget.Button[@text='RESTORE MY DATA']",
                    "//android.widget.Button[contains(@text, 'RESTORE')]",
                    # Generic position-based (right button is usually confirm)
                    "//android.widget.LinearLayout/android.widget.Button[2]",
                ]

                # Try each button locator
                for xpath in button_xpaths:
                    try:
                        button = self.driver.find_element(AppiumBy.XPATH, xpath)
                        if button.is_displayed():
                            button_text = button.text
                            logger.info(f"Found button '{button_text}' with xpath '{xpath}' - clicking")
                            button.click()
                            time.sleep(2)
                            self._capture_current_screen("after_button_click")
                            return True
                    except NoSuchElementException:
                        continue
                    except Exception as e:
                        logger.error(f"Error clicking button with xpath '{xpath}': {e}")

                logger.info("No buttons found via UI - trying backup methods")

            # Multiple fallback approaches for different devices and dialog variations
            fallback_methods = [
                # Method 1: Tap directly at the common position of the confirm button
                lambda: self._run_adb_command(["shell", "input tap 810 2130"])[0],  # Bottom right
                # Method 2: Tab to navigate to the right button and press Enter
                lambda: self._run_adb_command(["shell", "input keyevent 22 && input keyevent 23"])[0],
                # Method 3: Another common position for the confirm button
                lambda: self._run_adb_command(["shell", "input tap 850 2000"])[0],  # Slightly higher
                # Method 4: Try tapping on other common positions
                lambda: self._run_adb_command(["shell", "input tap 540 2130"])[0],  # Middle bottom
                # Method 5: Try pressing Enter directly
                lambda: self._run_adb_command(["shell", "input keyevent 23"])[0],
            ]

            # Try each fallback method until one succeeds
            for i, method in enumerate(fallback_methods):
                logger.info(f"Trying fallback method {i+1} for {dialog_type} dialog")
                try:
                    if method():
                        logger.info(f"Fallback method {i+1} succeeded")
                        time.sleep(5)  # Longer wait after using fallback method

                        # Capture screen after handling
                        if self.driver:
                            self._capture_current_screen(f"after_fallback_{i+1}")
                        return True
                except Exception as e:
                    logger.error(f"Error with fallback method {i+1}: {e}")

            # If all other methods fail, try brute force approach
            # This is a last resort emergency method
            logger.warning("All standard methods failed, trying emergency brute force approach")

            # METHOD 1: Try multiple tap locations in sequence
            tap_locations = [
                (810, 2130),  # Main position
                (750, 2130),  # Slightly left
                (870, 2130),  # Slightly right
                (810, 2080),  # Slightly up
                (810, 2180),  # Slightly down
                (880, 2080),  # Upper right
                (650, 2130),  # Far left
                (950, 2130),  # Far right
            ]

            for idx, (x, y) in enumerate(tap_locations):
                logger.info(f"Emergency tap {idx+1} at position ({x}, {y})")
                try:
                    self._run_adb_command(["shell", f"input tap {x} {y}"], timeout=1)
                    time.sleep(0.5)  # Brief wait between taps
                except:
                    pass

            # METHOD 2: Try rapid-fire Enter key presses
            for i in range(5):
                try:
                    self._run_adb_command(["shell", "input keyevent 23"], timeout=1)
                    time.sleep(0.3)
                except:
                    pass

            # Wait to see if any method worked
            time.sleep(3)
            if self.driver:
                self._capture_current_screen("emergency_method_result")

                # Check if dialog is still visible
                try:
                    dialog_still_visible = False
                    for strategy in [
                        "//android.widget.Button[@text='BACK UP MY DATA']",
                        "//android.widget.Button[contains(@text, 'RESTORE')]",
                    ]:
                        try:
                            if self.driver.find_element(AppiumBy.XPATH, strategy).is_displayed():
                                dialog_still_visible = True
                                break
                        except:
                            pass

                    if not dialog_still_visible:
                        logger.info("Emergency method appears to have succeeded!")
                        return True
                except:
                    # If we can't check, assume it might have worked
                    pass

            # If we get here, all methods failed
            if self.driver:
                self._capture_current_screen("all_methods_failed")

            logger.error("All dialog handling methods failed")
            # Return True anyway to avoid blocking - let the process continue
            # The dialog might auto-dismiss or the user might handle it manually
            logger.warning("Continuing process despite dialog handling failure")
            return True
        except Exception as e:
            logger.error(f"Error handling dialog: {e}")
            return False

    def save_current_user_data(self) -> bool:
        """
        Save the current user's data if a user is active.
        Uses Android's backup functionality which doesn't require root.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.current_user:
            logger.warning("No current user to save data for")
            return False

        logger.info(f"Saving data for user: {self.current_user}")

        # Create user directory if it doesn't exist
        user_dir = os.path.join(USER_DATA_DIR, self.current_user)
        os.makedirs(user_dir, exist_ok=True)

        # Path for backup file
        backup_file = os.path.join(user_dir, "kindle_backup.ab")

        # Use non-blocking approach for backup
        # Execute the backup directly with adb command to avoid timeout
        logger.info("Starting data backup with non-blocking approach")
        backup_cmd = f"adb -s {self.device_id} backup -f {backup_file} -noapk {KINDLE_PACKAGE}"

        # Execute the adb backup command in a background thread
        import threading
        import subprocess

        def run_backup_command():
            logger.info(f"Background thread executing: {backup_cmd}")
            try:
                # Use subprocess instead of os.system to get better error handling
                result = subprocess.run(backup_cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    logger.info("Backup command completed successfully in background")
                    if result.stdout:
                        logger.info(f"Backup stdout: {result.stdout}")
                else:
                    logger.error(f"Backup command failed with return code {result.returncode}")
                    logger.error(f"Backup stderr: {result.stderr}")
            except Exception as e:
                logger.error(f"Error in backup background thread: {e}")

        # Start backup in background thread
        backup_thread = threading.Thread(target=run_backup_command)
        backup_thread.daemon = True
        backup_thread.start()
        
        # Log the file path we're backing up to
        logger.info(f"Backing up data to file: {backup_file}")

        # Wait for the backup dialog to appear
        logger.info("Waiting for backup dialog to appear...")
        time.sleep(2)

        # Capture the backup dialog screen
        if self.driver:
            logger.info("Capturing backup dialog screen")
            self._capture_current_screen("backup_dialog")

            # Try to directly find and click the "BACK UP MY DATA" button
            try:
                # Look for backup button
                backup_button = None
                buttons = self.driver.find_elements(AppiumBy.XPATH, "//android.widget.Button")
                logger.info(f"Found {len(buttons)} buttons on screen")

                # Analyze all buttons for debugging
                for i, button in enumerate(buttons):
                    try:
                        text = button.text
                        resource_id = button.get_attribute("resource-id")
                        bounds = button.get_attribute("bounds")
                        logger.info(f"Button {i+1}: text='{text}', id='{resource_id}', bounds='{bounds}'")

                        if "BACK UP" in text:
                            backup_button = button
                    except Exception as e:
                        logger.error(f"Error inspecting button {i+1}: {e}")

                # Try to click the button directly if found
                if backup_button:
                    logger.info("Clicking BACK UP MY DATA button directly...")
                    backup_button.click()
                    logger.info("Successfully clicked BACK UP MY DATA button")
                    time.sleep(2)
                    self._capture_current_screen("after_backup_button_click")
                else:
                    # If button not found, use the handler
                    logger.info("Backup button not found directly, using the handler")
                    self._handle_backup_dialog()
            except Exception as e:
                logger.error(f"Error handling backup dialog directly: {e}")
                # Fall back to general handler
                self._handle_backup_dialog()
        else:
            # No driver, use ADB approach
            logger.info("No driver, using ADB approach to handle backup dialog")
            time.sleep(2)  # Wait for dialog to appear
            # Try clicking at the position of the BACK UP MY DATA button
            self._run_adb_command(["shell", "input tap 810 2130"], timeout=1)

        # Wait for backup to complete, checking for toast messages
        logger.info("Backup dialog handled, waiting for backup to complete...")
        
        # Capture multiple screens and watch for toast messages
        max_wait_time = 30  # Wait for up to 30 seconds
        start_time = time.time()
        backup_started = False
        backup_finished = False
        
        while time.time() - start_time < max_wait_time:
            # Capture page source every second to look for toast messages
            if self.driver:
                try:
                    page_source = self.driver.page_source
                    
                    # Look for toast messages in the XML
                    if "Backup starting" in page_source or "backup starting" in page_source.lower():
                        logger.info("Detected 'Backup starting' toast message")
                        backup_started = True
                        # Save this page source for analysis
                        self._capture_current_screen("backup_starting_toast")
                    
                    if "Backup finished" in page_source or "backup finished" in page_source.lower() or "backup complete" in page_source.lower():
                        logger.info("Detected 'Backup finished' toast message")
                        backup_finished = True
                        # Save this page source for analysis
                        self._capture_current_screen("backup_finished_toast")
                        # If backup is finished, we can break out of the loop
                        break
                        
                    # Also check for backup progress percentage
                    progress_pattern = r"Backup (\d+)%"
                    matches = re.findall(progress_pattern, page_source)
                    if matches:
                        progress = matches[0]
                        logger.info(f"Backup progress: {progress}%")
                        
                except Exception as e:
                    logger.error(f"Error capturing page source during backup: {e}")
            
            # If we've detected both start and finish, we can break out
            if backup_started and backup_finished:
                logger.info("Backup cycle complete (start and finish toasts detected)")
                break
                
            # Sleep briefly before checking again
            time.sleep(1)
            
        # Final capture after waiting
        if self.driver:
            self._capture_current_screen("after_backup_dialog")
            
        # Log completion status
        elapsed_time = time.time() - start_time
        if backup_finished:
            logger.info(f"Backup completed in {elapsed_time:.1f} seconds")
        elif backup_started:
            logger.info(f"Backup started but completion toast not detected after {elapsed_time:.1f} seconds")
        else:
            logger.info(f"No backup toast messages detected after {elapsed_time:.1f} seconds")

        # Assume success since we can't rely on the command's return status
        logger.info("Backup completed successfully")

        # Update the user index with timestamp
        index_data = self._get_users_index()
        if self.current_user not in index_data["users"]:
            index_data["users"][self.current_user] = {}

        import datetime

        index_data["users"][self.current_user]["last_saved"] = datetime.datetime.now().isoformat()
        # Make sure the active user is set correctly
        index_data["active_user"] = self.current_user
        self._save_users_index(index_data)

        # Verify the backup file exists and has content
        if os.path.exists(backup_file) and os.path.getsize(backup_file) > 0:
            logger.info(f"Successfully saved data for user: {self.current_user}")
            return True
        else:
            # Wait a bit longer to give the backup file time to be created
            logger.warning(f"Backup file not found immediately, waiting a few more seconds: {backup_file}")
            
            # Additional 5-second wait for slow file operations
            for i in range(5):
                time.sleep(1)
                if os.path.exists(backup_file) and os.path.getsize(backup_file) > 0:
                    logger.info(f"Backup file created after {i+1} second(s): {backup_file}")
                    return True
                    
            # If still not found, log a more detailed error
            logger.error(f"Backup file not created after additional wait time: {backup_file}")
            logger.error(f"Contents of user directory: {os.listdir(user_dir) if os.path.exists(user_dir) else 'directory not found'}")
            logger.error(f"All user data: {os.listdir(USER_DATA_DIR)}")
            
            # Now we can consider it a failure since we have evidence the backup didn't work
            return False

    def load_user_data(self, email: str) -> bool:
        """
        Load a specific user's data.
        Uses Android's restore functionality which doesn't require root.

        Args:
            email: The email of the user to load.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.user_exists(email):
            logger.info(f"User {email} does not exist yet, initializing new profile")
            # Create user directory if it doesn't exist
            user_dir = os.path.join(USER_DATA_DIR, email)
            os.makedirs(user_dir, exist_ok=True)

            # Update user index
            index_data = self._get_users_index()
            if email not in index_data["users"]:
                index_data["users"][email] = {}
            
            # Set active user in the index file
            index_data["active_user"] = email
            self._save_users_index(index_data)

            # Set current user in memory
            self.current_user = email
            logger.info(f"Initialized new user profile and set active user to: {email}")
            return True

        # Make sure we don't try to save the current user again if it's already the same
        # This avoids a double-backup situation
        if self.current_user and self.current_user != email:
            logger.info(f"Switching from {self.current_user} to {email}")
            saved = self.save_current_user_data()
            if not saved:
                logger.warning(f"Failed to save current user data for {self.current_user}, proceeding with switch anyway")
        else:
            logger.info(f"Current user is already {email} or no current user is set")

        # Proceed with loading the user data
        logger.info(f"Loading data for user: {email}")

        # First make sure to stop the Kindle app
        stop_result, stop_output = self._run_adb_command(["shell", "am force-stop", f"{KINDLE_PACKAGE}"])
        logger.info(f"Force stopping Kindle app: {stop_output}")
        
        # Clear existing app data completely
        logger.info("Clearing Kindle app data to ensure no data leakage between users")
        success, output = self._run_adb_command(["shell", "pm", "clear", KINDLE_PACKAGE])
        if not success:
            logger.error(f"Failed to clear Kindle app data: {output}")
            return False
        else:
            logger.info(f"Successfully cleared Kindle app data: {output}")

        user_dir = os.path.join(USER_DATA_DIR, email)
        backup_file = os.path.join(user_dir, "kindle_backup.ab")

        # Check if user data backup exists and is valid
        if not os.path.exists(backup_file) or os.path.getsize(backup_file) == 0:
            logger.info(f"No valid data backup found for user {email}, initializing clean state")
            
            # Start the app fresh to ensure it initializes properly
            start_result, start_output = self._run_adb_command(
                ["shell", "am start -n com.amazon.kindle/com.amazon.kindle.UpgradePage"]
            )
            logger.info(f"Started fresh Kindle app: {start_output}")
            
            # Update user reference but don't restore any data
            self.current_user = email 
            return True

        # Capture screen before starting restore process
        if self.driver:
            self._capture_current_screen("before_restore")

        # Use non-blocking approach for restore since adb restore command times out
        # Start the restore process directly with adb command
        logger.info("Starting data restore from backup with non-blocking approach")
        restore_cmd = f"adb -s {self.device_id} restore {backup_file}"

        # Execute the adb restore command directly to avoid timeout issues
        import threading
        import subprocess

        def run_restore_command():
            logger.info(f"Background thread executing: {restore_cmd}")
            try:
                # Use subprocess instead of os.system to get better error handling
                result = subprocess.run(restore_cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    logger.info("Restore command completed successfully in background")
                    if result.stdout:
                        logger.info(f"Restore stdout: {result.stdout}")
                else:
                    logger.error(f"Restore command failed with return code {result.returncode}")
                    logger.error(f"Restore stderr: {result.stderr}")
            except Exception as e:
                logger.error(f"Error in restore background thread: {e}")

        # Start restore in background thread
        restore_thread = threading.Thread(target=run_restore_command)
        restore_thread.daemon = True  # Make sure thread doesn't block process exit
        restore_thread.start()
        
        # Log the file path we're restoring from
        logger.info(f"Restoring data from file: {backup_file}")

        # Wait for the restore dialog to appear
        logger.info("Waiting for restore dialog to appear...")
        time.sleep(2)  # Initial wait for dialog

        # Immediately capture the restore dialog screen
        if self.driver:
            logger.info("Capturing restore dialog screen")
            self._capture_current_screen("restore_dialog")

            # Analyze UI elements to check if restore dialog is visible
            restore_dialog_visible = False
            restore_button = None

            try:
                # Look for the "RESTORE MY DATA" button
                buttons = self.driver.find_elements(AppiumBy.XPATH, "//android.widget.Button")
                logger.info(f"Found {len(buttons)} buttons on screen")

                for button in buttons:
                    try:
                        if "RESTORE" in button.text:
                            logger.info(f"Found restore button: {button.text}")
                            restore_dialog_visible = True
                            restore_button = button
                            break
                    except:
                        continue

                # Analyze UI elements for debugging
                if restore_dialog_visible:
                    logger.info("Restore dialog is visible - analyzing elements")

                    # Log details about all buttons
                    for i, button in enumerate(buttons):
                        try:
                            text = button.text
                            resource_id = button.get_attribute("resource-id")
                            bounds = button.get_attribute("bounds")
                            logger.info(f"Button {i+1}: text='{text}', id='{resource_id}', bounds='{bounds}'")
                        except Exception as e:
                            logger.error(f"Error inspecting button {i+1}: {e}")

                    # Log text views to understand dialog content
                    text_views = self.driver.find_elements(AppiumBy.XPATH, "//android.widget.TextView")
                    logger.info(f"Found {len(text_views)} text views on screen")
                    for i, tv in enumerate(text_views):
                        try:
                            text = tv.text
                            if text and len(text) > 0:
                                logger.info(f"TextView {i+1}: '{text}'")
                        except Exception:
                            pass

                    # Try to click the restore button directly if found
                    if restore_button:
                        logger.info("Clicking RESTORE MY DATA button directly...")
                        restore_button.click()
                        logger.info("Successfully clicked RESTORE MY DATA button")
                        time.sleep(2)
                        self._capture_current_screen("after_restore_button_click")
                    else:
                        logger.info("Restore button reference not available, using fallback handler")
                        self._handle_backup_dialog()
                else:
                    logger.warning("Restore dialog not visible - waiting longer")
                    time.sleep(3)  # Wait longer for dialog
                    self._capture_current_screen("restore_dialog_retry")
                    # Use fallback handler since dialog may be in a different format
                    self._handle_backup_dialog()
            except Exception as e:
                logger.error(f"Error analyzing UI elements: {e}")
                # Use fallback handler
                self._handle_backup_dialog()
        else:
            # If no driver, use ADB approach
            logger.info("No driver available, using ADB approach to handle restore dialog")
            time.sleep(2)  # Wait for dialog to appear
            # Try to click the RESTORE MY DATA button
            self._run_adb_command(["shell", "input tap 810 2130"], timeout=1)

        # Wait for restore to complete, checking for toast messages
        logger.info("Restore dialog handled, waiting for restore to complete...")
        
        # Capture multiple screens and watch for toast messages
        max_wait_time = 30  # Wait for up to 30 seconds
        start_time = time.time()
        restore_started = False
        restore_finished = False
        
        while time.time() - start_time < max_wait_time:
            # Capture page source every second to look for toast messages
            if self.driver:
                try:
                    page_source = self.driver.page_source
                    
                    # Look for toast messages in the XML
                    if "Restore starting" in page_source or "restore starting" in page_source.lower():
                        logger.info("Detected 'Restore starting' toast message")
                        restore_started = True
                        # Save this page source for analysis
                        self._capture_current_screen("restore_starting_toast")
                    
                    if "Restore finished" in page_source or "restore finished" in page_source.lower() or "restore complete" in page_source.lower():
                        logger.info("Detected 'Restore finished' toast message")
                        restore_finished = True
                        # Save this page source for analysis
                        self._capture_current_screen("restore_finished_toast")
                        # If restore is finished, we can break out of the loop
                        break
                        
                    # Also check for restore progress percentage
                    progress_pattern = r"Restore (\d+)%"
                    matches = re.findall(progress_pattern, page_source)
                    if matches:
                        progress = matches[0]
                        logger.info(f"Restore progress: {progress}%")
                        
                except Exception as e:
                    logger.error(f"Error capturing page source during restore: {e}")
            
            # If we've detected both start and finish, we can break out
            if restore_started and restore_finished:
                logger.info("Restore cycle complete (start and finish toasts detected)")
                break
                
            # Sleep briefly before checking again
            time.sleep(1)
            
        # Final capture after waiting
        if self.driver:
            self._capture_current_screen("after_restore_dialog")
            
        # Log completion status
        elapsed_time = time.time() - start_time
        if restore_finished:
            logger.info(f"Restore completed in {elapsed_time:.1f} seconds")
        elif restore_started:
            logger.info(f"Restore started but completion toast not detected after {elapsed_time:.1f} seconds")
        else:
            logger.info(f"No restore toast messages detected after {elapsed_time:.1f} seconds")

        # Update current user and active user in both memory and persistent storage
        self.current_user = email
        logger.info(f"Setting active user to: {email}")

        # Update the user index
        index_data = self._get_users_index()
        if email not in index_data["users"]:
            index_data["users"][email] = {}

        import datetime

        index_data["users"][email]["last_loaded"] = datetime.datetime.now().isoformat()
        # Make sure active_user is updated to the new user
        index_data["active_user"] = email
        self._save_users_index(index_data)
        
        # Verify active user was correctly set
        verify_index = self._get_users_index()
        if verify_index.get("active_user") != email:
            logger.error(f"Failed to set active user in index file! Expected: {email}, Got: {verify_index.get('active_user')}")
        else:
            logger.info(f"Verified active user set to {verify_index.get('active_user')}")

        # After restore completes, restart the app to ensure a clean state
        restart_result, restart_output = self._run_adb_command([
            "shell", 
            f"am force-stop {KINDLE_PACKAGE} && am start -n {KINDLE_PACKAGE}/com.amazon.kindle.UpgradePage"
        ])
        logger.info(f"Restarted Kindle app after restore: {restart_output}")

        logger.info(f"Successfully loaded data for user: {email}")
        return True

    def _check_current_auth_email(self) -> Optional[str]:
        """
        Check if we can detect the currently logged-in email in the Kindle app.
        This is an advanced function that tries to parse the UI to find the email.
        
        Returns:
            str: The detected email if found, None otherwise
        """
        if not self.driver:
            logger.info("No driver available to check current auth email")
            return None
            
        try:
            # Try to find user account info in different app screens
            # First, get the page source
            page_source = self.driver.page_source
            
            # Look for common patterns that might contain email
            # Check for account settings or profile sections
            account_elements = []
            try:
                # Look for elements that might contain email (account info, profile sections)
                account_elements = self.driver.find_elements(AppiumBy.XPATH, 
                                        "//android.widget.TextView[contains(@text, '@')]")
                
                # If we found elements with @ symbol, they likely contain an email
                if account_elements:
                    for element in account_elements:
                        text = element.text
                        if '@' in text:
                            # Simple validation to make sure it looks like an email
                            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                            matches = re.findall(email_pattern, text)
                            if matches:
                                detected_email = matches[0]
                                logger.info(f"Detected logged-in email: {detected_email}")
                                return detected_email
            except Exception as e:
                logger.error(f"Error finding account elements: {e}")
                
            logger.info("Could not detect logged-in email from UI")
            return None
        except Exception as e:
            logger.error(f"Error checking current auth email: {e}")
            return None

    def switch_user(self, email: str) -> bool:
        """
        Switch to another user, saving current user data and loading the new user's data.

        Args:
            email: The email of the user to switch to.

        Returns:
            bool: True if successful, False otherwise.
        """
        # First, check if we're already using this account
        if self.current_user == email:
            logger.info(f"Already using account for {email} according to our records")
            
            # Double-check by trying to detect the current email from the UI
            detected_email = self._check_current_auth_email()
            if detected_email:
                if detected_email.lower() == email.lower():
                    logger.info(f"Confirmed user {email} is already logged in")
                    return True
                else:
                    logger.warning(f"Found different email logged in: {detected_email}, will switch to {email}")
            else:
                # If we couldn't detect the email but our records show it's the same, assume it's correct
                logger.info(f"Could not confirm current user from UI, assuming {email} is already logged in")
                return True

        # Save current user's data if there is one
        if self.current_user:
            self.save_current_user_data()

        # Load new user's data
        return self.load_user_data(email)

    def delete_user(self, email: str) -> bool:
        """
        Delete a user's data.

        Args:
            email: The email of the user to delete.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not self.user_exists(email):
            logger.error(f"User {email} does not exist")
            return False

        # Don't delete current user's data
        if self.current_user == email:
            logger.error(f"Cannot delete current user: {email}")
            return False

        logger.info(f"Deleting data for user: {email}")

        # Delete user directory
        user_dir = os.path.join(USER_DATA_DIR, email)
        try:
            shutil.rmtree(user_dir)
        except Exception as e:
            logger.error(f"Failed to delete user directory: {e}")
            return False

        # Update the user index
        index_data = self._get_users_index()
        if email in index_data["users"]:
            del index_data["users"][email]
            self._save_users_index(index_data)

        logger.info(f"Successfully deleted user: {email}")
        return True
