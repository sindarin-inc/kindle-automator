from appium.webdriver.common.appiumby import AppiumBy

# Sign in button detection strategies
SIGN_IN_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/sign_in_button"),
    (AppiumBy.XPATH, "//*[@text='Sign in']"),
    (AppiumBy.XPATH, "//*[@text='Sign In']"),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Sign in")'),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Sign In")'),
]


# Tab selection detection strategies
def get_tab_selection_strategies(tab_name):
    return [
        # Strategy 1: Check content-desc attribute
        (
            AppiumBy.ANDROID_UIAUTOMATOR,
            f'new UiSelector().descriptionContains("{tab_name}, Tab selected")',
        ),
        # Strategy 2: Check tab by ID with selected icon and label
        (
            AppiumBy.ID,
            f"com.amazon.kindle:id/{tab_name.lower()}_tab",
            {  # Additional checks for child elements
                "icon": (AppiumBy.ID, "com.amazon.kindle:id/icon", "selected", "true"),
                "label": (
                    AppiumBy.ID,
                    "com.amazon.kindle:id/label",
                    "selected",
                    "true",
                ),
            },
        ),
    ]


# Notification dialog detection strategies
NOTIFICATION_DIALOG_STRATEGIES = [
    (AppiumBy.ID, "com.android.permissioncontroller:id/permission_message"),
    (AppiumBy.XPATH, "//*[contains(@text, 'notifications')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Notifications')]"),
]

# Reading view detection strategies
READING_VIEW_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_root_view"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'reader_view')]"),
]

# Library root view detection strategies
LIBRARY_ROOT_STRATEGIES = [(AppiumBy.ID, "com.amazon.kindle:id/library_root_view")]
