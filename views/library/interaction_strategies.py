from appium.webdriver.common.appiumby import AppiumBy

# Navigation elements
LIBRARY_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab']"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[contains(@content-desc, 'LIBRARY')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Library']"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_tab"),
]

# View options elements
VIEW_OPTIONS_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/sort_filter"),
    (AppiumBy.XPATH, "//android.widget.Button[@content-desc='view and sort options']"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_view_options"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='View options']"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'view_options')]"),
]

# Area to click to close menus
MENU_CLOSE_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/library_root_view"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_view_root"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_recycler_container"),
]

LIST_VIEW_OPTION_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='List']"),
    (AppiumBy.XPATH, "//*[contains(@text, 'List view')]"),
]

GRID_VIEW_OPTION_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Grid']"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Grid view')]"),
]

# Sign in elements for empty library
LIBRARY_SIGN_IN_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/empty_library_sign_in"),
    (AppiumBy.ID, "com.amazon.kindle:id/sign_in_button"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Sign In']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("Sign In")'),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("SIGN IN")'),
]

# Book list elements
BOOK_LIST_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/recycler_view"),
]

BOOK_ITEM_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/badgeable_cover"),
    (AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, ', Book')]"),
]

BOOK_TITLE_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/badgeable_cover"),
    (AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, ', Book')]"),
]

# Filter elements
ALL_ITEMS_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='All']"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_all_items_tab"),
]

DOWNLOADED_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Downloaded']"),
    (AppiumBy.ID, "com.amazon.kindle:id/library_downloaded_tab"),
]

# View options menu state detection
VIEW_OPTIONS_MENU_STATE_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/view_and_sort_menu_dismiss"),  # DONE button
    (AppiumBy.XPATH, "//android.widget.TextView[@text='List']"),  # List view option
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Grid']"),  # Grid view option
]
