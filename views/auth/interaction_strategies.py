from appium.webdriver.common.appiumby import AppiumBy

# Library sign in elements - prioritized by reliability
LIBRARY_SIGN_IN_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in"),  # Most specific
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),  # Common variant
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Sign In")'),  # Fallback
]

# Email view interaction elements
EMAIL_FIELD_STRATEGIES = [
    (
        AppiumBy.XPATH,
        "//android.webkit.WebView[@text='Amazon Sign-In']//android.widget.EditText[@hint='Email or phone number']",
    ),
]

CONTINUE_BUTTON_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='Continue']"),
]

# Password view interaction elements
PASSWORD_FIELD_STRATEGIES = [
    (
        AppiumBy.XPATH,
        "//android.webkit.WebView[@text='Amazon Sign-In']//android.widget.EditText[@password='true']",
    ),
]

PASSWORD_SIGN_IN_BUTTON_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='Sign in']"),
]

# Common elements that might appear on multiple views
SIGN_IN_RADIO_BUTTON_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.RadioButton[contains(@text, 'Sign in')]"),
]

# Error message elements - consolidated and prioritized
AUTH_ERROR_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'No account found')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'incorrect password')]"),
]

# Sign-in specific error messages
SIGN_IN_ERROR_STRATEGIES = [
    "//android.widget.TextView[contains(@text, 'No account found')]",
    "//android.widget.TextView[contains(@text, 'Please check your email')]",
    "//android.widget.TextView[contains(@text, 'valid')]",
]

# Captcha interaction strategies
CAPTCHA_INPUT_FIELD = (AppiumBy.XPATH, "//android.widget.EditText")
CAPTCHA_CONTINUE_BUTTON = (AppiumBy.XPATH, "//android.widget.Button[@text='Continue']")
