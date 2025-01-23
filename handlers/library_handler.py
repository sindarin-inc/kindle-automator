from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time


class LibraryHandler:
    def __init__(self, driver):
        self.driver = driver

    def navigate_to_library(self):
        """Navigates to the Library tab"""
        try:
            # Try to find the Library tab using multiple strategies
            library_tab_strategies = [
                (AppiumBy.ID, "com.amazon.kindle:id/library_tab"),
                (AppiumBy.XPATH, "//*[@content-desc='LIBRARY, Tab']"),
                (
                    AppiumBy.XPATH,
                    "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab']",
                ),
                (
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiSelector().textContains("LIBRARY")',
                ),
                (
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiSelector().descriptionContains("LIBRARY")',
                ),
            ]

            library_tab = None
            for strategy, locator in library_tab_strategies:
                try:
                    print(f"\nTrying to find Library tab with strategy: {strategy}, locator: {locator}")
                    library_tab = WebDriverWait(self.driver, 2).until(
                        EC.presence_of_element_located((strategy, locator))
                    )
                    if library_tab:
                        print(f"Found Library tab using {strategy}: {locator}")
                        break
                except Exception as e:
                    print(f"Strategy {strategy} failed: {e}")
                    continue

            if not library_tab:
                print("Could not find Library tab with any strategy")
                return False

            # Click the tab
            print("Clicking Library tab")
            library_tab.click()
            time.sleep(3)  # Wait for navigation
            return True

        except Exception as e:
            print(f"Error navigating to library: {e}")
            return False

    def list_books(self):
        """List all books in the library"""
        # TODO: Implement book listing functionality
        pass

    def open_book(self, book_title):
        """Open a specific book by title"""
        # TODO: Implement book opening functionality
        pass
