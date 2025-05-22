from appium.webdriver.common.appiumby import AppiumBy

# Navigation elements for More tab
MORE_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='More, Tab']"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[contains(@content-desc, 'More')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='MORE']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='More']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/more_tab']"),
]

# Sync button interaction strategies
SYNC_BUTTON_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/sync_item_id"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sync_item_id']"),
    (AppiumBy.XPATH, "//android.widget.Button[@content-desc[contains(., 'Sync Now')]]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Sync Now']"),
    (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Sync Now']]"),
]

# Library tab strategies (for navigating back from More)
LIBRARY_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='LIBRARY, Tab']"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[contains(@content-desc, 'LIBRARY')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='LIBRARY']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Library']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/library_tab']"),
]

# Home tab strategies (for navigating from More)
HOME_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.LinearLayout[@content-desc='Home, Tab']"),
    (AppiumBy.XPATH, "//android.widget.LinearLayout[contains(@content-desc, 'Home')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='HOME']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Home']"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/home_tab']"),
]

# Menu item interaction strategies
MORE_MENU_ITEM_STRATEGIES = {
    "sync": [
        (AppiumBy.ID, "com.amazon.kindle:id/sync_item_id"),
        (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Sync Now']]"),
    ],
    "read_listen": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Read & Listen with Audible']"),
        (
            AppiumBy.XPATH,
            "//android.widget.Button[.//android.widget.TextView[@text='Read & Listen with Audible']]",
        ),
    ],
    "reading_challenges": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc[contains(., 'Reading Challenges')]]"),
        (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Reading Challenges']]"),
    ],
    "your_lists": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Your Lists']"),
        (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Your Lists']]"),
    ],
    "kindle_unlimited": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Kindle Unlimited Membership']"),
        (
            AppiumBy.XPATH,
            "//android.widget.Button[.//android.widget.TextView[@text='Kindle Unlimited Membership']]",
        ),
    ],
    "notebooks": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Notebooks']"),
        (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Notebooks']]"),
    ],
    "amazon_family": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Amazon Family Sharing']"),
        (
            AppiumBy.XPATH,
            "//android.widget.Button[.//android.widget.TextView[@text='Amazon Family Sharing']]",
        ),
    ],
    "settings": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Settings']"),
        (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Settings']]"),
    ],
    "help_feedback": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Help & Feedback']"),
        (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Help & Feedback']]"),
    ],
    "info": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc='Info']"),
        (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Info']]"),
    ],
    "sign_out": [
        (AppiumBy.XPATH, "//android.widget.Button[@content-desc[contains(., 'Sign Out')]]"),
        (AppiumBy.XPATH, "//android.widget.Button[.//android.widget.TextView[@text='Sign Out']]"),
    ],
}

# Sync status detection strategies
SYNC_STATUS_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/sync_item_status"),
    (AppiumBy.XPATH, "//*[@resource-id='com.amazon.kindle:id/sync_item_status']"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Last synced')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Syncing')]"),
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Sync complete')]"),
]

# Sync progress indicators
SYNC_PROGRESS_INDICATORS = [
    (AppiumBy.XPATH, "//android.widget.TextView[contains(@text, 'Syncing')]"),
    (AppiumBy.XPATH, "//android.widget.ProgressBar"),
    (AppiumBy.XPATH, "//*[contains(@content-desc, 'Syncing')]"),
]
