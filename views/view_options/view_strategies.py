from appium.webdriver.common.appiumby import AppiumBy

# View options menu state detection - only when menu is actually open
VIEW_OPTIONS_MENU_STATE_STRATEGIES = [
    (AppiumBy.ID, "com.amazon.kindle:id/view_and_sort_menu_dismiss"),  # DONE button
    (AppiumBy.ID, "com.amazon.kindle:id/lib_view_type_container"),  # View type container
    (AppiumBy.ID, "com.amazon.kindle:id/view_type_header"),  # View header
]
