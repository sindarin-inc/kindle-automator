from appium.webdriver.common.appiumby import AppiumBy

# System dialog detection strategies
NOTIFICATION_DIALOG_IDENTIFIERS = [
    (AppiumBy.ID, "com.android.permissioncontroller:id/permission_message"),
    (AppiumBy.XPATH, "//*[contains(@text, 'notifications')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Notifications')]"),
]

# Common dialog buttons
DIALOG_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "android:id/button1"),  # Usually OK/Accept
    (AppiumBy.ID, "android:id/button2"),  # Usually Cancel/Deny
    (AppiumBy.XPATH, "//android.widget.Button[@text='OK']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Cancel']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Allow']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Deny']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Got it']"),
]

# Error dialog identifiers
ERROR_DIALOG_IDENTIFIERS = [
    (AppiumBy.ID, "android:id/alertTitle"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Error')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'error')]"),
]

# Full screen dialog identifiers
FULLSCREEN_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Viewing full screen']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Got it']"),
    (AppiumBy.ID, "android:id/ok"),
]

# Dialog detection strategies for "App not responding" dialog
APP_NOT_RESPONDING_DIALOG_IDENTIFIERS = [
    # The title that says "Kindle isn't responding"
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='android:id/alertTitle' and contains(@text, 'Kindle isn')]",
    ),
    # The "Close app" button
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/aerr_close' and @text='Close app']"),
    # The "Wait" button
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/aerr_wait' and @text='Wait']"),
]

# Download limit reached dialog identifiers
DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS = [
    # Title that says "DOWNLOAD LIMIT REACHED"
    (AppiumBy.ID, "com.amazon.kindle:id/rlr_title"),
    (AppiumBy.XPATH, "//android.widget.TextView[@content-desc='download limit reached header']"),
    # Error message containing "download limit"
    (AppiumBy.ID, "com.amazon.kindle:id/rlr_error_title"),
    # Device list container
    (AppiumBy.ID, "com.amazon.kindle:id/rlr_device_list"),
    # Remove and Read Now button
    (AppiumBy.ID, "com.amazon.kindle:id/rlr_remove_and_read_now_button"),
    # Cancel button
    (AppiumBy.ID, "com.amazon.kindle:id/rlr_cancel"),
]

# Read and Listen dialog identifiers
READ_AND_LISTEN_DIALOG_IDENTIFIERS = [
    # Title that says "Read and listen"
    (AppiumBy.ID, "com.amazon.kindle:id/brochure_pager_title"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Read and listen']"),
    # Brochure layout container
    (AppiumBy.ID, "com.amazon.kindle:id/brochure_layout"),
]

# Read and Listen dialog close button
READ_AND_LISTEN_CLOSE_BUTTON = [
    (AppiumBy.ID, "com.amazon.kindle:id/brochure_x_button"),
    (
        AppiumBy.XPATH,
        "//android.widget.ImageButton[@content-desc='Close' and @resource-id='com.amazon.kindle:id/brochure_x_button']",
    ),
]

# Viewing full screen dialog identifiers
VIEWING_FULL_SCREEN_DIALOG_IDENTIFIERS = [
    # Title that says "Viewing full screen"
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='android:id/immersive_cling_title' and @text='Viewing full screen']",
    ),
    (AppiumBy.ID, "android:id/immersive_cling_title"),
    # Android 36 version
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.android.systemui:id/immersive_cling_title' and @text='Viewing full screen']",
    ),
    (AppiumBy.ID, "com.android.systemui:id/immersive_cling_title"),
    # Description text
    (AppiumBy.ID, "android:id/immersive_cling_description"),
    (AppiumBy.ID, "com.android.systemui:id/immersive_cling_description"),
]

# Viewing full screen dialog "Got it" button
VIEWING_FULL_SCREEN_GOT_IT_BUTTON = [
    (AppiumBy.ID, "android:id/ok"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/ok' and @text='Got it']"),
    # Android 36 version
    (AppiumBy.ID, "com.android.systemui:id/ok"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='com.android.systemui:id/ok' and @text='Got it']"),
]

# Dialog interaction strategies
APP_NOT_RESPONDING_CLOSE_APP_BUTTON = (
    AppiumBy.XPATH,
    "//android.widget.Button[@resource-id='android:id/aerr_close' and @text='Close app']",
)
