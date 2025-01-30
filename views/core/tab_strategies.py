from appium.webdriver.common.appiumby import AppiumBy


# Tab selection strategies
def get_tab_selection_strategies(tab_name):
    """Generate strategies for detecting tab selection state.

    Args:
        tab_name (str): Name of the tab to check (e.g. 'LIBRARY', 'HOME')

    Returns:
        list: List of tuples containing strategies to detect if the tab is selected
    """
    return [
        # Primary strategy - check for exact content-desc match
        (AppiumBy.XPATH, f"//android.widget.LinearLayout[@content-desc='{tab_name}, Tab selected']"),
        # Secondary strategy - check for selected state in tab components
        (
            AppiumBy.XPATH,
            f"//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/{tab_name.lower()}_tab']//android.widget.TextView[@selected='true']",
        ),
        # Fallback strategy - check for selected state in tab icon
        (
            AppiumBy.XPATH,
            f"//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/{tab_name.lower()}_tab']//android.widget.ImageView[@selected='true']",
        ),
        # Additional strategy - check for both child elements being selected
        (
            AppiumBy.XPATH,
            f"//android.widget.LinearLayout[@resource-id='com.amazon.kindle:id/{tab_name.lower()}_tab'][.//android.widget.ImageView[@selected='true'] and .//android.widget.TextView[@selected='true']]",
        ),
        # Fallback strategy - check for content-desc without selected attribute
        (
            AppiumBy.XPATH,
            f"//android.widget.LinearLayout[@content-desc='{tab_name}, Tab selected' and .//android.widget.ImageView[@selected='true'] and .//android.widget.TextView[@selected='true']]",
        ),
        # Additional fallback - check for content-desc and any selected child element
        (
            AppiumBy.XPATH,
            f"//android.widget.LinearLayout[@content-desc='{tab_name}, Tab selected' and (.//android.widget.ImageView[@selected='true'] or .//android.widget.TextView[@selected='true'])]",
        ),
        # Last resort - check for content-desc only
        (AppiumBy.XPATH, f"//android.widget.LinearLayout[@content-desc='{tab_name}, Tab selected']"),
    ]
