from appium.webdriver.common.appiumby import AppiumBy

# Navigation elements
HOME_TAB_STRATEGIES = [
    (AppiumBy.XPATH, "//android.widget.TextView[@text='HOME']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Home']"),
    (AppiumBy.ID, "com.amazon.kindle:id/home_tab"),
]

# Content elements
HOME_CONTENT_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/home_content_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/home_content_view"),
]
