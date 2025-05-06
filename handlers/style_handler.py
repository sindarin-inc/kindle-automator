import logging
import os
import time

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import NoSuchElementException

from server.logging_config import store_page_source
from views.reading.view_strategies import (
    ABOUT_BOOK_CHECKBOX,
    FONT_SIZE_SLIDER_IDENTIFIERS,
    HIGHLIGHT_MENU_CHECKBOX,
    MORE_TAB_IDENTIFIERS,
    PAGE_TURN_ANIMATION_CHECKBOX,
    POPULAR_HIGHLIGHTS_CHECKBOX,
    REALTIME_HIGHLIGHTING_CHECKBOX,
    STYLE_BUTTON_IDENTIFIERS,
    STYLE_SHEET_PILL_IDENTIFIERS,
    STYLE_SLIDEOVER_IDENTIFIERS,
)

logger = logging.getLogger(__name__)


class StyleHandler:
    def __init__(self, driver):
        self.driver = driver
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)
        # Get profile manager from the driver's profile_manager attribute
        self.profile_manager = driver.profile_manager if hasattr(driver, "profile_manager") else None

    def update_reading_style(self, show_placemark: bool = False) -> bool:
        """
        Update reading styles for the current profile. Should be called after a book is opened.
        This will only update styles if they have not already been updated for this profile.

        Args:
            show_placemark (bool): Whether to tap to display the placemark ribbon.
                                  Default is False (don't show placemark).

        Returns:
            bool: True if the styles were updated successfully or were already updated, False otherwise
        """
        # First check if styles have already been updated for this profile
        if self.profile_manager and self.profile_manager.is_styles_updated():
            logger.info("Reading styles already updated for this profile, skipping")
            return True

        logger.info("Updating reading styles for the current profile")

        try:
            # Store page source before starting
            store_page_source(self.driver.page_source, "style_update_before")

            # Calculate screen dimensions for later use
            window_size = self.driver.get_window_size()
            center_x = window_size["width"] // 2
            center_y = window_size["height"] // 2

            # Only tap to show placemark if explicitly requested
            if show_placemark:
                # Tap center of page to show the placemark view
                self.driver.tap([(center_x, center_y)])
                logger.info("Tapped center of page to show placemark (placemark mode enabled)")
                time.sleep(1)

                # Store page source after tapping center
                store_page_source(self.driver.page_source, "style_update_after_center_tap")
            else:
                logger.info("Skipping center tap (placemark mode disabled)")
                # We still need to tap to show reading controls to access the style button
                # This is a tap near the top of the screen that won't trigger a placemark
                top_y = int(window_size["height"] * 0.05)  # Very top of the screen (5%)
                self.driver.tap([(center_x, top_y)])
                logger.info(
                    f"Tapped near top of screen at ({center_x}, {top_y}) to show toolbar without placemark"
                )
                time.sleep(0.5)

            # 2. Tap the Style button
            style_button_found = False
            for strategy, locator in STYLE_BUTTON_IDENTIFIERS:
                try:
                    style_button = self.driver.find_element(strategy, locator)
                    if style_button.is_displayed():
                        style_button.click()
                        logger.info("Clicked style button")
                        style_button_found = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue

            if not style_button_found:
                logger.error("Could not find style button")
                return False

            # Store page source after tapping style button
            store_page_source(self.driver.page_source, "style_update_after_style_button")

            # 3. Slide the font size slider all the way to the left
            slider_found = False
            for strategy, locator in FONT_SIZE_SLIDER_IDENTIFIERS:
                try:
                    slider = self.driver.find_element(strategy, locator)
                    if slider.is_displayed():
                        # Get slider dimensions
                        size = slider.size
                        location = slider.location

                        # Calculate slider endpoints for drag action
                        slider_width = size["width"]
                        slider_height = size["height"]
                        start_x = location["x"] + slider_width - 10  # Near the far right
                        end_x = location["x"] + 10  # Near the far left
                        slider_y = location["y"] + slider_height // 2

                        # Swipe from right to left to decrease font size
                        self.driver.swipe(start_x, slider_y, end_x, slider_y, 500)
                        logger.info(
                            f"Slid font size slider from ({start_x}, {slider_y}) to ({end_x}, {slider_y})"
                        )
                        slider_found = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue

            # Look for the "A" decrease font size button as an alternative
            if not slider_found:
                try:
                    decrease_button = self.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_decrease_font_size"
                    )
                    if decrease_button.is_displayed():
                        logger.info(
                            "Found decrease font size button, tapping multiple times as alternative to slider"
                        )
                        # Tap the button multiple times to ensure smallest font size
                        for _ in range(5):
                            decrease_button.click()
                            time.sleep(0.2)
                        slider_found = True
                except NoSuchElementException:
                    logger.warning("Could not find decrease button either")
                except Exception as e:
                    logger.warning(f"Error using decrease button: {e}")

            if not slider_found:
                logger.warning("Could not find font size slider or decrease button, continuing anyway")
                # We'll continue even if we can't find the slider, as other settings are still important

            # Store page source after adjusting font size
            store_page_source(self.driver.page_source, "style_update_after_font_size")

            # 4. Tap the More tab
            more_tab_found = False
            for strategy, locator in MORE_TAB_IDENTIFIERS:
                try:
                    more_tab = self.driver.find_element(strategy, locator)
                    if more_tab.is_displayed():
                        more_tab.click()
                        logger.info("Clicked More tab")
                        more_tab_found = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue

            if not more_tab_found:
                # Try by text content as a fallback
                try:
                    more_tab = self.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.TextView[@text='More']"
                    )
                    if more_tab.is_displayed():
                        more_tab.click()
                        logger.info("Clicked More tab by text")
                        more_tab_found = True
                        time.sleep(1)
                    else:
                        logger.warning("Found More tab by text but it's not displayed")
                except NoSuchElementException:
                    logger.error("Could not find More tab by any strategy")
                    # We'll continue even without the More tab, try to function with what we have

            # Store page source regardless of whether tab was found
            store_page_source(self.driver.page_source, "style_update_after_more_tab_attempt")

            # Store page source after tapping More tab
            store_page_source(self.driver.page_source, "style_update_after_more_tab")

            # First, expand the slideover to full height by tapping on the handle
            handle_found = False
            try:
                # Look for handle by ID
                handle = self.driver.find_element(
                    AppiumBy.ID, "com.amazon.kindle:id/aa_menu_v2_bottom_sheet_handle"
                )
                if handle.is_displayed():
                    # Get position information
                    location = handle.location
                    size = handle.size
                    handle_x = location["x"] + (size["width"] // 2)
                    handle_y = location["y"] + (size["height"] // 2)

                    # Tap the handle
                    self.driver.tap([(handle_x, handle_y)])
                    logger.info(f"Tapped slideover handle at ({handle_x}, {handle_y}) to expand fully")
                    handle_found = True
                    time.sleep(1)  # Wait for expansion animation
                else:
                    logger.warning("Found handle by ID but it's not displayed")
            except NoSuchElementException:
                logger.warning("Could not find handle by direct ID")

            # If we couldn't find the handle by ID, try other strategies
            if not handle_found:
                try:
                    for strategy, locator in STYLE_SHEET_PILL_IDENTIFIERS:
                        try:
                            pill = self.driver.find_element(strategy, locator)
                            if pill.is_displayed():
                                pill.click()
                                logger.info(f"Clicked slideover pill {strategy}:{locator} to expand")
                                handle_found = True
                                time.sleep(1)
                                break
                        except NoSuchElementException:
                            continue
                except Exception as e:
                    logger.warning(f"Error trying to find and click slideover pill: {e}")

            # If we still couldn't find the handle, try a generic tap where we know it should be
            if not handle_found:
                # From the XML we know the handle is at y position around 1251-1364
                window_size = self.driver.get_window_size()
                center_x = window_size["width"] // 2
                handle_y = 1300  # Approximate position based on the XML
                self.driver.tap([(center_x, handle_y)])
                logger.info(f"Performed blind tap at ({center_x}, {handle_y}) where handle should be")
                time.sleep(1)

            # Store page source after expansion attempt
            store_page_source(self.driver.page_source, "style_update_after_expand_attempt")

            # 5. Disable "Real-time Text Highlighting"
            self._toggle_checkbox(REALTIME_HIGHLIGHTING_CHECKBOX, False, "Real-time Text Highlighting")

            # Store page source after toggling highlighting
            store_page_source(self.driver.page_source, "style_update_after_highlight_toggle")

            # 6. Scroll down to see more options
            try:
                # Look for the ScrollView directly - best strategy
                try:
                    scroll_view = self.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/view_options_tab_scrollview_more"
                    )
                    if scroll_view.is_displayed():
                        logger.info(
                            "Found the More tab ScrollView, will perform a scroll to see additional settings"
                        )

                        # Get the ScrollView dimensions
                        location = scroll_view.location
                        size = scroll_view.size

                        # Calculate scroll coordinates - scroll up to reveal more options
                        start_y = location["y"] + (
                            size["height"] * 0.8
                        )  # Start near bottom of visible scrollview
                        end_y = location["y"] + (size["height"] * 0.2)  # End near top of visible scrollview
                        scroll_x = location["x"] + (size["width"] // 2)  # Middle of the scrollview width

                        # Perform the scroll - scroll up to show elements below
                        self.driver.swipe(scroll_x, start_y, scroll_x, end_y, 800)
                        logger.info(
                            f"Scrolled ScrollView from ({scroll_x}, {start_y}) to ({scroll_x}, {end_y})"
                        )
                        time.sleep(1)
                except NoSuchElementException:
                    logger.warning("Could not find the ScrollView by ID, trying alternate approach")

                    # Try to find any more tab content
                    try:
                        more_tab_content = self.driver.find_element(
                            AppiumBy.ID, "com.amazon.kindle:id/view_options_tab_content"
                        )
                        if more_tab_content.is_displayed():
                            logger.info(
                                "Found the More tab content, will perform a scroll to see additional settings"
                            )
                            location = more_tab_content.location
                            size = more_tab_content.size

                            # Calculate scroll coordinates
                            start_y = location["y"] + (size["height"] * 0.8)
                            end_y = location["y"] + (size["height"] * 0.2)
                            scroll_x = location["x"] + (size["width"] // 2)

                            # Perform the scroll
                            self.driver.swipe(scroll_x, start_y, scroll_x, end_y, 800)
                            logger.info(
                                f"Scrolled content from ({scroll_x}, {start_y}) to ({scroll_x}, {end_y})"
                            )
                            time.sleep(1)
                    except NoSuchElementException:
                        logger.warning(
                            "Could not find the More tab content, trying fallback to Real-time highlight element"
                        )

                        # Fallback: Use the Real-time Text Highlighting switch as reference point
                        highlight_switch = None
                        for strategy, locator in REALTIME_HIGHLIGHTING_CHECKBOX:
                            try:
                                element = self.driver.find_element(strategy, locator)
                                if element.is_displayed():
                                    highlight_switch = element
                                    break
                            except NoSuchElementException:
                                continue

                        if highlight_switch:
                            # Get the element location
                            location = highlight_switch.location

                            # Calculate scroll coordinates - scroll from this element up
                            start_y = location["y"] + 200  # Well below the element
                            end_y = location["y"] - 400  # Well above the element
                            scroll_x = window_size["width"] // 2

                            # Perform the scroll
                            self.driver.swipe(scroll_x, start_y, scroll_x, end_y, 800)
                            logger.info(
                                f"Scrolled from highlight element ({scroll_x}, {start_y}) to ({scroll_x}, {end_y})"
                            )
                            time.sleep(1)
                        else:
                            # Generic scroll if we can't find any reference points
                            logger.warning("No reference points found for scrolling, using generic scroll")
                            screen_height = window_size["height"]
                            start_y = int(screen_height * 0.8)  # Start at 80% down the screen
                            end_y = int(screen_height * 0.2)  # End at 20% down the screen
                            scroll_x = window_size["width"] // 2

                            # Do a longer, slower scroll to ensure we see more options
                            self.driver.swipe(scroll_x, start_y, scroll_x, end_y, 1000)
                            logger.info(
                                f"Performed generic scroll from ({scroll_x}, {start_y}) to ({scroll_x}, {end_y})"
                            )
                            time.sleep(1)

                # Do a second scroll to ensure we get to the bottom of the options
                # This helps with different screen sizes and UI layouts
                time.sleep(0.5)
                window_size = self.driver.get_window_size()
                start_y2 = int(window_size["height"] * 0.7)
                end_y2 = int(window_size["height"] * 0.3)
                scroll_x2 = window_size["width"] // 2
                self.driver.swipe(scroll_x2, start_y2, scroll_x2, end_y2, 800)
                logger.info(
                    f"Performed second scroll from ({scroll_x2}, {start_y2}) to ({scroll_x2}, {end_y2})"
                )
                time.sleep(1)

            except Exception as e:
                logger.error(f"Error during scrolling: {e}")
                # Continue anyway since some devices might show all options without scrolling

            # Store page source after scrolling
            store_page_source(self.driver.page_source, "style_update_after_scrolling")

            # 7. Disable "About this Book"
            self._toggle_checkbox(ABOUT_BOOK_CHECKBOX, False, "About this Book")

            # 8. Disable "Page Turn Animation"
            self._toggle_checkbox(PAGE_TURN_ANIMATION_CHECKBOX, False, "Page Turn Animation")

            # 9. Disable "Popular Highlights"
            self._toggle_checkbox(POPULAR_HIGHLIGHTS_CHECKBOX, False, "Popular Highlights")

            # 10. Disable "Highlight Menu"
            self._toggle_checkbox(HIGHLIGHT_MENU_CHECKBOX, False, "Highlight Menu")

            # Store page source after all toggles
            store_page_source(self.driver.page_source, "style_update_after_all_toggles")

            # 11. Tap the slideover tab at the top of the style slideover to set it to half-height
            sheet_pill_found = False
            for strategy, locator in STYLE_SHEET_PILL_IDENTIFIERS:
                try:
                    pill = self.driver.find_element(strategy, locator)
                    if pill.is_displayed():
                        pill.click()
                        logger.info("Clicked style sheet pill to set to half-height")
                        sheet_pill_found = True
                        time.sleep(1)
                        break
                except NoSuchElementException:
                    continue

            if not sheet_pill_found:
                logger.warning(
                    "Could not find style sheet pill, will try tapping directly where it should be"
                )
                # Try tapping where the pill would typically be (top center of the slideover)
                try:
                    # Look for the slideover first to get its position
                    slideover_found = False
                    for strategy, locator in STYLE_SLIDEOVER_IDENTIFIERS:
                        try:
                            slideover = self.driver.find_element(strategy, locator)
                            if slideover.is_displayed():
                                # Get the top center of the slideover
                                location = slideover.location
                                size = slideover.size
                                pill_x = location["x"] + size["width"] // 2
                                pill_y = location["y"] + 20  # Near the top

                                self.driver.tap([(pill_x, pill_y)])
                                logger.info(f"Tapped estimated pill location at ({pill_x}, {pill_y})")
                                slideover_found = True
                                time.sleep(1)
                                break
                        except NoSuchElementException:
                            continue

                    if not slideover_found:
                        logger.warning("Could not find style slideover, will try generic tap")
                        # Generic tap near the top of the screen
                        tap_x = window_size["width"] // 2
                        tap_y = window_size["height"] // 4
                        self.driver.tap([(tap_x, tap_y)])
                        logger.info(f"Performed generic tap at ({tap_x}, {tap_y})")
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"Error tapping pill location: {e}")

            # Store page source after pill tap
            store_page_source(self.driver.page_source, "style_update_after_pill_tap")

            # 12. Tap near the top of the screen to hide the style slideover
            top_tap_x = window_size["width"] // 2
            top_tap_y = int(window_size["height"] * 0.1)  # 10% from the top
            self.driver.tap([(top_tap_x, top_tap_y)])
            logger.info(f"Tapped near top of screen at ({top_tap_x}, {top_tap_y}) to hide style slideover")
            time.sleep(1)

            # Store final page source
            store_page_source(self.driver.page_source, "style_update_complete")

            # Even if some steps failed, we've still likely made some improvements
            # Update the profile to indicate styles have been updated
            success = True
            try:
                # Import here to avoid circular imports
                from server.utils.request_utils import get_sindarin_email
                
                # Get email from the request using standard utility function
                email = get_sindarin_email()
                
                if email:
                    if self.profile_manager and self.profile_manager.update_style_preference(True, email):
                        logger.info(f"Successfully updated style preference in profile for {email}")
                    else:
                        logger.warning(f"Failed to update style preference in profile for {email}, may need to retry")
                        # Don't mark as failure, we'll still return success if we've made it this far
                else:
                    logger.warning("No email available from get_sindarin_email() to update style preference")
                    # Don't mark as failure, we'll still return success if we've made it this far
            except Exception as e:
                logger.error(f"Error updating style preference in profile: {e}")
                # Again, don't mark as failure, we'll still return success if we've made it this far

            return success

        except Exception as e:
            logger.error(f"Error updating reading styles: {e}")
            # Store exception page source
            try:
                store_page_source(self.driver.page_source, "style_update_exception")
            except:
                pass
            return False

    def _toggle_checkbox(self, checkbox_strategies, desired_state, description):
        """
        Toggle a checkbox to the desired state.

        Args:
            checkbox_strategies: List of (strategy, locator) tuples for the checkbox
            desired_state: Boolean indicating the desired state (True for checked, False for unchecked)
            description: Description of the checkbox for logging

        Returns:
            bool: True if the operation was successful, False otherwise
        """
        try:
            # Store before page source
            store_page_source(
                self.driver.page_source, f"toggle_{description.lower().replace(' ', '_')}_before"
            )

            checkbox_found = False
            for strategy, locator in checkbox_strategies:
                try:
                    checkbox = self.driver.find_element(strategy, locator)
                    if checkbox.is_displayed():
                        # Try different attributes to determine the current state
                        current_state = None

                        # Try 'checked' attribute first
                        checked_attr = checkbox.get_attribute("checked")
                        if checked_attr is not None:
                            current_state = checked_attr.lower() == "true"

                        # If that didn't work, try 'selected' attribute
                        if current_state is None:
                            selected_attr = checkbox.get_attribute("selected")
                            if selected_attr is not None:
                                current_state = selected_attr.lower() == "true"

                        # Try content-desc which sometimes contains state information
                        if current_state is None:
                            content_desc = checkbox.get_attribute("content-desc")
                            if content_desc:
                                current_state = (
                                    "enabled" in content_desc.lower() or "on" in content_desc.lower()
                                )

                        # Look at the text which might indicate state
                        if current_state is None:
                            text = checkbox.text
                            if text:
                                current_state = "enabled" in text.lower() or "on" in text.lower()

                        # If we still couldn't determine state, make a best guess based on the UI
                        if current_state is None:
                            logger.warning(f"Could not determine state for {description}, assuming it's on")
                            current_state = True  # Assume it's on, so we'll try to turn it off

                        logger.info(f"Current state of {description}: {current_state}")

                        # Only toggle if the current state doesn't match the desired state
                        if current_state != desired_state:
                            checkbox.click()
                            logger.info(f"Toggled {description} from {current_state} to {desired_state}")
                            time.sleep(0.5)  # Short wait for toggle to take effect
                        else:
                            logger.info(f"{description} is already in the desired state ({desired_state})")

                        checkbox_found = True
                        break
                except NoSuchElementException:
                    continue
                except Exception as inner_e:
                    logger.warning(f"Error interacting with {description} element: {inner_e}")
                    continue

            # Try a broader text-based search if the specific strategies failed
            if not checkbox_found:
                try:
                    # Look for a generic Switch or CheckBox with text containing our description
                    logger.info(f"Trying generic search for {description}")
                    # Construct a simple XPath to find a control containing the description text
                    text_parts = description.split()
                    # Create a flexible XPath that checks partial text matches (case-insensitive)
                    xpath = (
                        f"//android.widget.Switch[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{description.lower()}')]"
                        + f"|//android.widget.CheckBox[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{description.lower()}')]"
                    )

                    checkbox = self.driver.find_element(AppiumBy.XPATH, xpath)
                    if checkbox.is_displayed():
                        logger.info(f"Found {description} through generic text search")
                        checkbox.click()
                        logger.info(f"Clicked {description} through generic search")
                        checkbox_found = True
                        time.sleep(0.5)
                except NoSuchElementException:
                    logger.warning(f"Could not find {description} through generic text search either")
                except Exception as text_e:
                    logger.warning(f"Error during text-based search for {description}: {text_e}")

            if not checkbox_found:
                logger.warning(f"Could not find checkbox for {description}")
                return False

            # Store after page source
            store_page_source(
                self.driver.page_source, f"toggle_{description.lower().replace(' ', '_')}_after"
            )
            return True

        except Exception as e:
            logger.error(f"Error toggling {description}: {e}")
            return False
