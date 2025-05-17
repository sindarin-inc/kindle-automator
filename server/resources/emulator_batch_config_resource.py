"""
Resource for batch configuration of all emulators.
This endpoint iterates through all available emulators, applies library and reading settings,
then performs a graceful shutdown with snapshot.
"""

import logging
import time

from flask import jsonify, request
from flask_restful import Resource

from server.utils.ansi_colors import CYAN, GREEN, RED, RESET, YELLOW
from server.utils.emulator_shutdown_manager import EmulatorShutdownManager
from views.core.avd_profile_manager import AVDProfileManager
from views.state_machine import KindleStateMachine

logger = logging.getLogger(__name__)


class EmulatorBatchConfigResource(Resource):
    """
    Batch configuration endpoint for setting up all emulators with library and reading settings.

    POST /batch-configure-emulators
    """

    def __init__(self, server_instance):
        self.server = server_instance

    def post(self):
        """
        Boot each emulator one at a time, apply library/reading settings, then gracefully shutdown.

        The steps for each emulator:
        1. Check if already running - if so, skip to next
        2. Boot the emulator
        3. Navigate to library view
        4. Apply library settings (list view, group_by_series=false)
        5. Open a random book
        6. Apply reading settings
        7. Return to library
        8. Graceful shutdown with snapshot
        """
        try:
            logger.info(f"{CYAN}Starting batch configuration of all emulators{RESET}")

            # Initialize managers
            avd_manager = AVDProfileManager()
            shutdown_manager = EmulatorShutdownManager(self.server)

            # Get all profiles
            all_profiles = avd_manager.list_profiles()

            results = []
            successful_count = 0
            skipped_count = 0
            failed_count = 0

            for profile in all_profiles:
                email = profile.get("email")
                avd_name = profile.get("avd_name")
                emulator_id = profile.get("emulator_id")

                result = {
                    "email": email,
                    "avd_name": avd_name,
                    "status": "pending",
                    "error": None,
                    "steps_completed": [],
                }

                try:
                    # Check if emulator is already running
                    if emulator_id and self._is_emulator_running(emulator_id):
                        logger.info(
                            f"{YELLOW}Emulator already running for {email} ({emulator_id}), skipping{RESET}"
                        )
                        result["status"] = "skipped"
                        result["error"] = "Emulator already running"
                        skipped_count += 1
                        results.append(result)
                        continue

                    # Boot the emulator
                    logger.info(f"{GREEN}Starting emulator for {email}{RESET}")
                    # Use switch_profile to start emulator, same as the successful flow
                    success, message = self.server.switch_profile(email, force_new_emulator=False)

                    if not success:
                        logger.error(f"{RED}Failed to start emulator for {email}: {message}{RESET}")
                        result["status"] = "failed"
                        result["error"] = f"Failed to start emulator: {message}"
                        failed_count += 1
                        results.append(result)
                        continue

                    result["steps_completed"].append("emulator_started")

                    # Wait for emulator to be ready
                    logger.info(f"Waiting for emulator to be ready for {email}")
                    time.sleep(10)  # Give it time to boot

                    # Get the automator for this profile
                    automator = self.server.get_or_create_automator(email)
                    if not automator:
                        logger.error(f"{RED}Failed to create automator for {email}{RESET}")
                        result["status"] = "failed"
                        result["error"] = "Failed to create automator"
                        failed_count += 1
                        results.append(result)
                        continue

                    # Ensure state machine is initialized
                    if not hasattr(automator, "state_machine") or not automator.state_machine:
                        state_machine = KindleStateMachine(automator.driver, automator)
                        automator.state_machine = state_machine

                    # Get reference to state machine
                    state_machine = automator.state_machine

                    # Navigate to library
                    logger.info(f"Navigating to library for {email}")
                    library_state = state_machine.transition_to_library(
                        max_transitions=10, server=self.server
                    )

                    if not library_state:
                        logger.error(f"{RED}Failed to navigate to library for {email}{RESET}")
                        result["status"] = "failed"
                        result["error"] = "Failed to navigate to library"
                        failed_count += 1
                        results.append(result)
                        continue

                    result["steps_completed"].append("library_reached")

                    # Apply library settings
                    logger.info(f"Applying library settings for {email}")
                    library_handler = state_machine.library_handler

                    # First ensure we're in list view
                    if not library_handler._is_library_view_preferences_correctly_set():
                        logger.info(f"Library preferences need to be configured for {email}")

                        # Open the grid/list dialog
                        if library_handler.open_grid_list_view_dialog(force_open=True):
                            # Apply settings
                            if library_handler.handle_grid_list_view_dialog():
                                logger.info(
                                    f"{GREEN}Library settings applied successfully for {email}{RESET}"
                                )
                                result["steps_completed"].append("library_settings_applied")
                            else:
                                logger.error(f"{RED}Failed to apply library settings for {email}{RESET}")
                                result["status"] = "failed"
                                result["error"] = "Failed to apply library settings"
                                failed_count += 1
                                results.append(result)
                                continue
                        else:
                            logger.error(f"{RED}Failed to open grid/list dialog for {email}{RESET}")
                            result["status"] = "failed"
                            result["error"] = "Failed to open grid/list dialog"
                            failed_count += 1
                            results.append(result)
                            continue
                    else:
                        logger.info(f"Library settings already correct for {email}")
                        result["steps_completed"].append("library_settings_verified")

                    # Find and open a random book
                    logger.info(f"Getting book list for {email}")
                    books = library_handler.get_book_titles()

                    if books and len(books) > 0:
                        # Pick the first book (or could randomize)
                        book = books[0]
                        book_title = book.get("title", "Unknown Book")

                        logger.info(f"Opening book '{book_title}' for {email}")

                        # Open the book
                        open_result = library_handler.open_book(book_title)

                        if open_result and open_result.get("success"):
                            result["steps_completed"].append("book_opened")

                            # Apply reading settings
                            logger.info(f"Applying reading settings for {email}")
                            reader_handler = state_machine.reader_handler

                            # The book should already be open, so we just need to update styles
                            style_handler = state_machine.style_handler
                            if style_handler and hasattr(style_handler, "update_reading_style"):
                                if style_handler.update_reading_style(show_placemark=False):
                                    logger.info(
                                        f"{GREEN}Reading settings applied successfully for {email}{RESET}"
                                    )
                                    result["steps_completed"].append("reading_settings_applied")
                                else:
                                    logger.warning(
                                        f"{YELLOW}Failed to apply reading settings for {email}{RESET}"
                                    )

                            # Navigate back to library
                            logger.info(f"Navigating back to library for {email}")
                            if reader_handler.navigate_back_to_library():
                                result["steps_completed"].append("returned_to_library")
                            else:
                                logger.warning(
                                    f"{YELLOW}Failed to navigate back to library for {email}{RESET}"
                                )
                        else:
                            logger.warning(
                                f"{YELLOW}Failed to open book for {email}, continuing anyway{RESET}"
                            )
                    else:
                        logger.warning(
                            f"{YELLOW}No books found for {email}, skipping reading settings{RESET}"
                        )

                    # Perform graceful shutdown with snapshot
                    logger.info(f"Performing graceful shutdown for {email}")
                    shutdown_summary = shutdown_manager.shutdown_emulator(email, preserve_reading_state=False)

                    if shutdown_summary.get("snapshot_taken"):
                        result["steps_completed"].append("snapshot_taken")

                    if shutdown_summary.get("emulator_stopped"):
                        result["steps_completed"].append("emulator_stopped")
                        result["status"] = "success"
                        successful_count += 1
                    else:
                        result["status"] = "partial_success"
                        result["error"] = "Emulator not fully stopped"
                        successful_count += 1  # Still count as success if we got the snapshot

                except Exception as e:
                    logger.error(f"{RED}Error processing {email}: {e}{RESET}")
                    result["status"] = "failed"
                    result["error"] = str(e)
                    failed_count += 1

                results.append(result)

                # Brief pause between emulators
                time.sleep(3)

            # Summary
            summary = {
                "total_profiles": len(all_profiles),
                "successful": successful_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "results": results,
            }

            logger.info(
                f"{GREEN}Batch configuration complete: {successful_count} successful, {skipped_count} skipped, {failed_count} failed{RESET}"
            )

            return jsonify(
                {
                    "status": "success",
                    "message": f"Batch configuration complete for {len(all_profiles)} profiles",
                    "summary": summary,
                }
            )

        except Exception as e:
            logger.error(f"{RED}Error in batch configuration: {e}{RESET}")
            return jsonify({"status": "error", "error": str(e)}), 500

    def _is_emulator_running(self, emulator_id):
        """Check if a specific emulator is running."""
        try:
            # Check if there's an existing automator for this profile
            # First, find the email for this emulator_id
            email = None
            for profile in self.server.profile_manager.list_profiles():
                if profile.get("emulator_id") == emulator_id:
                    email = profile.get("email")
                    break

            if email and email in self.server.automators:
                automator = self.server.automators[email]
                if automator and hasattr(automator, "driver") and automator.driver:
                    # There's an active automator, emulator is likely running
                    return True

            # Fallback to basic ADB check
            import subprocess

            result = subprocess.run(
                [f"{self.server.android_home}/platform-tools/adb", "devices"],
                capture_output=True,
                text=True,
                check=False,
            )
            return emulator_id in result.stdout
        except Exception as e:
            logger.error(f"Error checking if emulator is running: {e}")
            return False
