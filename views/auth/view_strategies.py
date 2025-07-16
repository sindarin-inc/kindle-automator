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
    (AppiumBy.XPATH, "//android.view.View[@resource-id='auth-error-message-box']"),
]

# Captcha-related strategies
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
    # Interactive captcha indicators
    (AppiumBy.XPATH, "//android.view.View[@text='Solve this puzzle to protect your account']"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'Choose all the')]"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Confirm']"),
]

# Grid-based image captcha that we can't solve programmatically
INTERACTIVE_CAPTCHA_IDENTIFIERS = [
    # Grid-related UI elements - specific to the image grid captcha
    (AppiumBy.XPATH, "//android.view.View[@resource-id='aacb-waf-box']"),
    (AppiumBy.XPATH, "//android.view.View[@resource-id='root']"),
    (AppiumBy.XPATH, "//android.view.View[@resource-id='captcha-container']"),
    # Buttons specific to image grid captcha
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='amzn-btn-verify-internal']"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='amzn-btn-refresh-internal']"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='amzn-btn-info-internal']"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='amzn-btn-audio-internal']"),
    # Look for multiple numbered buttons (the image grid)
    (AppiumBy.XPATH, "//android.widget.Button[@text='1']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='2']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='3']"),
    # Special text elements in grid captcha
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'Solved:')]"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'Required:')]"),
]

CAPTCHA_REQUIRED_INDICATORS = [
    # Text captcha indicators
    (AppiumBy.XPATH, "//android.webkit.WebView[@text='Authentication required']"),
    (AppiumBy.XPATH, "//android.widget.Image[@text='captcha']"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'Enter the letters')]"),
    (AppiumBy.XPATH, "//android.widget.Button[@hint='verifyCaptcha']"),
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Enter the characters you see']"),
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Type characters']"),
]

CAPTCHA_ERROR_MESSAGES = [
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Enter the characters as they are given')]"),
]

# Puzzle authentication indicators
# Simplified to only check for the universal puzzle text
PUZZLE_REQUIRED_INDICATORS = [
    (AppiumBy.XPATH, "//android.view.View[@text='Solve this puzzle to protect your account']"),
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
    "//android.view.View[@resource-id='auth-error-message-box']//android.view.View[contains(@text, 'problem')]",
]

# Auth error messages that require app restart
AUTH_RESTART_MESSAGES = [
    (
        AppiumBy.XPATH,
        '//android.view.View[contains(@text, "We\'re unable to verify your mobile number")]',
    ),
]

# Two-Step Verification (2FA) view identifiers
TWO_FACTOR_VIEW_IDENTIFIERS = [
    # Main WebView with title
    (AppiumBy.XPATH, "//android.webkit.WebView[@text='Two-Step Verification']"),
    # Header text
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Two-Step Verification']"),
    # OTP input field
    (AppiumBy.ID, "auth-mfa-otpcode"),
    (AppiumBy.XPATH, "//android.widget.EditText[@resource-id='auth-mfa-otpcode']"),
    # Instruction text
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'One Time Password')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Authenticator App')]"),
    # Form container
    (AppiumBy.ID, "auth-mfa-form"),
    (AppiumBy.XPATH, "//android.view.View[@resource-id='auth-mfa-form']"),
    # Email OTP variant identifiers
    (AppiumBy.XPATH, "//android.view.View[@text='Enter verification code']"),
    (AppiumBy.ID, "input-box-otp"),
    (AppiumBy.XPATH, "//android.widget.EditText[@resource-id='input-box-otp']"),
    (AppiumBy.ID, "verification-code-form"),
    (AppiumBy.XPATH, "//android.view.View[@resource-id='verification-code-form']"),
    (AppiumBy.ID, "cvf-submit-otp-button"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Submit code']"),
    (
        AppiumBy.XPATH,
        '//android.view.View[contains(@text, "For your security, we\'ve sent the code to your email")]',
    ),
    (AppiumBy.ID, "channelDetailsForOtp"),
    (AppiumBy.XPATH, "//android.view.View[@content-desc='Resend code']"),
]
