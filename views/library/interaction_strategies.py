from appium.webdriver.common.appiumby import AppiumBy

# Navigation elements
LIBRARY_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Library']"),
]

# Sign in elements for empty library
LIBRARY_SIGN_IN_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in"),
    (AppiumBy.ID, "com.amazon.kindle:id/sign_in_button"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Sign In']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Sign In")'),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("SIGN IN")'),
]

# Book list elements
BOOK_LIST_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/library_books_list"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_content_container"),
]

BOOK_ITEM_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/library_book_item"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'book_item')]"),
]
