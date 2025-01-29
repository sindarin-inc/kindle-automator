import argparse
import os
import socket
import subprocess
import time
from typing import Tuple, Union

from appium import webdriver
from appium.options.android import UiAutomator2Options
from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler
from views.core.logger import logger
from views.state_machine import AppState, KindleStateMachine
from driver import Driver


class KindleAutomator:
    def __init__(self, email, password, captcha_solution):
        self.email = email
        self.password = password
        self.captcha_solution = captcha_solution
        self.driver = None
        self.state_machine = None
        self.device_id = None  # Will be set during initialization
        self.library_handler = None
        self.reader_handler = None

    def cleanup(self):
        """Cleanup resources."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

    def initialize_driver(self):
        """Initialize the Appium driver and Kindle app."""
        # Create and initialize driver
        driver = Driver()
        if not driver.initialize():
            return False

        self.driver = driver.get_driver()
        self.device_id = driver.get_device_id()

        # Initialize state machine with credentials
        self.state_machine = KindleStateMachine(
            self.driver,
            email=self.email,
            password=self.password,
            captcha_solution=self.captcha_solution,
        )

        # Initialize handlers
        self.library_handler = LibraryHandler(self.driver)
        self.reader_handler = ReaderHandler(self.driver)

        return True

    def run(self, reading_book_title=None):
        """Run the automation flow.

        Args:
            reading_book_title (str, optional): Title of book to read. If provided,
                                              will attempt to open and read the book.

        Returns:
            If reading_book_title is provided:
                tuple: (success, page_number) where success is a boolean and
                      page_number is the current page number or None if not found
            Otherwise:
                bool: True if automation completed successfully, False otherwise
        """
        try:
            # Initialize driver and app
            if not self.initialize_driver():
                logger.error("Failed to initialize driver")
                return (False, None) if reading_book_title else False

            # Handle initial setup and reach library view
            if not self.handle_initial_setup():
                logger.error("Failed to reach library view")
                return (False, None) if reading_book_title else False

            # Check if we're on a captcha screen
            if self.state_machine.current_state == AppState.CAPTCHA:
                logger.info("Automation stopped at captcha screen. Please solve the captcha in captcha.png")
                logger.info("Then update CAPTCHA_SOLUTION in config.py and run again")
                return (False, None) if reading_book_title else False

            # Always get book titles first for debugging
            logger.info("Getting book titles...")
            book_titles = self.library_handler.get_book_titles()

            if not book_titles:
                logger.warning("No books found in library")
                return (False, None) if reading_book_title else True

            # If we're reading a specific book
            if reading_book_title:
                return self.reader_handler.handle_reading_flow(reading_book_title)

            return True

        except Exception as e:
            logger.error(f"Automation failed: {e}")
            import traceback

            traceback.print_exc()
            return (False, None) if reading_book_title else False
        finally:
            self.cleanup()

    def handle_initial_setup(self):
        """Handles the initial app setup and ensures we reach the library view"""
        return self.state_machine.transition_to_library()


def main():
    parser = argparse.ArgumentParser(description="Kindle Automation Tool")
    parser.add_argument("--reinstall", action="store_true", help="Reinstall the Kindle app")
    args = parser.parse_args()

    try:
        # Try to import from config.py, fall back to template if not found
        try:
            import config

            AMAZON_EMAIL = config.AMAZON_EMAIL
            AMAZON_PASSWORD = config.AMAZON_PASSWORD
            CAPTCHA_SOLUTION = getattr(config, "CAPTCHA_SOLUTION", None)
            READING_BOOK_TITLE = getattr(config, "READING_BOOK_TITLE", None)
        except ImportError:
            logger.warning("No config.py found. Using default credentials from config.template.py")
            import config_template

            AMAZON_EMAIL = config_template.AMAZON_EMAIL
            AMAZON_PASSWORD = config_template.AMAZON_PASSWORD
            CAPTCHA_SOLUTION = getattr(config_template, "CAPTCHA_SOLUTION", None)
            READING_BOOK_TITLE = None

        # Initialize automator
        automator = KindleAutomator(AMAZON_EMAIL, AMAZON_PASSWORD, CAPTCHA_SOLUTION)

        # Handle reinstall command
        if args.reinstall:
            logger.info("Reinstalling Kindle app...")
            if automator.uninstall_kindle() and automator.install_kindle():
                logger.info("Kindle app reinstalled successfully")
                return 0
            return 1

        # Check credentials for normal operation
        if not AMAZON_EMAIL or not AMAZON_PASSWORD:
            logger.error("Email and password are required in config.py")
            return 1

        # Run the automation
        result = automator.run(READING_BOOK_TITLE)

        # Handle results
        if isinstance(result, tuple):
            success, page_number = result
            if success:
                logger.info(f"Successfully opened book. Current page: {page_number}")
                return 0
        else:
            if result:
                return 0

        return 1

    except Exception as e:
        logger.error(f"Automation failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
