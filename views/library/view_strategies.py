from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
LIBRARY_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/library_root_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_recycler_container"),
]

# Empty library with sign-in button identifiers
EMPTY_LIBRARY_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Sign in to access your Kindle Library')]"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_empty_view"),
]

LIBRARY_TAB_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Library']"),
]

# View mode identifiers
GRID_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.GridView[@resource-id='com.amazon.kindle:id/recycler_view']"),
    (AppiumBy.CLASS_NAME, "android.widget.GridView"),
]

LIST_VIEW_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title']",
    ),
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_author']",
    ),
]

# Book element identifiers
BOOK_TITLE_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_title"),
]

BOOK_AUTHOR_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/lib_book_row_author"),
]
