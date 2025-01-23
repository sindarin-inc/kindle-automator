from appium.webdriver.common.appiumby import AppiumBy

# Library sign in elements
LIBRARY_SIGN_IN_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in"),
    (AppiumBy.ID, "com.amazon.kindle:id/sign_in_button"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Sign In']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Sign In")'),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("SIGN IN")'),
]

# Email view interaction elements
EMAIL_FIELD_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Email or phone number']"),
]

CONTINUE_BUTTON_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='Continue']"),
]

# Password view interaction elements
PASSWORD_FIELD_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Amazon password']"),
    (AppiumBy.XPATH, "//android.widget.EditText[@password='true']"),
]

PASSWORD_SIGN_IN_BUTTON_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='Sign in']"),
    (AppiumBy.XPATH, "//android.webkit.WebView//android.widget.Button[@text='Sign In']"),
    (AppiumBy.XPATH, "//android.webkit.WebView//android.widget.Button[@text='Sign-In']"),
]

# Common elements that might appear on multiple views
SIGN_IN_RADIO_BUTTON_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.RadioButton[contains(@text, 'Sign in')]"),
]

# Error message elements
AUTH_ERROR_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='No account found with email address']"),
    (AppiumBy.XPATH, "//android.view.View[@text='No account found with email address']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'incorrect password')]"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'incorrect password')]"),
]

SIGN_IN_ERROR_STRATEGIES = [
    "//android.widget.TextView[@text='No account found with email address']",
    "//android.view.View[@text='No account found with email address']",
    "//android.widget.TextView[@text='Please check your email address or click Create Account if you are new to Amazon.']",
    "//android.view.View[@text='Please check your email address or click Create Account if you are new to Amazon.']",
    "//android.widget.TextView[contains(@text, 'valid')]",
    "//android.view.View[contains(@text, 'valid')]",
]
