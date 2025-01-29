from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
LIBRARY_VIEW_IDENTIFIERS = [
    # Primary identifiers - most specific and reliable
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_root_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_recycler_container']"),
    # Secondary identifiers - specific to library functionality
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_top_tool_bar_layout']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sort_filter']"),  # View options button
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/filter_root']"),  # Filter section
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/search_box']"),  # Search box
    # View-specific identifiers
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']",
    ),
    # Navigation identifiers - updated for tablet layout
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.TextView[@selected='true']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.ImageView[@selected='true']",
    ),
]

# Empty library with sign-in button identifiers
EMPTY_LIBRARY_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Sign in to access your Kindle Library')]"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_empty_view']"),
]

LIBRARY_TAB_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[contains(@content-desc, 'LIBRARY, Tab')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
]

LIBRARY_TAB_SELECTION_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab selected']"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.TextView[@selected='true']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/library_tab']//android.widget.ImageView[@selected='true']",
    ),
]

# Bottom navigation bar identifiers
BOTTOM_NAV_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/bottom_bar']"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/bottom_bar_inflated']",
    ),
]

# Library view content identifiers
LIBRARY_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_content']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_toolbar']"),
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/recycler_view']",
    ),
]

# View mode identifiers
GRID_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/grid_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/grid_recycler_view']"),
]

LIST_VIEW_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/list_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/list_recycler_view']"),
]

# Book element identifiers - updated for tablet layout
BOOK_TITLE_IDENTIFIERS = [
    # Find buttons that contain book titles
    (AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, ', Book')]"),
    (
        AppiumBy.XPATH,
        "//android.widget.Button[.//android.widget.TextView[@resource-id='com.amazon.kindle:id/lib_book_row_title']]",
    ),
]

BOOK_TITLE_ELEMENT_ID = "com.amazon.kindle:id/lib_book_row_title"
BOOK_AUTHOR_ELEMENT_ID = "com.amazon.kindle:id/lib_book_row_author"

BOOK_AUTHOR_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/lib_book_row_author']"),
]
