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
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/nln_text_secondary']",
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

# Add new identifiers for the "last read page" dialog
LAST_READ_PAGE_DIALOG_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='android:id/message' and contains(@text, 'You are currently on page')]",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='android:id/message' and contains(@text, 'You are currently at location')]",
    ),
]

# Add new identifiers for the "Go to that location?" dialog
GO_TO_LOCATION_DIALOG_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='android:id/message' and contains(@text, 'Go to that location?')]",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='android:id/message' and contains(@text, 'Go to that page?')]",
    ),
]

# Add style button and menu identifiers
STYLE_BUTTON_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/menuitem_viewoptions"),
    (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Reading Settings']"),
]

LAYOUT_TAB_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_layout_tab"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='Layout']"),
]

STYLE_MENU_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_settings_panel"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_settings_container"),
]

DARK_MODE_TOGGLE_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_settings_theme_dark"),
    (AppiumBy.XPATH, "//android.widget.RadioButton[@text='Dark']"),
]

LIGHT_MODE_TOGGLE_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_settings_theme_light"),
    (AppiumBy.XPATH, "//android.widget.RadioButton[@text='Light']"),
]

# Background color radio buttons
BLACK_BG_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_bg_color_option_black"),
    (AppiumBy.XPATH, "//android.widget.RadioButton[@content-desc='Black']"),
]

WHITE_BG_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_bg_color_option_white"),
    (AppiumBy.XPATH, "//android.widget.RadioButton[@content-desc='White']"),
]

# Goodreads auto-update dialog identifiers
GOODREADS_AUTO_UPDATE_DIALOG_IDENTIFIERS = [
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/tutorial_title' and @text='Auto-update on Goodreads']",
    ),
]

GOODREADS_AUTO_UPDATE_DIALOG_BUTTONS = [
    (AppiumBy.ID, "com.amazon.kindle:id/button_enable_autoshelving"),  # "OK" button
    (AppiumBy.ID, "com.amazon.kindle:id/button_disable_autoshelving"),  # "NOT NOW" button
]

# ID for "Not Now" button in Goodreads dialog
GOODREADS_NOT_NOW_BUTTON = (AppiumBy.ID, "com.amazon.kindle:id/button_disable_autoshelving")
