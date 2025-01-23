from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
READING_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_root_view"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'reader_view')]"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_content_view"),
]

READING_TOOLBAR_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_toolbar"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_toolbar_container"),
]

PAGE_NUMBER_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'page_number')]"),
]
