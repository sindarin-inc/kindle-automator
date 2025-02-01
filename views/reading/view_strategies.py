from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
READING_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_drawer_layout"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_root_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_content_fragment_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_page_fragment_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number_text"),
]

# Add new identifiers for reading progress and toolbar
READING_PROGRESS_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number_text"),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/reader_footer_page_number_text']",
    ),
]
READING_TOOLBAR_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.widget.Button[@resource-id='com.amazon.kindle:id/menuitem_close_book']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.Button[@resource-id='com.amazon.kindle:id/menuitem_hamburger']",
    ),
]

BOTTOM_SHEET_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/bottom_sheet_dialog']",
    ),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/bottom_sheet_pill']"),
]

PAGE_NUMBER_IDENTIFIERS = [
    # Primary identifier - the text element containing the page number
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number_text"),
    # Fallback identifiers
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/reader_footer_page_number_text']",
    ),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@resource-id, 'page_number')]"),
]

# Add tap zones for page navigation
PAGE_NAVIGATION_ZONES = {
    "next": 0.95,  # 95% of screen width for next page (further right)
    "prev": 0.05,  # 5% of screen width for previous page (further left)
    "center": 0.5,  # 50% for center taps
}

# Full screen dialog detection
READING_VIEW_FULL_SCREEN_DIALOG = [
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='android:id/immersive_cling_title' and @text='Viewing full screen']",
    ),
]
