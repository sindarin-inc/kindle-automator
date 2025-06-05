"""Logout resource for signing out of the Kindle app."""

import logging
import os
import time
import traceback

from appium.webdriver.common.appiumby import AppiumBy
from flask import request
from flask_restful import Resource
from selenium.common import exceptions as selenium_exceptions

from server.logging_config import store_page_source
from server.middleware.automator_middleware import ensure_automator_healthy
from server.middleware.profile_middleware import ensure_user_profile_loaded
from server.middleware.response_handler import handle_automator_response
from server.utils.request_utils import get_automator_for_request, get_sindarin_email
from views.core.app_state import AppState

logger = logging.getLogger(__name__)


class LogoutResource(Resource):
    def __init__(self, **kwargs):
        self.server_instance = kwargs.get("server_instance")
        super().__init__()

    @ensure_user_profile_loaded
    @ensure_automator_healthy
    @handle_automator_response(None)
    def _logout(self):
        """Sign out of the Kindle app"""
        # Get server instance from the request context if not provided
        server = self.server_instance or request.app.config.get("server_instance")

        automator, _, error_response = get_automator_for_request(server)
        if error_response:
            return error_response

        try:
            # First check current state
            current_state = automator.state_machine.update_current_state()
            logger.info(f"Current state before logout: {current_state}")

            # Navigate to MORE tab if not already there
            if current_state != AppState.MORE_SETTINGS:
                logger.info("Navigating to MORE tab")

                # Try to click the MORE tab
                from views.more.interaction_strategies import MORE_TAB_STRATEGIES

                tab_found = False
                for strategy, locator in MORE_TAB_STRATEGIES:
                    try:
                        more_tab = automator.driver.find_element(strategy, locator)
                        if more_tab.is_displayed():
                            more_tab.click()
                            tab_found = True
                            logger.info("Successfully clicked MORE tab")
                            time.sleep(1)  # Wait for tab to load
                            break
                    except selenium_exceptions.NoSuchElementException:
                        continue

                if not tab_found:
                    logger.error("Failed to find MORE tab")
                    return {"error": "Failed to navigate to MORE tab"}, 500

                # Update state after navigation
                current_state = automator.state_machine.update_current_state()
                if current_state != AppState.MORE_SETTINGS:
                    logger.error(f"Failed to reach MORE_SETTINGS state, current state: {current_state}")
                    return {
                        "error": f"Failed to reach MORE settings, current state: {current_state.name}"
                    }, 500

            # Now we're in MORE_SETTINGS, find and click Sign Out
            logger.info("Looking for Sign Out button")

            from views.more.interaction_strategies import MORE_MENU_ITEM_STRATEGIES

            sign_out_clicked = False
            for strategy, locator in MORE_MENU_ITEM_STRATEGIES.get("sign_out", []):
                try:
                    sign_out_button = automator.driver.find_element(strategy, locator)
                    if sign_out_button.is_displayed():
                        sign_out_button.click()
                        sign_out_clicked = True
                        logger.info("Successfully clicked Sign Out button")
                        break
                except selenium_exceptions.NoSuchElementException:
                    continue
                except Exception as e:
                    logger.warning(f"Error clicking sign out with strategy {strategy}: {e}")
                    continue

            if not sign_out_clicked:
                # Try scrolling down to find the Sign Out button
                logger.info("Sign Out button not immediately visible, scrolling down")

                # Get the list view and scroll it
                try:
                    list_view = automator.driver.find_element(
                        AppiumBy.ID, "com.amazon.kindle:id/items_screen_list"
                    )

                    # Scroll down a few times to find Sign Out
                    for i in range(3):
                        logger.info(f"Scroll attempt {i+1}")
                        # Use swipe gesture for mobile scrolling
                        # Get screen dimensions
                        screen_size = automator.driver.get_window_size()
                        start_x = screen_size["width"] // 2
                        start_y = screen_size["height"] * 0.8
                        end_y = screen_size["height"] * 0.2

                        # Swipe up to scroll down
                        automator.driver.swipe(start_x, start_y, start_x, end_y, duration=500)
                        time.sleep(0.5)

                        # Try to find Sign Out button again
                        for strategy, locator in MORE_MENU_ITEM_STRATEGIES.get("sign_out", []):
                            try:
                                sign_out_button = automator.driver.find_element(strategy, locator)
                                if sign_out_button.is_displayed():
                                    sign_out_button.click()
                                    sign_out_clicked = True
                                    logger.info("Successfully clicked Sign Out button after scrolling")
                                    break
                            except selenium_exceptions.NoSuchElementException:
                                continue

                        if sign_out_clicked:
                            break

                except Exception as e:
                    logger.error(f"Error scrolling to find Sign Out button: {e}")

            if not sign_out_clicked:
                logger.error("Failed to find or click Sign Out button")
                # Store diagnostics
                try:
                    page_source = automator.driver.page_source
                    store_page_source(page_source, "logout_failed")
                except Exception as ps_error:
                    logger.error(f"Failed to store page source: {ps_error}")
                automator.driver.save_screenshot(os.path.join(automator.screenshots_dir, "logout_failed.png"))
                return {"error": "Failed to find Sign Out button"}, 500

            # Wait for the confirmation dialog to appear
            time.sleep(1)

            # Look for the confirmation dialog
            confirm_dialog_found = False
            try:
                # Check for "Confirm sign out" dialog title
                dialog_title = automator.driver.find_element(AppiumBy.ID, "com.amazon.kindle:id/alertTitle")
                if dialog_title.is_displayed() and "Confirm sign out" in dialog_title.text:
                    logger.info("Found 'Confirm sign out' dialog")
                    confirm_dialog_found = True
            except selenium_exceptions.NoSuchElementException:
                # Also try by text
                try:
                    dialog_title = automator.driver.find_element(
                        AppiumBy.XPATH, "//android.widget.TextView[@text='Confirm sign out']"
                    )
                    if dialog_title.is_displayed():
                        logger.info("Found 'Confirm sign out' dialog by text")
                        confirm_dialog_found = True
                except selenium_exceptions.NoSuchElementException:
                    pass

            if confirm_dialog_found:
                # Click the SIGN OUT button in the dialog
                logger.info("Clicking SIGN OUT button in confirmation dialog")
                sign_out_confirm_clicked = False

                # Try to find the SIGN OUT button (button1)
                try:
                    sign_out_confirm = automator.driver.find_element(AppiumBy.ID, "android:id/button1")
                    if sign_out_confirm.is_displayed():
                        sign_out_confirm.click()
                        sign_out_confirm_clicked = True
                        logger.info("Clicked SIGN OUT confirmation button (button1)")
                except selenium_exceptions.NoSuchElementException:
                    pass

                if not sign_out_confirm_clicked:
                    # Try by text
                    try:
                        sign_out_confirm = automator.driver.find_element(
                            AppiumBy.XPATH, "//android.widget.Button[@text='SIGN OUT']"
                        )
                        if sign_out_confirm.is_displayed():
                            sign_out_confirm.click()
                            sign_out_confirm_clicked = True
                            logger.info("Clicked SIGN OUT confirmation button by text")
                    except selenium_exceptions.NoSuchElementException:
                        pass

                if not sign_out_confirm_clicked:
                    logger.error("Failed to click SIGN OUT button in confirmation dialog")
                    try:
                        page_source = automator.driver.page_source
                        store_page_source(page_source, "logout_confirm_failed")
                    except Exception as ps_error:
                        logger.error(f"Failed to store page source: {ps_error}")
                    automator.driver.save_screenshot(
                        os.path.join(automator.screenshots_dir, "logout_confirm_failed.png")
                    )
                    return {"error": "Failed to confirm sign out"}, 500

                # Wait for the logout to complete after confirmation
                time.sleep(2)
            else:
                # No confirmation dialog, just wait for logout to process
                time.sleep(1)

            # Check if we've reached the sign-in screen
            new_state = automator.state_machine.update_current_state()
            logger.info(f"State after logout: {new_state}")

            if new_state == AppState.SIGN_IN:
                logger.info("Successfully signed out - now at sign-in screen")

                # Clear the current book tracking
                sindarin_email = get_sindarin_email()
                if sindarin_email:
                    server.clear_current_book(sindarin_email)

                return {
                    "success": True,
                    "message": "Successfully signed out",
                    "current_state": new_state.name,
                }, 200
            elif new_state == AppState.HOME:
                # Sometimes the app goes to HOME after logout, especially if there's auto-login
                logger.info("Logout completed but app returned to HOME state - may have auto-login enabled")

                # Clear the current book tracking
                sindarin_email = get_sindarin_email()
                if sindarin_email:
                    server.clear_current_book(sindarin_email)

                return {
                    "success": True,
                    "message": "Successfully signed out",
                    "current_state": new_state.name,
                    "note": "App returned to HOME state after logout - may have auto-login enabled",
                }, 200
            else:
                logger.warning(f"Logout may have succeeded but unexpected state: {new_state}")

                # Still clear the current book tracking as logout was attempted
                sindarin_email = get_sindarin_email()
                if sindarin_email:
                    server.clear_current_book(sindarin_email)

                return {
                    "success": True,
                    "message": "Sign out button clicked",
                    "current_state": new_state.name,
                    "warning": "Unexpected state after logout",
                }, 200

        except Exception as e:
            logger.error(f"Error during logout: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Store diagnostics
            try:
                page_source = automator.driver.page_source
                store_page_source(page_source, "logout_error")
            except Exception as ps_error:
                logger.error(f"Failed to store page source: {ps_error}")
            automator.driver.save_screenshot(os.path.join(automator.screenshots_dir, "logout_error.png"))
            return {"error": f"Failed to logout: {str(e)}"}, 500

    def get(self):
        """Handle GET request for logout"""
        return self._logout()

    def post(self):
        """Handle POST request for logout"""
        return self._logout()
