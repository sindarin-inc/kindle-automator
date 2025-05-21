from appium.webdriver.common.appiumby import AppiumBy

# Invalid Item dialog elements
INVALID_ITEM_DIALOG_BUTTONS = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='REMOVE' and @resource-id='android:id/button1']"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/button1']"),  # REMOVE button
    (AppiumBy.XPATH, "//android.widget.Button[@text='CANCEL' and @resource-id='android:id/button2']"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/button2']"),  # CANCEL button
]

# Navigation elements
LIBRARY_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab']"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[contains(@content-desc, 'LIBRARY')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Library']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_tab']"),
]

# View options elements
VIEW_OPTIONS_BUTTON_STRATEGIES = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sort_filter']"),
    (AppiumBy.XPATH, "//android.widget.Button[@content-desc='view and sort options']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_view_options']"),
    (AppiumBy.XPATH, "//android.widget.ImageButton[@content-desc='View options']"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'view_options')]"),
]

# Area to click to close menus
MENU_CLOSE_STRATEGIES = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_root_view']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_view_root']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_recycler_container']"),
]

LIST_VIEW_OPTION_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/lib_menu_list_view"),  # Direct ID reference for the button
    (AppiumBy.XPATH, "//android.widget.TextView[@text='List']"),
    (AppiumBy.XPATH, "//*[contains(@text, 'List view')]"),
]

GRID_VIEW_OPTION_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/lib_menu_grid_view"),  # Direct ID reference for the button
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Grid']"),
    (AppiumBy.XPATH, "//*[contains(@text, 'Grid view')]"),
]

# Sign in elements for empty library
LIBRARY_SIGN_IN_BUTTON_STRATEGIES = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/empty_library_sign_in']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sign_in_button']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='Sign In']"),
    (AppiumBy.XPATH, "//android.widget.Button[@text='SIGN IN']"),
]

# Book list elements
BOOK_LIST_STRATEGIES = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/recycler_view']"),
]

BOOK_ITEM_STRATEGIES = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/badgeable_cover']"),
    (AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, ', Book')]"),
]

BOOK_TITLE_STRATEGIES = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/badgeable_cover']"),
    (AppiumBy.XPATH, "//android.widget.Button[contains(@content-desc, ', Book')]"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/book_item']"),
]

# Filter elements
ALL_ITEMS_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='All']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_all_items_tab']"),
]

DOWNLOADED_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Downloaded']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_downloaded_tab']"),
]

# View options menu state detection
VIEW_OPTIONS_MENU_STATE_STRATEGIES = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/view_and_sort_menu_dismiss']"),  # DONE button
    (AppiumBy.XPATH, "//android.widget.TextView[@text='List']"),  # List view option
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Grid']"),  # Grid view option
]

VIEW_OPTIONS_DONE_STRATEGIES = [
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/view_and_sort_menu_dismiss']"),  # DONE button
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/touch_outside']"),  # Touch outside area
]

# Safe areas to tap to close menus - coordinates are relative to screen size (0-1)
SAFE_TAP_AREAS = [
    (0.1, 0.1),  # Top-left corner
    (0.9, 0.1),  # Top-right corner
    (0.1, 0.9),  # Bottom-left corner
    (0.9, 0.9),  # Bottom-right corner
    (0.5, 0.5),  # Center of screen
]

# Unable to Download dialog identifiers and buttons
UNABLE_TO_DOWNLOAD_DIALOG_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Unable to Download']"),
    (
        AppiumBy.XPATH,
        "//android.widget.TextView[@resource-id='com.amazon.kindle:id/alertTitle' and @text='Unable to Download']",
    ),
    (AppiumBy.ID, "com.amazon.kindle:id/alertTitle"),
]

UNABLE_TO_DOWNLOAD_DIALOG_BUTTONS = [
    (AppiumBy.XPATH, "//android.widget.Button[@text='CANCEL']"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/button2']"),
    (AppiumBy.ID, "android:id/button2"),  # CANCEL button
    (AppiumBy.XPATH, "//android.widget.Button[@text='TRY AGAIN']"),
    (AppiumBy.XPATH, "//android.widget.Button[@resource-id='android:id/button1']"),
    (AppiumBy.ID, "android:id/button1"),  # TRY AGAIN button
]
