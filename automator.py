import argparse
import logging
import os
import subprocess
import tempfile
import time
import traceback

from driver import Driver
from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler
from views.state_machine import AppState, KindleStateMachine

logger = logging.getLogger(__name__)


class KindleAutomator:
    def __init__(self):
        self.email = None
        self.password = None
        self.captcha_solution = None
        self.driver = None
        self.state_machine = None
        self.device_id = None  # Will be set during initialization
        self.library_handler = None
        self.reader_handler = None
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

        # Initialize state machine without credentials or captcha
        self.state_machine = KindleStateMachine(self.driver)

        # Initialize handlers
        self.library_handler = LibraryHandler(self.driver)
        self.reader_handler = ReaderHandler(self.driver)

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

    def transition_to_library(self):
        """Handles the initial app setup and ensures we reach the library view"""
        return self.state_machine.transition_to_library()

    def ensure_driver_running(self):
        """Ensure the driver is healthy and running, reinitialize if needed."""
        try:
            if not self.driver:
                # Test if driver is still connected
                try:
                    self.driver.current_activity
                except Exception as e:
                    logger.info("Driver not connected - reinitializing")
                    self.cleanup()
                    return self.initialize_driver()
                else:
                    logger.info("Driver already initialized")

            # Basic health check - try to get current activity
            try:
                self.driver.current_activity
                logger.info("Driver is healthy")
                return True
            except Exception as e:
                logger.info(f"Driver is unhealthy ({e}), reinitializing...")
                self.cleanup()  # Clean up old driver
                return self.initialize_driver()

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error ensuring driver is running: {e}")
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

    def update_credentials(self, email, password):
        """Update user credentials in the automator and state machine.

        Args:
            email: The Amazon account email
            password: The Amazon account password
        """
        logger.info(f"Updating credentials for email: {email}")
        self.email = email
        self.password = password
        if self.state_machine and self.state_machine.auth_handler:
            self.state_machine.auth_handler.email = email
            self.state_machine.auth_handler.password = password
            
    def take_secure_screenshot(self, output_path=None):
        """Take screenshot using scrcpy for screens with FLAG_SECURE.
        
        This is used for screens like authentication and CAPTCHA where
        normal screenshot methods are blocked by Android security.
        
        Args:
            output_path (str, optional): Path to save the screenshot. If None, 
                                        a path in the screenshots directory is generated.
        
        Returns:
            str: Path to the saved screenshot or None if screenshot failed
        """
        try:
            if output_path is None:
                # Generate a filename if none provided
                filename = f"secure_screenshot_{int(time.time())}.png"
                output_path = os.path.join(self.screenshots_dir, filename)
                
            logger.info(f"Taking secure screenshot using scrcpy, saving to {output_path}")
            
            # Create a temporary file for the screenshot
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                temp_path = temp_file.name
            
            # Use scrcpy to capture a screenshot
            # The -s parameter specifies the device ID
            cmd = ["scrcpy", 
                   "-s", self.device_id, 
                   "--no-display", 
                   "--record", temp_path, 
                   "--record-format", "image",
                   "--max-fps", "1",
                   "--no-audio",
                   "--max-size", "1280"]
            
            # Execute the command with a short timeout
            process = subprocess.Popen(cmd, 
                                    stdout=subprocess.PIPE, 
                                    stderr=subprocess.PIPE)
            
            # Wait for a short time then terminate the process
            # This is because scrcpy doesn't have a built-in "take one screenshot and exit" option
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                
            # Copy the temp screenshot to the desired location
            if os.path.exists(temp_path):
                if os.path.getsize(temp_path) > 0:  # Ensure the file is not empty
                    subprocess.run(["cp", temp_path, output_path])
                    os.unlink(temp_path)  # Remove the temp file
                    logger.info(f"Secure screenshot saved to {output_path}")
                    return output_path
                else:
                    logger.error("Scrcpy created an empty screenshot file")
                    os.unlink(temp_path)
                    return None
            else:
                logger.error("Failed to create scrcpy screenshot")
                return None
                
        except Exception as e:
            logger.error(f"Error taking secure screenshot: {e}")
            return None
