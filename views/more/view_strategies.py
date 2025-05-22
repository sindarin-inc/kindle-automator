from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies for More tab
MORE_SETTINGS_VIEW_IDENTIFIERS = [
    # Primary identifiers - most specific and reliable
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/more_screenlet_root']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/items_screen_list']"),
    # Tab selection identifiers
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='More, Tab selected']"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/more_tab']//android.widget.TextView[@selected='true']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/more_tab']//android.widget.ImageView[@selected='true']",
    ),
    # Sync Now button as a strong indicator
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sync_item_id']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Sync Now']"),
]

# More tab identifiers
MORE_TAB_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/more_tab']"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[contains(@content-desc, 'More, Tab')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='MORE']"),
]

# More tab selection identifiers
MORE_TAB_SELECTION_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='More, Tab selected']"),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/more_tab']//android.widget.TextView[@selected='true']",
    ),
    (
        AppiumBy.XPATH,
        "//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/more_tab']//android.widget.ImageView[@selected='true']",
    ),
]

# Sync button identifiers
SYNC_BUTTON_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/sync_item_id"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sync_item_id']"),
    (AppiumBy.XPATH, "//android.widget.Button[@content-desc[contains(., 'Sync Now')]]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Sync Now']"),
]

# Sync status identifiers
SYNC_STATUS_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/sync_item_status"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sync_item_status']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Last synced')]"),
]

# More settings menu items
MORE_MENU_ITEMS = {
    "sync": [
        (AppiumBy.ID, "com.amazon.kindle:id/sync_item_id"),
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Sync Now']"),
    ],
    "read_listen": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Read & Listen with Audible']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Read & Listen with Audible']"),
    ],
    "reading_challenges": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Reading Challenges']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc[contains(., 'Reading Challenges')]]"),
    ],
    "your_lists": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Your Lists']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Your Lists']"),
    ],
    "kindle_unlimited": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Kindle Unlimited Membership']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Kindle Unlimited Membership']"),
    ],
    "notebooks": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Notebooks']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Notebooks']"),
    ],
    "amazon_family": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Amazon Family Sharing']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Amazon Family Sharing']"),
    ],
    "settings": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Settings']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Settings']"),
    ],
    "help_feedback": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Help & Feedback']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Help & Feedback']"),
    ],
    "info": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Info']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Info']"),
    ],
    "sign_out": [
        (AppiumBy.XPATH, "//android.widget.TextView[@text='Sign Out']"),
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc[contains(., 'Sign Out')]]"),
    ],
}
