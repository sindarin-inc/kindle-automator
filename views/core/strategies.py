from appium.webdriver.common.appiumby import AppiumBy

# Common XPath patterns
COMMON_TEXT_PATTERNS = {
    "sign_in": ["Sign in", "Sign In", "SIGN IN", "Sign-in", "Sign-In"],
    "error": ["error", "Error", "problem", "Problem", "invalid", "Invalid"],
}

# Authentication related strategies
SIGN_IN_VIEW_STRATEGIES = [
    # Email field
    (AppiumBy.CLASS_NAME, "android.widget.EditText"),
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Email or phone number']"),
    # Sign in page indicators
    (AppiumBy.XPATH, "//android.webkit.WebView[@text='Amazon Sign-In']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Continue']"),
]

SIGN_IN_BUTTON_STRATEGIES = [
    # Resource ID based
    (AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in"),
    (AppiumBy.ID, "com.amazon.kindle:id/sign_in_button"),
    # Text based
    (AppiumBy.XPATH, "//android.widget.Button[@text='Sign In']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
    # UI Automator based
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Sign In")'),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("SIGN IN")'),
]

# Error detection strategies
AUTH_ERROR_STRATEGIES = [
    # Account not found
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@text='No account found with email address']",
    ),
    (
        AppiumBy.XPATH,
        "//android.view.View[@text='No account found with email address']",
    ),
    # Password errors
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[contains(@text, 'incorrect password')]",
    ),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'incorrect password')]"),
]

SIGN_IN_ERROR_STRATEGIES = [
    # Account not found
    "//android.widget.TextView[@text='No account found with email address']",
    "//android.view.View[@text='No account found with email address']",
    "//android.widget.TextView[@text='Please check your email address or click Create Account if you are new to Amazon.']",
    "//android.view.View[@text='Please check your email address or click Create Account if you are new to Amazon.']",
    # General validation errors
    "//android.widget.TextView[contains(@text, 'valid')]",
    "//android.view.View[contains(@text, 'valid')]",
    "//android.widget.TextView[contains(@text, 'Error')]",
    "//android.view.View[contains(@text, 'Error')]",
]

# System dialog detection strategies
NOTIFICATION_DIALOG_STRATEGIES = [
    (AppiumBy.ID, "com.android.permissioncontroller:id/permission_message"),
    (AppiumBy.XPATH, "//*[contains(@text, 'notifications')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Notifications')]"),
]

# View detection strategies
READING_VIEW_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_root_view"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'reader_view')]"),
]

LIBRARY_ROOT_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/library_root_view"),
]
