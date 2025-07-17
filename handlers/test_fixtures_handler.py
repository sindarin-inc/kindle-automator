import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler


class TestFixturesHandler:
    def __init__(self, driver):
        self.driver = driver
        self.library_handler = LibraryHandler(driver)
        self.reader_handler = ReaderHandler(driver)
        self.fixtures_dir = "fixtures/views"
        os.makedirs(self.fixtures_dir, exist_ok=True)

    def _restart_kindle_app(self):
        """Kill and restart the Kindle app to start from Home view."""
        logger.info("Restarting Kindle app...")
        subprocess.run(["adb", "shell", "am force-stop", "com.amazon.kindle"], check=True)
        time.sleep(1)
        subprocess.run(
            ["adb", "shell", "am start -n com.amazon.kindle/com.amazon.kindle.UpgradePage"],
            check=True,
        )
        time.sleep(2)

    def _capture_view(self, name: str):
        """Capture the current view's page source to a file."""
        logger.info(f"Capturing {name} view...")
        source = self.driver.page_source
        with open(os.path.join(self.fixtures_dir, f"{name}.xml"), "w") as f:
            f.write(source)

    def create_fixtures(self):
        """Create fixtures for all major views."""
        try:
            # Step 1: Kill and restart Kindle app to start from Home view
            self._restart_kindle_app()
            self._capture_view("home")

            # Step 2: Navigate to Library and capture
            logger.info("Navigating to Library view...")
            if self.library_handler.navigate_to_library():
                self._capture_view("library")
            else:
                logger.error("Failed to navigate to Library view", exc_info=True)

            # Step 3: Open a book and capture reading views
            logger.info("Opening book...")
            book_title = "Poor Charlie's Almanack: The Essential Wit and Wisdom of Charles T. Munger"
            if self.reader_handler.open_book(book_title):
                # Capture initial reading view
                self._capture_view("reading")

                # Show toolbar and capture
                window_size = self.driver.get_window_size()
                center_x = window_size["width"] // 2
                center_y = window_size["height"] // 2
                self.driver.tap([(center_x, center_y)])
                time.sleep(1)
                self._capture_view("reading_with_toolbar")
            else:
                logger.error("Failed to open book", exc_info=True)

            # Step 4: Force sign out and capture auth view
            logger.info("Capturing auth view...")
            subprocess.run(["adb", "shell", "pm clear com.amazon.kindle"], check=True)
            time.sleep(1)
            subprocess.run(
                ["adb", "shell", "am start -n com.amazon.kindle/com.amazon.kindle.UpgradePage"],
                check=True,
            )
            time.sleep(2)
            self._capture_view("auth")

            return True

        except Exception as e:
            logger.error(f"Error creating fixtures: {e}", exc_info=True)
            return False
