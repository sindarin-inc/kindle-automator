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

READING_TOOLBAR_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/menuitem_close_book"),
    (AppiumBy.ID, "com.amazon.kindle:id/menuitem_hamburger"),
    (AppiumBy.ID, "com.amazon.kindle:id/command_bar_title_bottom"),
]

BOTTOM_SHEET_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/bottom_sheet_dialog"),
    (AppiumBy.ID, "com.amazon.kindle:id/bottom_sheet_pill"),
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
