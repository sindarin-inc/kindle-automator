from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
EMAIL_VIEW_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.webkit.WebView[@text='Amazon Sign-In']//android.widget.EditText[@hint='Email or phone number']",
    ),
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Email or phone number']"),
]

PASSWORD_VIEW_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.webkit.WebView[@text='Amazon Sign-In']//android.widget.EditText[@password='true']",
    ),
    (AppiumBy.XPATH, "//android.widget.EditText[@password='true']"),
    (AppiumBy.XPATH, "//android.widget.EditText[@hint='Amazon password']"),
]

ERROR_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Error')]"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'Error')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'incorrect')]"),
    (AppiumBy.XPATH, "//android.view.View[contains(@text, 'incorrect')]"),
]

# Library view verification strategies
LIBRARY_VIEW_VERIFICATION_STRATEGIES = [
    # Root view identifiers
    (AppiumBy.ID, "com.amazon.kindle:id/library_home_root"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_root_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_recycler_container"),
    # Grid view specific identifiers
    (AppiumBy.ID, "com.amazon.kindle:id/recycler_view"),
    (AppiumBy.XPATH, "//android.widget.GridView[@resource-id='com.amazon.kindle:id/recycler_view']"),
    # List view specific identifiers
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']",
    ),
    # Tab identifiers
    (AppiumBy.ID, "com.amazon.kindle:id/library_tab"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
    # Additional library elements
    (AppiumBy.ID, "com.amazon.kindle:id/library_screenlet_root"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_view_root"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_top_tool_bar_layout"),
    # Bottom navigation
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']"),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/label' and @text='LIBRARY']",
    ),
]
