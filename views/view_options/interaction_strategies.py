from appium.webdriver.common.appiumby import AppiumBy

# Buttons and interactive elements
VIEW_OPTIONS_DONE_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/view_and_sort_menu_dismiss"),  # DONE button
    (AppiumBy.ID, "com.amazon.kindle:id/touch_outside"),  # Touch outside area
]
