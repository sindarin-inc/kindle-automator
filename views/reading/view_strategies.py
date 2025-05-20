from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.by import By

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

# Comic book view identifiers
COMIC_BOOK_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/brochure_layout"),
    (AppiumBy.XPATH, "//android.view.ViewGroup[@resource-id='com.amazon.kindle:id/brochure_layout']"),
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

# Reading style settings
PLACEMARK_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_placemark_ribbon"),
    (AppiumBy.XPATH, "//android.widget.ImageView[@content-desc='Bookmark added.']"),
    (AppiumBy.XPATH, "//android.widget.ImageView[@content-desc='Bookmark removed.']"),
]

STYLE_SLIDEOVER_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_bottom_sheet"),
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_setting_content"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/aa_menu_v2_setting_content']",
    ),
]

FONT_SIZE_SLIDER_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_font_slider_seekbar"),
    (
        AppiumBy.XPATH,
        "//android.widget.SeekBar[@resource-id='com.amazon.kindle:id/aa_menu_v2_font_slider_seekbar']",
    ),
    (AppiumBy.XPATH, "//android.widget.SeekBar[@content-desc='Font Size']"),
]

MORE_TAB_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_more_tab"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='More']"),
]

STYLE_SHEET_PILL_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/bottom_sheet_pill"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/bottom_sheet_pill']"),
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_bottom_sheet_handle"),
    (
        AppiumBy.XPATH,
        "//android.widget.ImageView[@resource-id='com.amazon.kindle:id/aa_menu_v2_bottom_sheet_handle']",
    ),
]

# Reading preferences checkboxes
REALTIME_HIGHLIGHTING_CHECKBOX = [
    (
        AppiumBy.ID,
        "com.amazon.kindle:id/aa_menu_v2_real_time_text_highlighting_toggle",
    ),  # Correct ID from XML
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_realtime_highlight_toggle"),  # Alternate ID pattern
    (
        AppiumBy.XPATH,
        "//android.widget.Switch[@resource-id='com.amazon.kindle:id/aa_menu_v2_real_time_text_highlighting_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.Switch[@resource-id='com.amazon.kindle:id/aa_menu_v2_realtime_highlight_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.CheckBox[@resource-id='com.amazon.kindle:id/aa_menu_v2_real_time_text_highlighting_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.CheckBox[@resource-id='com.amazon.kindle:id/aa_menu_v2_realtime_highlight_toggle']",
    ),
    (AppiumBy.XPATH, "//android.widget.Switch[contains(@text, 'Real-time Text Highlighting')]"),
    (AppiumBy.XPATH, "//android.widget.CheckBox[contains(@text, 'Real-time Text Highlighting')]"),
    (
        AppiumBy.XPATH,
        "//*[contains(@text, 'Real-time Text Highlighting')]//following-sibling::android.widget.Switch",
    ),
    (
        AppiumBy.XPATH,
        "//*[contains(@text, 'Real-time Text Highlighting')]//following-sibling::android.widget.CheckBox",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[contains(@content-desc, 'Real-time Text Highlighting')]/following-sibling::android.widget.Switch",
    ),
]

ABOUT_BOOK_CHECKBOX = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_about_book_toggle"),
    (
        AppiumBy.ID,
        "com.amazon.kindle:id/aa_menu_v2_about_this_book_toggle",
    ),  # Alternative pattern based on XML
    (
        AppiumBy.XPATH,
        "//android.widget.Switch[@resource-id='com.amazon.kindle:id/aa_menu_v2_about_book_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.Switch[@resource-id='com.amazon.kindle:id/aa_menu_v2_about_this_book_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.CheckBox[@resource-id='com.amazon.kindle:id/aa_menu_v2_about_book_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.CheckBox[@resource-id='com.amazon.kindle:id/aa_menu_v2_about_this_book_toggle']",
    ),
    (AppiumBy.XPATH, "//android.widget.Switch[contains(@text, 'About this Book')]"),
    (AppiumBy.XPATH, "//android.widget.CheckBox[contains(@text, 'About this Book')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'About this Book')]//following-sibling::android.widget.Switch"),
    (AppiumBy.XPATH, "//*[contains(@text, 'About this Book')]//following-sibling::android.widget.CheckBox"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[contains(@content-desc, 'About this Book')]/following-sibling::android.widget.Switch",
    ),
]

