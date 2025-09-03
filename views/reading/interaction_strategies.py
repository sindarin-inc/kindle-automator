from appium.webdriver.common.appiumby import AppiumBy

# Navigation elements
PAGE_TURN_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_content_view"),  # Main content area for tapping
]

# Download limit reached dialog elements
DOWNLOAD_LIMIT_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='DOWNLOAD LIMIT REACHED']"),
    (AppiumBy.ID, "com.amazon.kindle:id/rlr_title"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'DOWNLOAD LIMIT')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@content-desc, 'download limit reached')]"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[.//android.widget.TextView[@text='DOWNLOAD LIMIT REACHED']]",
    ),
]

DOWNLOAD_LIMIT_ERROR_TEXT = [
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/rlr_error_title']"),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[contains(@text, 'Oops! You have reached your download limit')]",
    ),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'download limit')]"),
]

DOWNLOAD_LIMIT_DEVICE_LIST = [
    (AppiumBy.ID, "com.amazon.kindle:id/rlr_device_list"),
    (AppiumBy.XPATH, "//android.widget.ListView[@resource-id='com.amazon.kindle:id/rlr_device_list']"),
    (AppiumBy.XPATH, "//android.widget.ListView[.//android.widget.CheckedTextView]"),
]

DOWNLOAD_LIMIT_FIRST_DEVICE = [
    (
        AppiumBy.XPATH,
        "//android.widget.ListView[@resource-id='com.amazon.kindle:id/rlr_device_list']/android.widget.LinearLayout[1]",
    ),
    (AppiumBy.XPATH, "//android.widget.ListView/android.widget.LinearLayout[1]"),
    (AppiumBy.XPATH, "(//android.widget.LinearLayout[.//android.widget.CheckedTextView])[1]"),
]

DOWNLOAD_LIMIT_CHECKEDTEXTVIEW = [
    (
        AppiumBy.XPATH,
        "//android.widget.CheckedTextView[@resource-id='com.amazon.kindle:id/rlr_list_device_name']",
    ),
    (AppiumBy.XPATH, "//android.widget.CheckedTextView"),
    (AppiumBy.XPATH, "(//android.widget.CheckedTextView)[1]"),
]

DOWNLOAD_LIMIT_REMOVE_BUTTON = [
    (AppiumBy.ID, "com.amazon.kindle:id/rlr_remove_and_read_now_button"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='REMOVE AND READ NOW']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='REMOVE AND DOWNLOAD']"),
    (AppiumBy.XPATH, "//android.widget.Button[contains(@text, 'REMOVE AND')]"),
    (AppiumBy.XPATH, "//android.widget.Button[contains(@text, 'READ NOW')]"),
    (AppiumBy.XPATH, "//android.widget.Button[contains(@text, 'Download')]"),
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
    (AppiumBy.ID, "com.android.systemui:id/ok"),  # Android 36 version
    (
        AppiumBy.XPATH,
        "//android.widget.Button[@resource-id='com.android.systemui:id/ok' and @text='Got it']",
    ),  # Android 36 specific
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

# Comic book view elements
COMIC_BOOK_X_BUTTON = [
    (AppiumBy.ID, "com.amazon.kindle:id/brochure_x_button"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Close']"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[@resource-id='com.amazon.kindle:id/brochure_x_button']"),
]


# Item Removed dialog functions
def handle_item_removed_dialog(driver):
    """Handle the 'Item Removed' dialog by clicking the Close button."""
    import logging

    from views.reading.view_strategies import ITEM_REMOVED_DIALOG_CLOSE_BUTTON

    try:
        for strategy, selector in ITEM_REMOVED_DIALOG_CLOSE_BUTTON:
            try:
                close_button = driver.find_element(strategy, selector)
                close_button.click()
                logging.info("Clicked Close button on Item Removed dialog")
                return True
            except Exception:
                continue

        logging.warning("Could not find Close button on Item Removed dialog")
        driver.save_screenshot("item_removed_dialog_error.png")
        return False
    except Exception as e:
        logging.error(f"Error handling Item Removed dialog: {e}")
        driver.save_screenshot("item_removed_dialog_error.png")
        return False


COMIC_BOOK_NEXT_BUTTON = [
    (AppiumBy.ID, "com.amazon.kindle:id/brochure_button_next"),
    (AppiumBy.XPATH, "//android.widget.TextView[@content-desc='Show next set of options']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/brochure_button_next']"),
]

# Title Not Available dialog identifiers
TITLE_NOT_AVAILABLE_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Title Not Available']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Title Not Available')]"),
    (AppiumBy.ID, "android:id/alertTitle"),  # Generic alert title
]

# Title Not Available dialog buttons
TITLE_NOT_AVAILABLE_DIALOG_BUTTONS = [
    (AppiumBy.ID, "android:id/button2"),  # Cancel button
    (AppiumBy.XPATH, "//android.widget.Button[@text='Cancel']"),  # Fallback using text
]

# Unable to Download dialog identifiers
UNABLE_TO_DOWNLOAD_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Unable to Download']"),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/alertTitle' and @text='Unable to Download']",
    ),
]

# Unable to Download OK button
UNABLE_TO_DOWNLOAD_OK_BUTTON = [
    (AppiumBy.ID, "android:id/button1"),  # OK button by ID
    (AppiumBy.XPATH, "//android.widget.Button[@text='OK']"),  # Fallback using text
]

# Page position popover interaction elements
PAGE_SCRUBBER_SEEKBAR = [
    (AppiumBy.ID, "com.amazon.kindle:id/page_scrubber_seekbar"),
    (AppiumBy.XPATH, "//android.widget.SeekBar[@resource-id='com.amazon.kindle:id/page_scrubber_seekbar']"),
]

PAGE_POSITION_TEXT = [
    (AppiumBy.ID, "com.amazon.kindle:id/page_position_text"),
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/page_position_text']"),
]

# Footer page number element that opens the page position popover when tapped
FOOTER_PAGE_NUMBER_TAP_TARGET = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number_text"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number"),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/reader_footer_page_number_text']",
    ),
]
