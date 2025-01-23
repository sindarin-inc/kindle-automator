from appium.webdriver.common.appiumby import AppiumBy

# Navigation controls
PAGE_TURN_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_page_turn_overlay"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_page_turn_button"),
]

# Toolbar elements
TOOLBAR_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_toolbar_button"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'toolbar_button')]"),
]

MENU_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_menu_button"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Menu']"),
]

# Content elements
TEXT_SELECTION_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_text_selection_overlay"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'text_selection')]"),
]

BOOKMARK_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_bookmark_button"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'bookmark_button')]"),
]
