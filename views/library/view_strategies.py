from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
LIBRARY_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/library_home_root"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_root_view"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'library_view')]"),
]

EMPTY_LIBRARY_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/empty_library_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in"),
]

LIBRARY_TAB_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Library']"),
]
