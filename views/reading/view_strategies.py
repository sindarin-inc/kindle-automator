from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.by import By

# View identification strategies
READING_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_drawer_layout"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_under_drawer"),  # Container under drawer layout
    (AppiumBy.ID, "com.amazon.kindle:id/reader_root_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_content_fragment_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_page_fragment_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_number_text"),
    (AppiumBy.ID, "com.amazon.kindle:id/manga_root_layout"),  # Manga/comic reader view
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
        "//android.widget.TextView[@resource-id='com.android.systemui:id/immersive_cling_title' and @text='Viewing full screen']",
    ),
    (AppiumBy.ID, "com.android.systemui:id/immersive_cling_title"),
    (AppiumBy.ID, "com.android.systemui:id/ok"),  # The "Got it" button
    (AppiumBy.ID, "android:id/ok"),  # Android 36 uses android:id instead of com.android.systemui:id
    (
        AppiumBy.XPATH,
        "//android.widget.Button[@resource-id='android:id/ok' and @text='Got it']",
    ),  # More specific for Android 36
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


# Tutorial message identifiers
TUTORIAL_MESSAGE_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/snackbar_text"),
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/snackbar_text']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Tap the middle of the page')]"),
]

TUTORIAL_MESSAGE_CONTAINER = [
    (AppiumBy.ID, "com.amazon.kindle:id/toast_tutorial_shell"),
    (AppiumBy.XPATH, "//android.view.ViewGroup[@resource-id='com.amazon.kindle:id/toast_tutorial_shell']"),
]

# Footnote dialog identifiers (appears when tapping on footnote links)
# Not currently used - footnotes are handled by fallback tap strategy in reader_handler
FOOTNOTE_DIALOG_IDENTIFIERS = []

# Bottom left position indicator in reading view
# Shows current position in various formats (page X of Y, location X of Y, X minutes left, etc.)
READING_POSITION_INDICATOR_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/reader_footer_page_num_view"),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/reader_footer_page_num_view']",
    ),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@resource-id, 'page_num_view')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@resource-id, 'footer_page')]"),
    # Fallback: look for text patterns in bottom left area
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, ' of ')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Page ')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Location ')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, ' left in ')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'minutes left')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'hours left')]"),
]

# Page position popover identifiers (accessed via footer page number tap)
PAGE_POSITION_POPOVER_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/page_scrubber_popover"),
    (AppiumBy.ID, "com.amazon.kindle:id/page_position_popover"),
    (AppiumBy.ID, "com.amazon.kindle:id/location_container"),  # Main container for page position popover
    (AppiumBy.ID, "com.amazon.kindle:id/nln_text_secondary"),  # Page position text in popover
    (AppiumBy.ID, "com.amazon.kindle:id/page_scrubber_seekbar"),  # Seekbar in popover
    (AppiumBy.XPATH, "//android.widget.FrameLayout[contains(@resource-id, 'popover')]"),
]

# Table of Contents button in the page position popover
TABLE_OF_CONTENTS_BUTTON_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/page_scrubber_menu"),
    (AppiumBy.ID, "com.amazon.kindle:id/menuitem_toc"),
    (AppiumBy.ID, "com.amazon.kindle:id/menuitem_hamburger"),  # The hamburger menu button
    (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Table of Contents']"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[contains(@content-desc, 'Table of Contents')]"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[contains(@content-desc, 'Contents')]"),
]

# Table of Contents view identifiers
TABLE_OF_CONTENTS_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/toc_dialog_container"),  # Main ToC dialog container
    (AppiumBy.ID, "com.amazon.kindle:id/toc_fragment_container"),  # ToC fragment container
    (AppiumBy.ID, "com.amazon.kindle:id/toc_list_container"),  # RecyclerView containing the list
    (
        AppiumBy.ID,
        "com.amazon.kindle:id/toc_entry_view_container",
    ),  # ToC entry containers (actual element found)
    (AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title"),  # ToC chapter titles (actual element found)
    (AppiumBy.ID, "com.amazon.kindle:id/toc_header_container"),  # ToC header with title/author
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Table of Contents']"),
]

# Table of Contents list view
TABLE_OF_CONTENTS_LIST_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/toc_list_container"),  # RecyclerView (primary identifier)
    (
        AppiumBy.XPATH,
        "//androidx.recyclerview.widget.RecyclerView[@resource-id='com.amazon.kindle:id/toc_list_container']",
    ),
    (AppiumBy.ID, "com.amazon.kindle:id/toc_list"),
    (AppiumBy.XPATH, "//android.widget.ListView[@resource-id='com.amazon.kindle:id/toc_list']"),
]

# Table of Contents close button
TABLE_OF_CONTENTS_CLOSE_BUTTON_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/toc_header_close_parent"),  # Primary close button container
    (AppiumBy.XPATH, "//android.widget.FrameLayout[@content-desc='Close Table Of Contents']"),
    (AppiumBy.ID, "com.amazon.kindle:id/toc_header_close"),  # Close button image view
    (AppiumBy.ID, "com.amazon.kindle:id/toc_close_button"),
    (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Close']"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='Close']"),
]

# Chapter item identifiers in the Table of Contents
CHAPTER_ITEM_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/toc_entry_title"),  # Actual ToC chapter title elements
    (
        AppiumBy.XPATH,
        "//android.widget.ListView[@resource-id='com.amazon.kindle:id/toc_list']//android.widget.TextView",
    ),
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/chapter_title']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/toc_item_text']"),
]

# Chapter page number in ToC item
CHAPTER_PAGE_NUMBER_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/toc_entry_position"),  # Actual page position element
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/toc_entry_position']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/chapter_page_number']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@resource-id='com.amazon.kindle:id/toc_item_page']"),
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
