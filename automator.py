import argparse
import logging
import os

from driver import Driver
from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler
from views.state_machine import AppState, KindleStateMachine

logger = logging.getLogger(__name__)


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
            if not self.transition_to_library():
                # Check if we're on a captcha screen - this is actually a success case
                # that requires client interaction
                if self.state_machine.current_state == AppState.CAPTCHA:
                    logger.info(
                        "Automation stopped at captcha screen. Please solve the captcha in captcha.png"
                    )
                    logger.info("Then update CAPTCHA_SOLUTION in config.py and run again")
                    # Don't cleanup - keep driver alive for next request
                    return (True, None) if reading_book_title else True

                logger.error("Failed to reach library view")
                self.cleanup()  # Only cleanup on actual failure
                return (False, None) if reading_book_title else False

            # Store the current page source
            self.store_current_page_source()

            # Always get book titles first for debugging
            logger.info("Getting book titles...")
            book_titles = self.library_handler.get_book_titles()

            if not book_titles:
                logger.warning("No books found in library")
                return (False, None) if reading_book_title else True

            # If we're reading a specific book
            if reading_book_title:
                result = self.reader_handler.handle_reading_flow(reading_book_title)
                if not result[0]:  # Only cleanup on failure
                    self.cleanup()
                return result

            return True

        except Exception as e:
            logger.error(f"Automation failed: {e}")
            import traceback

            traceback.print_exc()
            self.cleanup()  # Cleanup on exception
            return (False, None) if reading_book_title else False

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
                logger.info("No driver found, initializing...")
                return self.initialize_driver()

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
            logger.error(f"Error ensuring driver is running: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Kindle Automation Tool")
    parser.add_argument("--reinstall", action="store_true", help="Reinstall the Kindle app")
    args = parser.parse_args()

    try:
        # Import config
        import config

        automator = KindleAutomator(
            config.AMAZON_EMAIL, config.AMAZON_PASSWORD, getattr(config, "CAPTCHA_SOLUTION", None)
        )

        # Handle reinstall command
        if args.reinstall:
            logger.info("Reinstalling Kindle app...")
            if automator.uninstall_kindle() and automator.install_kindle():
                logger.info("Kindle app reinstalled successfully")
                return 0
            return 1

        # Run the automation
        result = automator.run(getattr(config, "READING_BOOK_TITLE", None))

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
