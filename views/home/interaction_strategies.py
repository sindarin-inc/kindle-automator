from appium.webdriver.common.appiumby import AppiumBy

from views.core.matchers import by_id

# Navigation elements
HOME_TAB_STRATEGIES = [
    # Compose/classic-agnostic: clickable bare-id 'home_tab' View on Kindle 8.150+.
    by_id("home_tab"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='HOME']"),
    (AppiumBy.XPATH, "//android.widget.TextView[@text='Home']"),
    (AppiumBy.ID, "com.amazon.kindle:id/home_tab"),
]

# Content elements
HOME_CONTENT_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/home_content_container"),
    (AppiumBy.ID, "com.amazon.kindle:id/home_content_view"),
]
