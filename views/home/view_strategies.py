from appium.webdriver.common.appiumby import AppiumBy

# View identification strategies
HOME_VIEW_IDENTIFIERS = [
    (AppiumBy.ID, "com.amazon.kindle:id/home_root_view"),
    (AppiumBy.XPATH, "//*[contains(@resource-id, 'home_view')]"),
]

HOME_TAB_IDENTIFIERS = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='HOME']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Home']"),
    (AppiumBy.ID, "com.amazon.kindle:id/home_tab"),
]
