from appium.webdriver.common.appiumby import AppiumBy

# Navigation elements
PAGE_TURN_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_content_view"),  # Main content area for tapping
]

# UI elements
READING_TOOLBAR_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_toolbar"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_toolbar_container"),
]

PAGE_NUMBER_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'page_number')]"),
]

# Menu elements
READING_MENU_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_menu_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_menu"),
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

BOTTOM_SHEET_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/bottom_sheet_dialog"),
    (AppiumBy.ID, "com.amazon.kindle:id/bottom_sheet_pill"),
]

# About this book slideover identifiers
ABOUT_BOOK_SLIDEOVER_IDENTIFIERS = [
    (AppiumBy.XPATH, "//*[@content-desc='Showing information about this book.']"),
    (AppiumBy.ID, "com.amazon.kindle:id/readingactions_content_container"),
    (
        AppiumBy.XPATH,
        "//*[@content-desc='Information about this book is expanded. Double tap or swipe down to collapse it']",
    ),
]

# Close book button
CLOSE_BOOK_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/menuitem_close_book"),  # Primary strategy
    (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Close Book.']"),  # Fallback strategy
]

# Full screen dialog interaction
FULL_SCREEN_DIALOG_GOT_IT = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='Got it']"),
    (AppiumBy.ID, "android:id/ok"),  # Specific ID for the Got it button
    (AppiumBy.ID, "android:id/button1"),  # Fallback using button ID
]

# Full screen dialog detection
FULL_SCREEN_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Viewing full screen']"),
    (
        AppiumBy.XPATH,
        "//android.widget.RelativeLayout[.//android.widget.TextView[@text='Viewing full screen']]",
    ),
]

# Add strategies for the "last read page" dialog buttons
LAST_READ_PAGE_DIALOG_BUTTONS = [
    (AppiumBy.ID, "android:id/button1"),  # YES button
    (AppiumBy.XPATH, "//android.widget.Button[@text='YES']"),  # Fallback using text
]

# Word Wise dialog identifiers
WORD_WISE_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Word Wise']"),  # Title text
    (AppiumBy.ID, "com.amazon.kindle:id/wordwise_ftue_layout"),  # Dialog layout 
]

# Word Wise "No Thanks" button
WORD_WISE_NO_THANKS_BUTTON = [
    (AppiumBy.ID, "android:id/button2"),  # NO THANKS button by ID
    (AppiumBy.XPATH, "//android.widget.Button[@text='NO THANKS']"),  # Fallback using text
]
