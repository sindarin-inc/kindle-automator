import logging
import time
from typing import Callable, Optional

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.interaction import POINTER_TOUCH
from selenium.webdriver.common.actions.pointer_input import PointerInput

logger = logging.getLogger(__name__)


class SmartScroller:
    """Smart scrolling utility for Kindle Automator - unified scroll implementation."""

    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        self.screen_size = self.driver.get_window_size()

    def _perform_hook_scroll(
        self,
        center_x: int,
        scroll_start_y: int,
        scroll_end_y: int,
        total_duration_ms: int,
    ):
        """
        Performs a scroll gesture that starts fast and decelerates towards the end
        to achieve precise positioning without inertia.
        Uses W3C Actions with ActionBuilder.
        """
        # Get ActionBuilder from ActionChains
        action_builder = ActionChains(self.driver).w3c_actions

        # Add a new pointer input source of type touch and get the PointerInput object
        # POINTER_TOUCH is 'touch'
        finger = action_builder.add_pointer_input(POINTER_TOUCH, "finger")

        # Sequence of actions for the 'finger'
        # These methods on 'finger' (PointerInput) will add actions to the 'action_builder'

        # 1. Move pointer to start position (instantaneous)
        finger.create_pointer_move(duration=0, x=center_x, y=scroll_start_y)
        # 2. Press down (button=0 is typically the main touch/mouse button)
        finger.create_pointer_down(button=0)
        # 3. Small pause (duration is in seconds for create_pause)
        finger.create_pause(0.01)  # 10ms

        if scroll_start_y == scroll_end_y:
            # If there's no vertical movement, just perform a press for the specified duration
            # The initial 10ms pause is already accounted for.
            # Remaining duration for the press itself.
            press_duration_s = max(0, (total_duration_ms - 10) / 1000.0)
            if press_duration_s > 0:
                finger.create_pause(press_duration_s)
        else:
            # Multi-segment scroll for deceleration using 6 segments
            # Modified to have much stronger deceleration at the end to eliminate momentum
            # Ratios: distance [0.35, 0.25, 0.20, 0.12, 0.06, 0.02]
            # Ratios: time     [0.08, 0.12, 0.15, 0.20, 0.25, 0.20]

            # Calculate durations for each segment (ensure they sum to total_duration_ms - 10ms pause)
            effective_total_duration_ms = total_duration_ms - 10  # Account for the initial 10ms pause

            duration1_ms = int(round(effective_total_duration_ms * 0.08))
            duration2_ms = int(round(effective_total_duration_ms * 0.12))
            duration3_ms = int(round(effective_total_duration_ms * 0.15))
            duration4_ms = int(round(effective_total_duration_ms * 0.20))
            duration5_ms = int(round(effective_total_duration_ms * 0.25))
            # duration6_ms takes the remainder to ensure sum is correct
            duration6_ms = (
                effective_total_duration_ms
                - duration1_ms
                - duration2_ms
                - duration3_ms
                - duration4_ms
                - duration5_ms
            )

            # Ensure all durations are non-negative
            duration1_ms = max(0, duration1_ms)
            duration2_ms = max(0, duration2_ms)
            duration3_ms = max(0, duration3_ms)
            duration4_ms = max(0, duration4_ms)
            duration5_ms = max(0, duration5_ms)
            duration6_ms = max(0, duration6_ms)

            delta_y = scroll_end_y - scroll_start_y

            # Calculate target y-coordinates for each segment
            y1_target = scroll_start_y + 0.35 * delta_y
            y2_target = scroll_start_y + (0.35 + 0.25) * delta_y  # Cumulative distance
            y3_target = scroll_start_y + (0.35 + 0.25 + 0.20) * delta_y
            y4_target = scroll_start_y + (0.35 + 0.25 + 0.20 + 0.12) * delta_y
            y5_target = scroll_start_y + (0.35 + 0.25 + 0.20 + 0.12 + 0.06) * delta_y
            # y6_target is scroll_end_y

            # Perform the scroll segments
            # Segment 1 - fast initial movement
            finger.create_pointer_move(duration=duration1_ms, x=center_x, y=int(round(y1_target)))
            # Segment 2
            finger.create_pointer_move(duration=duration2_ms, x=center_x, y=int(round(y2_target)))
            # Segment 3
            finger.create_pointer_move(duration=duration3_ms, x=center_x, y=int(round(y3_target)))
            # Segment 4 - starting to slow down significantly
            finger.create_pointer_move(duration=duration4_ms, x=center_x, y=int(round(y4_target)))
            # Segment 5 - very slow movement
            finger.create_pointer_move(duration=duration5_ms, x=center_x, y=int(round(y5_target)))
            # Segment 6 - final tiny crawl to eliminate momentum
            finger.create_pointer_move(duration=duration6_ms, x=center_x, y=scroll_end_y)

        # Release the pointer
        finger.create_pointer_up(button=0)

        try:
            # Perform all actions defined in the ActionBuilder
            action_builder.perform()
        except Exception as e:
            logger.error(f"Error performing scroll: {e}")

    def scroll_down(self):
        """Scroll down in the view using the smart scrolling technique."""
        screen_size = self.driver.get_window_size()
        start_y = screen_size["height"] * 0.8
        end_y = screen_size["height"] * 0.2

        self._perform_hook_scroll(
            screen_size["width"] // 2,
            start_y,
            end_y,
            1200,  # Increased from 1001ms to allow more time for deceleration
        )

        # Allow time for scroll to complete
        time.sleep(0.5)

    def scroll_up(self):
        """Scroll up in the view using the smart scrolling technique."""
        screen_size = self.driver.get_window_size()
        start_y = screen_size["height"] * 0.2
        end_y = screen_size["height"] * 0.8

        self._perform_hook_scroll(
            screen_size["width"] // 2,
            start_y,
            end_y,
            1200,  # Increased from 1001ms to allow more time for deceleration
        )

        # Allow time for scroll to complete
        time.sleep(0.5)

    def scroll_to_element(
        self, element_finder: Callable, max_scrolls: int = 10, direction: str = "down"
    ) -> bool:
        """
        Scroll until an element is found or max_scrolls is reached.

        Args:
            element_finder: A function that returns the element if found, None otherwise
            max_scrolls: Maximum number of scroll attempts
            direction: Scroll direction, either "down" or "up"

        Returns:
            bool: True if the element was found, False otherwise
        """
        for _ in range(max_scrolls):
            element = element_finder()
            if element:
                return True

            if direction.lower() == "down":
                self.scroll_down()
            elif direction.lower() == "up":
                self.scroll_up()
            else:
                raise ValueError(f"Invalid scroll direction: {direction}. Use 'up' or 'down'.")

            # Allow time for content to settle
            time.sleep(0.5)

        return False

    def scroll_to_position(self, container_element, target_y_percentage: float):
        """
        Smart scroll to position a reference container at the specified percentage from top.

        Args:
            container_element: The element to position
            target_y_percentage: Target Y position as percentage of screen height (0.0-1.0)
        """
        try:
            screen_size = self.driver.get_window_size()
            start_y = container_element.location["y"]
            end_y = screen_size["height"] * target_y_percentage

            # Verify scroll distance is reasonable
            if abs(start_y - end_y) < 100:
                logger.warning("Scroll distance too small, using default scroll")
                self.scroll_down()  # Use default scroll instead
            else:
                self._perform_hook_scroll(
                    screen_size["width"] // 2,
                    start_y,
                    end_y,
                    1200,  # Increased from 1001ms to allow more time for deceleration
                )
        except (NoSuchElementException, StaleElementReferenceException):
            logger.warning("Element reference lost during scroll_to_position, using default scroll")
            self.scroll_down()  # Fallback to default
        except Exception as e:
            logger.error(f"Error in scroll_to_position: {e}")
            self.scroll_down()  # Fallback to default
