import logging
import subprocess
import time
import traceback
from functools import wraps

import flask
from flask import Response
from selenium.common import exceptions as selenium_exceptions

from server.utils.request_utils import get_sindarin_email

logger = logging.getLogger(__name__)


def ensure_automator_healthy(f):
    """Decorator to ensure automator is initialized and healthy before each operation.
    Works with the multi-emulator approach by getting the sindarin_email from the request.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        # Access server instance from the Flask app
        from flask import current_app as app

        server = app.config["server_instance"]

        max_retries = 2  # Allow retries for UiAutomator2 crashes

        # Get sindarin_email from request to determine which automator to use
        sindarin_email = get_sindarin_email()

        # If we still don't have an email after checking current_email, try the current profile
        if not sindarin_email:
            # Try to get from current profile
            current_profile = server.profile_manager.get_current_profile()
            if current_profile:
                sindarin_email = current_profile.get("email")
                logger.debug(f"Using email from current profile: {sindarin_email}")

        if not sindarin_email:
            logger.error("No sindarin_email found in request or current state")
            return {"error": "No email provided to identify which profile to use"}, 400

        # Update activity timestamp for this email
        server.update_activity(sindarin_email)

        # Proactively check for stale Appium processes before attempting operations
        try:
            from server.utils.appium_driver import AppiumDriver

            appium_driver = AppiumDriver.get_instance()
            appium_info = appium_driver.get_appium_process_info(sindarin_email)

            if appium_info and appium_info.get("running"):
                # Check if it's actually healthy
                if not appium_driver._check_appium_health(sindarin_email):
                    logger.warning(
                        f"Detected stale Appium process for {sindarin_email} before operation, cleaning up"
                    )
                    appium_driver.stop_appium_for_profile(sindarin_email)
                    # Clear the automator as well since it has a stale driver
                    if sindarin_email in server.automators and server.automators[sindarin_email]:
                        server.automators[sindarin_email].cleanup()
                        server.automators[sindarin_email] = None
        except Exception as e:
            logger.warning(f"Error checking for stale Appium processes: {e}")

        for attempt in range(max_retries):
            try:
                # Get the automator for this email
                automator = server.automators.get(sindarin_email)

                # Initialize automator if needed
                if not automator:
                    logger.info(f"No automator found for {sindarin_email}. Initializing automatically...")
                    automator = server.initialize_automator(sindarin_email)
                    if not automator:
                        logger.error(f"Failed to initialize automator for {sindarin_email}")
                        return {"error": f"Failed to initialize automator for {sindarin_email}"}, 500

                    if not automator.initialize_driver():
                        logger.error(f"Failed to initialize driver for {sindarin_email}")
                        return {
                            "error": (
                                f"Failed to initialize driver for {sindarin_email}. Call /initialize first."
                            )
                        }, 500

                # Ensure driver is running
                if not automator.ensure_driver_running():
                    logger.error(f"Failed to ensure driver is running for {sindarin_email}")
                    return {"error": f"Failed to ensure driver is running for {sindarin_email}"}, 500

                # Execute the function
                result = f(*args, **kwargs)

                # Special handling for Flask Response objects to prevent JSON serialization errors
                if isinstance(result, (flask.Response, Response)):
                    return result

                return result

            except Exception as e:
                # Check if it's the UiAutomator2 server crash error or other common crash patterns
                error_message = str(e)
                # Check for lost driver session errors (Appium specific)
                is_lost_session = any(
                    [
                        "The session identified by" in error_message and "is not known" in error_message,
                        "NoSuchDriverException" in error_message,
                    ]
                )
                # Check the specific exception type as well as the message
                is_driver_error = (
                    isinstance(
                        e, (selenium_exceptions.NoSuchDriverException, selenium_exceptions.WebDriverException)
                    )
                    if hasattr(selenium_exceptions, "NoSuchDriverException")
                    else isinstance(e, selenium_exceptions.WebDriverException)
                )
                is_uiautomator_crash = (
                    is_driver_error
                    or is_lost_session
                    or any(
                        [
                            "cannot be proxied to UiAutomator2 server because the instrumentation process is not running"
                            in error_message,
                            "instrumentation process is not running" in error_message,
                            "Failed to establish a new connection" in error_message,
                            "Connection refused" in error_message,
                            "Connection reset by peer" in error_message,
                            "A session is either terminated or not started" in error_message,
                            "NoSuchDriverError" in error_message,
                            "InvalidSessionIdException" in error_message,
                            "Could not proxy command to the remote server" in error_message,
                            "socket hang up" in error_message,
                            "NoSuchContextException" in error_message,
                            "InvalidContextError" in error_message,
                        ]
                    )
                )

                if is_uiautomator_crash and attempt < max_retries - 1:
                    logger.warning("\n" + "=" * 80)
                    logger.warning(
                        f"🔄 RETRY: UiAutomator2 server crashed on attempt {attempt + 1}/{max_retries}. Restarting driver..."
                    )
                    logger.warning(f"Crash error: {error_message}")
                    logger.warning("=" * 80 + "\n")

                    # Kill any leftover UiAutomator2 processes directly via ADB
                    try:
                        automator = server.automators.get(sindarin_email)
                        if automator and automator.device_id:
                            device_id = automator.device_id
                            logger.info(f"Forcibly killing UiAutomator2 processes on device {device_id}")
                            # Kill uiautomator processes
                            subprocess.run(
                                [f"adb -s {device_id} shell pkill -f uiautomator"],
                                shell=True,
                                check=False,
                                timeout=5,
                            )
                            # Also kill any processes using the system port
                            subprocess.run(
                                [f"adb -s {device_id} shell pkill -f 'uiautomator2.*8201'"],
                                shell=True,
                                check=False,
                                timeout=5,
                            )
                            # Forward --remove-all to clear port forwards
                            subprocess.run(
                                [f"adb -s {device_id} forward --remove-all"],
                                shell=True,
                                check=False,
                                timeout=5,
                            )
                            time.sleep(2)  # Give it time to fully terminate
                    except Exception as kill_e:
                        logger.warning(f"Error while killing UiAutomator2 processes: {kill_e}")

                    # Force a complete driver restart for this email
                    automator = server.automators.get(sindarin_email)
                    if automator:
                        logger.info(f"Cleaning up automator resources for {sindarin_email}")
                        automator.cleanup()
                        server.automators[sindarin_email] = None

                    # Reset Appium server state for this specific email
                    try:
                        logger.info(f"Resetting Appium server state for email {sindarin_email}")

                        from server.utils.appium_driver import AppiumDriver
                        from server.utils.port_utils import get_appium_port_for_email
                        from server.utils.vnc_instance_manager import VNCInstanceManager

                        vnc_manager = VNCInstanceManager.get_instance()
                        appium_driver = AppiumDriver.get_instance()

                        # Check if Appium is running but not healthy (stale process)
                        appium_info = appium_driver.get_appium_process_info(sindarin_email)
                        if appium_info and appium_info.get("running"):
                            # Check if it's actually healthy
                            if not appium_driver._check_appium_health(sindarin_email):
                                logger.warning(
                                    f"Found stale Appium process for {sindarin_email}, stopping it"
                                )
                                appium_driver.stop_appium_for_profile(sindarin_email)
                                time.sleep(2)

                        port = get_appium_port_for_email(
                            sindarin_email,
                            vnc_manager=vnc_manager,
                            profiles_index=server.profile_manager.profiles_index,
                        )
                        logger.info(f"Using Appium port {port} for {sindarin_email}")

                        # If port wasn't already stored, store it for future use
                        if not server.profile_manager.get_appium_port_for_email(sindarin_email):
                            # Store this port in the profile for future use
                            if hasattr(server.profile_manager, "register_profile"):
                                # Get the AVD name for this email
                                avd_name = server.profile_manager.get_avd_for_email(sindarin_email)
                                if avd_name:
                                    # Get existing VNC instance if any
                                    vnc_instance = server.profile_manager.get_vnc_instance_for_email(
                                        sindarin_email
                                    )
                                    # Register the profile with the new port
                                    server.profile_manager.register_profile(
                                        email=sindarin_email,
                                        avd_name=avd_name,
                                        vnc_instance=vnc_instance,
                                        appium_port=port,
                                    )
                                    logger.info(f"Stored Appium port {port} for {sindarin_email} in profile")

                        # Start a dedicated Appium server for this email
                        if not appium_driver.start_appium_for_profile(sindarin_email):
                            logger.error(f"Failed to restart Appium server for {sindarin_email}")
                            return {"error": f"Failed to start Appium server for {sindarin_email}"}, 500

                        time.sleep(2)  # Wait for the Appium server to start
                    except Exception as appium_e:
                        logger.warning(f"Error while resetting Appium for {sindarin_email}: {appium_e}")

                    # Try to switch back to the profile
                    success, message = server.switch_profile(sindarin_email)
                    if not success:
                        logger.error(f"Failed to switch back to profile: {message}")
                        return {"error": f"Failed to switch back to profile: {message}"}, 500

                    automator = server.initialize_automator(sindarin_email)
                    # Clear current book since we're restarting the driver
                    server.clear_current_book(sindarin_email)

                    if automator and automator.initialize_driver():
                        logger.info("\n" + "=" * 80)
                        logger.info(
                            "✅ RETRY: Successfully restarted driver after UiAutomator2 crash, retrying operation..."
                        )
                        logger.info("=" * 80 + "\n")
                        continue  # Retry the operation with the next loop iteration
                    else:
                        logger.error("Failed to restart driver after UiAutomator2 crash")

                # For non-UiAutomator2 crashes or if restart failed, log and return error
                logger.error(f"Error in operation (attempt {attempt + 1}/{max_retries}): {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")

                # On the last attempt, return the error
                if attempt == max_retries - 1:
                    return {"error": str(e)}, 500

    return wrapper
