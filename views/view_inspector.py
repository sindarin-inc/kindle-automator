from appium.webdriver.common.appiumby import AppiumBy
import subprocess
import time


class ViewInspector:
    def __init__(self):
        self.app_package = "com.amazon.kindle"
        self.app_activity = "com.amazon.kindle.UpgradePage"
        self.driver = None

    def set_driver(self, driver):
        """Sets the Appium driver instance"""
        self.driver = driver

    def ensure_app_foreground(self):
        """Ensures the Kindle app is in the foreground"""
        try:
            print(f"Bringing {self.app_package} to foreground...")
            subprocess.run(
                ["adb", "shell", f"am start -n {self.app_package}/{self.app_activity}"],
                check=True,
                capture_output=True,
                text=True,
            )
            time.sleep(0.5)  # Reduced from 2s to 0.5s
            print("App brought to foreground")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error bringing app to foreground: {e}")
            return False

    def _is_tab_selected(self, tab_name):
        """Check if a specific tab is currently selected"""
        try:
            # Try to find the tab with 'selected' state
            xpath = f"//android.widget.LinearLayout[@content-desc='{tab_name}, Tab' and @selected='true']"
            print(f"Looking for selected tab: {tab_name}")
            selected_tab = self.driver.find_element(AppiumBy.XPATH, xpath)
            print(f"Found {tab_name} tab is selected")
            return True
        except Exception as e:
            print(f"Tab {tab_name} not selected")
            return False

    def get_current_view(self):
        """Determines the current view using multiple indicators"""
        if not self.driver:
            print("Error: Appium driver not set")
            return None

        try:
            print("\nStarting view detection...")

            # First check for notifications permission dialog as it overlays everything
            try:
                print("Checking for notification permission dialog...")
                notification_indicators = [
                    (AppiumBy.XPATH, "//*[contains(@text, 'notifications')]"),
                    (AppiumBy.XPATH, "//*[contains(@text, 'Notifications')]"),
                    (
                        AppiumBy.ID,
                        "com.android.permissioncontroller:id/permission_message",
                    ),
                ]
                for strategy, locator in notification_indicators:
                    if self.driver.find_element(strategy, locator):
                        print("Detected notifications permission dialog")
                        return "notifications_permission"
            except Exception as e:
                print(f"No notification dialog found: {str(e)}")

            # Check for sign in view
            try:
                print("Checking for sign in view...")
                sign_in_indicators = [
                    (AppiumBy.ID, "com.amazon.kindle:id/sign_in_button"),
                    (AppiumBy.XPATH, "//*[contains(@text, 'Sign In')]"),
                    (AppiumBy.XPATH, "//*[contains(@text, 'Sign in')]"),
                ]
                for strategy, locator in sign_in_indicators:
                    if self.driver.find_element(strategy, locator):
                        print("Detected sign in view")
                        return "sign_in"
            except Exception as e:
                print(f"No sign in view found: {str(e)}")

            # Check for reading view
            try:
                print("Checking for reading view...")
                reading_indicators = [
                    (AppiumBy.ID, "com.amazon.kindle:id/reader_root"),
                    (AppiumBy.XPATH, "//*[contains(@resource-id, 'reader_view')]"),
                ]
                for strategy, locator in reading_indicators:
                    if self.driver.find_element(strategy, locator):
                        print("Detected reading view")
                        return "reading"
            except Exception as e:
                print(f"No reading view found: {str(e)}")

            # Check which tab is selected
            print("Checking tab selection...")
            if self._is_tab_selected("LIBRARY"):
                print("Detected library tab is selected")
                return "library"
            elif self._is_tab_selected("HOME"):
                print("Detected home tab is selected")
                return "home"

            # If we can't determine the view but we're in the app
            try:
                print("Checking for general app indicators...")
                if self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/library_root_view"
                ):
                    print("In app but can't determine exact view")
                    return "unknown"
            except Exception as e:
                print(f"No general app indicators found: {str(e)}")

            print("Could not identify current view with any known indicators")
            return "unknown"

        except Exception as e:
            print(f"Error determining current view: {e}")
            return None
