import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AboutBookPopoverHandler:
    """Handles the 'About the Book' popover that appears in various reading contexts."""
    
    def __init__(self, driver):
        """Initialize with the driver instance."""
        self.driver = driver

    def dismiss_popover(self) -> Optional[Dict[str, Any]]:
        """
        Dismisses the About Book popover by tapping in the area above it.

        The popover is a bottom sheet that slides up from the bottom, and can be
        dismissed by tapping anywhere in the darkened area above the sheet content.
        """
        try:
            # The clickable FrameLayout covers the entire screen when the bottom sheet is shown
            # We'll tap in the upper portion of the screen to dismiss it
            clickable_frame = self.driver.find_element(
                "xpath",
                "//android.widget.FrameLayout[@resource-id='com.amazon.kindle:id/bottom_sheet_container']"
                "//android.widget.FrameLayout[@clickable='true' and @bounds='[0,0][1080,1920]']",
            )

            if clickable_frame:
                # Tap in the upper area of the screen (above the popover content)
                # Using coordinates that should be safely above any popover content
                self.driver.tap([(540, 300)])  # Center horizontally, upper third of screen
                logger.info("Dismissed About Book popover by tapping above content")
                return {"action": "dismissed_about_book_popover", "success": True}

        except Exception as e:
            logger.warning(f"Failed to dismiss About Book popover: {e}")
            # Try alternative approach - tap using absolute coordinates
            try:
                self.driver.tap([(540, 300)])
                logger.info("Dismissed About Book popover using fallback tap")
                return {"action": "dismissed_about_book_popover", "success": True}
            except Exception as fallback_error:
                logger.error(f"Fallback dismissal also failed: {fallback_error}")

        return None

    def is_popover_present(self) -> bool:
        """
        Checks if the About Book popover is currently displayed.

        Returns:
            bool: True if the popover is present, False otherwise
        """
        try:
            # Check for the bottom sheet container with clickable overlay
            clickable_frame = self.driver.find_element(
                "xpath",
                "//android.widget.FrameLayout[@resource-id='com.amazon.kindle:id/bottom_sheet_container']"
                "//android.widget.FrameLayout[@clickable='true' and @bounds='[0,0][1080,1920]']",
            )
            return clickable_frame is not None
        except:
            return False
