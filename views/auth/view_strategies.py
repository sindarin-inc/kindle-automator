from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
EMAIL_VIEW_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.webkit.WebView[@text='Amazon Sign-In']//android.widget.EditText[@hint='Email or phone number']",
    ),
]

PASSWORD_VIEW_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.webkit.WebView[@text='Amazon Sign-In']//android.widget.EditText[@password='true']",
    ),
]

ERROR_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Error')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'incorrect')]"),
]

# Captcha view identification strategies
CAPTCHA_VIEW_IDENTIFIERS = [
    # Main view identifier
    (AppiumBy.XPATH, "//android.webkit.WebView[@text='Authentication required']"),
    # Captcha heading
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Solve this puzzle')]"),
    # Captcha image
    (AppiumBy.XPATH, "//android.widget.Image[@text='captcha']"),
    # Input field
    (AppiumBy.XPATH, "//android.widget.EditText[not(@password)]"),
    # Instructions text
    (AppiumBy.XPATH, "//android.view.View[@text='Enter the letters and numbers above']"),
    # Helper buttons
    (AppiumBy.XPATH, "//android.view.View[@content-desc='See new characters ']"),
    (AppiumBy.XPATH, "//android.view.View[@content-desc='Hear the characters']"),
    # Continue button
    (AppiumBy.XPATH, "//android.widget.Button[@text='Continue' and @hint='verifyCaptcha']"),
]

# Required indicators for captcha screen verification
CAPTCHA_REQUIRED_INDICATORS = [
    (AppiumBy.XPATH, "//android.webkit.WebView[@text='Authentication required']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Solve this puzzle')]"),
    (AppiumBy.XPATH, "//android.widget.Image[@text='captcha']"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'Enter the letters')]"),
    (AppiumBy.XPATH, "//android.widget.Button[@hint='verifyCaptcha']"),
]

# Library view verification strategies - prioritized by specificity
LIBRARY_VIEW_VERIFICATION_STRATEGIES = [
    # Primary identifiers - most specific and reliable
    (AppiumBy.ID, "com.amazon.kindle:id/library_screenlet_root"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_view_root"),
    # Secondary identifiers - specific to library functionality
    (AppiumBy.ID, "com.amazon.kindle:id/library_recycler_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_top_tool_bar_layout"),
    # View-specific identifiers - only check if primary/secondary fail
    (AppiumBy.XPATH, "//android.widget.GridView[@resource-id='com.amazon.kindle:id/recycler_view']"),
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']",
    ),
    # Navigation identifiers - least specific, use as last resort
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']"),
]

SIGN_IN_ERROR_STRATEGIES = [
    "//android.view.View[contains(@text, 'No account found with email address')]",
    "//android.view.View[contains(@text, 'incorrect password')]",
    "//android.view.View[contains(@text, 'unable to verify your mobile number')]",  # Add mobile verification error
]
