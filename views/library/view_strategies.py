from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
LIBRARY_VIEW_IDENTIFIERS = [
    # Primary identifiers - most specific and reliable
    (AppiumBy.ID, "com.amazon.kindle:id/library_root_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_recycler_container"),
    # Secondary identifiers - specific to library functionality
    (AppiumBy.ID, "com.amazon.kindle:id/library_top_tool_bar_layout"),
    (AppiumBy.ID, "com.amazon.kindle:id/sort_filter"),  # View options button
    (AppiumBy.ID, "com.amazon.kindle:id/filter_root"),  # Filter section
    (AppiumBy.ID, "com.amazon.kindle:id/search_box"),  # Search box
    # View-specific identifiers
    (AppiumBy.XPATH, "//android.widget.GridView[@resource-id='com.amazon.kindle:id/recycler_view']"),
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']",
    ),
    # Navigation identifiers
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']"),
]

# Empty library with sign-in button identifiers
EMPTY_LIBRARY_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Sign in to access your Kindle Library')]"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_empty_view"),
]

LIBRARY_TAB_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/library_tab"),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("LIBRARY, Tab")'),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Library")'),
]

LIBRARY_TAB_SELECTION_IDENTIFIERS = [
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("LIBRARY, Tab selected")'),
    (
        AppiumBy.ID,
        "com.amazon.kindle:id/library_tab",
        {
            "icon": (AppiumBy.ID, "com.amazon.kindle:id/icon", "selected", "true"),
            "label": (AppiumBy.ID, "com.amazon.kindle:id/label", "selected", "true"),
        },
    ),
]

# Bottom navigation bar identifiers
BOTTOM_NAV_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/bottom_navigation"),
    (AppiumBy.ID, "com.amazon.kindle:id/navigation_bar_view"),
]

# Library view content identifiers
LIBRARY_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/library_content"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_toolbar"),
]

# View mode identifiers
GRID_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/grid_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/grid_recycler_view"),
]

LIST_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/list_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/list_recycler_view"),
]

# Book element identifiers
BOOK_TITLE_IDENTIFIERS = [
    # Find the button that contains the book title
    (
        AppiumBy.XPATH,
        "//android.widget.Button[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title']]",
    ),
]

BOOK_TITLE_ELEMENT_ID = "com.amazon.kindle:id/lib_book_row_title"
BOOK_AUTHOR_ELEMENT_ID = "com.amazon.kindle:id/lib_book_row_author"

BOOK_AUTHOR_IDENTIFIERS = [
    (AppiumBy.ID, BOOK_AUTHOR_ELEMENT_ID),
]