PAGE_TURN_ANIMATION_CHECKBOX = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_page_turn_animation_toggle"),
    (
        AppiumBy.XPATH,
        "//android.widget.Switch[@resource-id='com.amazon.kindle:id/aa_menu_v2_page_turn_animation_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.CheckBox[@resource-id='com.amazon.kindle:id/aa_menu_v2_page_turn_animation_toggle']",
    ),
    (AppiumBy.XPATH, "//android.widget.Switch[contains(@text, 'Page Turn Animation')]"),
    (AppiumBy.XPATH, "//android.widget.CheckBox[contains(@text, 'Page Turn Animation')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Page Turn Animation')]//following-sibling::android.widget.Switch"),
    (
        AppiumBy.XPATH,
        "//*[contains(@text, 'Page Turn Animation')]//following-sibling::android.widget.CheckBox",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[contains(@content-desc, 'Page Turn Animation')]/following-sibling::android.widget.Switch",
    ),
    # More generic selector that might help with different UI layouts
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[contains(@text, 'Page Turn')]/../following-sibling::android.widget.Switch",
    ),
]

POPULAR_HIGHLIGHTS_CHECKBOX = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_popular_highlight_toggle"),
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_popular_highlights_toggle"),  # Alternative pattern
    (
        AppiumBy.XPATH,
        "//android.widget.Switch[@resource-id='com.amazon.kindle:id/aa_menu_v2_popular_highlight_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.Switch[@resource-id='com.amazon.kindle:id/aa_menu_v2_popular_highlights_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.CheckBox[@resource-id='com.amazon.kindle:id/aa_menu_v2_popular_highlight_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.CheckBox[@resource-id='com.amazon.kindle:id/aa_menu_v2_popular_highlights_toggle']",
    ),
    (AppiumBy.XPATH, "//android.widget.Switch[contains(@text, 'Popular Highlights')]"),
    (AppiumBy.XPATH, "//android.widget.CheckBox[contains(@text, 'Popular Highlights')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Popular Highlights')]//following-sibling::android.widget.Switch"),
    (
        AppiumBy.XPATH,
        "//*[contains(@text, 'Popular Highlights')]//following-sibling::android.widget.CheckBox",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[contains(@content-desc, 'Popular Highlights')]/following-sibling::android.widget.Switch",
    ),
    # More generic selector that might help with different UI layouts
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[contains(@text, 'Popular Highlight')]/../following-sibling::android.widget.Switch",
    ),
]

HIGHLIGHT_MENU_CHECKBOX = [
    (AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_highlight_menu_toggle"),
    (
        AppiumBy.XPATH,
        "//android.widget.Switch[@resource-id='com.amazon.kindle:id/aa_menu_v2_highlight_menu_toggle']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.CheckBox[@resource-id='com.amazon.kindle:id/aa_menu_v2_highlight_menu_toggle']",
    ),
    (AppiumBy.XPATH, "//android.widget.Switch[contains(@text, 'Highlight Menu')]"),
    (AppiumBy.XPATH, "//android.widget.CheckBox[contains(@text, 'Highlight Menu')]"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Highlight Menu')]//following-sibling::android.widget.Switch"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Highlight Menu')]//following-sibling::android.widget.CheckBox"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[contains(@content-desc, 'Highlight Menu')]/following-sibling::android.widget.Switch",
    ),
    # More generic selector that might help with different UI layouts
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[contains(@text, 'Highlight Menu')]/../following-sibling::android.widget.Switch",
    ),
]

# Word Wise dialog identifiers
WORD_WISE_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Word Wise']"),
    (AppiumBy.ID, "com.amazon.kindle:id/wordwise_ftue_layout"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/wordwise_ftue_layout']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/wordwise_ftue_title' and @text='Word Wise']",
    ),
]

# Item Removed dialog identifiers
ITEM_REMOVED_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Item Removed')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Item Removed']"),
]

ITEM_REMOVED_DIALOG_CLOSE_BUTTON = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='CLOSE']"),
    (AppiumBy.ID, "android:id/button1"),
]

def is_item_removed_dialog_visible(driver):
    """Check if the 'Item Removed' dialog is visible."""
    try:
        for strategy, selector in ITEM_REMOVED_DIALOG_IDENTIFIERS:
            try:
                dialog_title = driver.find_element(strategy, selector)
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False
