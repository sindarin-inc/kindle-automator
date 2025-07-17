"""Manager for gracefully shutting down emulators."""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import signal
import subprocess
import time
import traceback
from datetime import datetime
from typing import Dict, Optional

from selenium.common.exceptions import InvalidSessionIdException

from server.utils.vnc_instance_manager import VNCInstanceManager
from views.core.app_state import AppState
from views.state_machine import KindleStateMachine

logger = logging.getLogger(__name__)


class EmulatorShutdownManager:
    """Manages graceful shutdown of emulators."""

    #: Keys expected by downstream callers in the returned shutdown summary
    _SUMMARY_KEYS = (
        "email",
        "emulator_stopped",
        "vnc_stopped",
        "xvfb_stopped",
        "websocket_stopped",
        "automator_cleaned",
        "snapshot_taken",
        "placemark_sync_attempted",
        "placemark_sync_success",
    )

    # ---------------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------------

    def __init__(self, server_instance):
        self.server = server_instance

    # ------------------------------------------------------------------
    # External API ––– keep signature unchanged
    # ------------------------------------------------------------------

    def shutdown_emulator(  # noqa: C901 (complexity is acceptable for entry‑point)
        self,
        email: str,
        preserve_reading_state: bool = False,
        mark_for_restart: Optional[bool] = None,
        skip_snapshot: bool = False,
    ) -> Dict[str, bool]:
        """Gracefully shut down the emulator attached to *email*.

        Args:
            email: Profile email.
            preserve_reading_state: Skip navigation to Library before snapshot.
            mark_for_restart: Persist running flag for deployment restarts.  If *None*,
                falls back to *preserve_reading_state* for backwards compatibility.
            skip_snapshot: Skip taking a snapshot before shutdown (for cold boot).

        Returns
        -------
        Dict[str, bool]
            A summary of work performed keyed by ``_SUMMARY_KEYS``.
        """
        summary = {key: False for key in self._SUMMARY_KEYS}
        summary["email"] = email

        import time as _time

        start_time = _time.time()
        logger.info(
            "Processing shutdown request for %s (preserve_reading_state=%s, mark_for_restart=%s, skip_snapshot=%s)",
            email,
            preserve_reading_state,
            mark_for_restart,
            skip_snapshot,
        )

        # ------------------------------------------------------------------
        # 1. Update "was_running_at_restart" flag                     ──────
        # ------------------------------------------------------------------
        self._mark_for_restart(email, mark_for_restart)

        # ------------------------------------------------------------------
        # 2. Obtain automator or fall back to orphan‑handling          ──────
        # ------------------------------------------------------------------
        automator = self.server.automators.get(email)
        if automator is None:
            return self._handle_orphaned_emulator(email, summary)

        # ------------------------------------------------------------------
        # 3. UI navigation (navigate to library if needed)             ──────
        # ------------------------------------------------------------------
        ui_nav_start = _time.time()
        ui_crashed = not self._navigate_to_library_if_needed(
            automator,
            email,
            preserve_reading_state,
            summary,
        )
        logger.info(f"UI navigation took {_time.time() - ui_nav_start:.1f}s for {email}")

        # ------------------------------------------------------------------
        # 4. Take snapshot (always attempt, even if UI crashed)        ──────
        # ------------------------------------------------------------------
        if not skip_snapshot:
            snapshot_start = _time.time()
            self._take_snapshot(automator, email, summary)
            logger.info(f"Snapshot attempt took {_time.time() - snapshot_start:.1f}s for {email}")
        else:
            logger.info(f"Skipping snapshot for {email} as requested (cold boot)")

        # ------------------------------------------------------------------
        # 5. Stop emulator + auxiliary processes                       ──────
        # ------------------------------------------------------------------
        stop_emulator_start = _time.time()
        display_num: Optional[int] = None
        try:
            display_num = self._stop_emulator_processes(automator, email, summary)
            logger.info(f"Stop emulator processes took {_time.time() - stop_emulator_start:.1f}s for {email}")
        finally:
            # Always cleanup ports even when stop_emulator raised.
            emulator_id = automator.emulator_manager.emulator_launcher.get_running_emulator(email)[0]
            if emulator_id:
                self._cleanup_emulator_ports(emulator_id, email)
            else:
                logger.info(f"No emulator ID found for cleanup of email={email}")

        # ------------------------------------------------------------------
        # 6. Platform‑specific VNC / Xvfb / WebSocket cleanup           ──────
        # ------------------------------------------------------------------
        cleanup_display_start = _time.time()
        self._cleanup_display_resources(email, display_num, summary)
        logger.info(f"Display resource cleanup took {_time.time() - cleanup_display_start:.1f}s for {email}")

        # ------------------------------------------------------------------
        # 7. Final in‑memory cleanups                                   ──────
        # ------------------------------------------------------------------
        cleanup_automator_start = _time.time()
        self._cleanup_automator(email, automator, summary)
        self.server.clear_current_book(email)
        logger.info(f"Automator cleanup took {_time.time() - cleanup_automator_start:.1f}s for {email}")

        logger.info(f"Total shutdown took {_time.time() - start_time:.1f}s for {email}")
        return summary

    def shutdown_all_emulators(self, preserve_reading_state: bool = False):  # noqa: D401, ANN001
        """Shutdown every running emulator and return per‑emulator summaries."""
        logger.info(
            "Starting graceful shutdown of all running emulators (preserve_reading_state=%s)",
            preserve_reading_state,
        )
        summaries = []
        for email in [e for e, a in self.server.automators.items() if a]:
            summaries.append(self.shutdown_emulator(email, preserve_reading_state))
            time.sleep(1)  # Avoid resource contention between successive shutdowns.
        logger.info("Completed shutdown of %d emulators", len(summaries))
        return summaries

    # ------------------------------------------------------------------
    # Private helpers – orchestration                                   ──────
    # ------------------------------------------------------------------

    @staticmethod
    def _mark_for_restart(email: str, mark_for_restart: Optional[bool]):
        """Persist *was_running_at_restart* flag through the VNC manager."""
        with contextlib.suppress(Exception):
            VNCInstanceManager.get_instance().mark_running_for_deployment(
                email, should_restart=mark_for_restart
            )

    # ----------------------- orphan‑handling ------------------------ #

    def _handle_orphaned_emulator(self, email: str, summary: Dict[str, bool]):  # noqa: C901
        """Stop an emulator that is still running but has no live automator."""
        vnc_manager = VNCInstanceManager.get_instance()
        vnc_instance = vnc_manager.get_instance_for_profile(email)
        if not vnc_instance or not vnc_instance.get("emulator_id"):
            logger.info("No running emulator found in VNC instance manager for %s", email)
            return summary

        emulator_id = vnc_instance["emulator_id"]
        logger.info("Found orphaned emulator %s for %s", emulator_id, email)
        with contextlib.suppress(Exception):
            from views.core.avd_profile_manager import AVDProfileManager

            pm = AVDProfileManager.get_instance()
            if pm.emulator_manager and pm.emulator_manager.emulator_launcher:
                stopped = pm.emulator_manager.emulator_launcher.stop_emulator(email)
                summary["emulator_stopped"] = stopped
                if not stopped:
                    # Force kill using the port extracted from ``emulator_id``.
                    port = emulator_id.split("-")[1] if emulator_id.startswith("emulator-") else None
                    if port:
                        self._force_kill_emulator_process(port)
                        summary["emulator_stopped"] = True
                vnc_manager.clear_emulator_id_for_profile(email)
        # Release VNC regardless of stop result.
        with contextlib.suppress(Exception):
            if vnc_manager.release_instance_from_profile(email):
                summary["vnc_stopped"] = True
                summary["websocket_stopped"] = True
        return summary

    # -------------------- UI preparation + snapshot ----------------- #

    def _navigate_to_library_if_needed(
        self,
        automator,
        email: str,
        preserve_reading_state: bool,
        summary: Dict[str, bool],
    ) -> bool:
        """Navigate to Library if not preserving reading state and driver is available."""
        try:
            driver = automator.driver
            if not driver:
                logger.info(f"No driver available for {email}, skipping library navigation")
                return True  # Not an error - we can still take snapshots
            if not automator.state_machine:
                automator.state_machine = KindleStateMachine(driver)
        except InvalidSessionIdException:
            logger.warning("Emulator for %s has no valid session ID, skipping library navigation", email)
            return False
        except Exception as exc:
            # If UiAutomator crashed, we can't navigate but can still snapshot
            logger.error(
                "UiAutomator2 crashed for %s during navigation attempt: %s", email, exc, exc_info=True
            )
            return False

        if not preserve_reading_state:
            self._park_in_library(automator.state_machine, email, summary)
        return True

    def _park_in_library(
        self, state_machine: KindleStateMachine, email: str, summary: Dict[str, bool]
    ) -> None:
        """Navigate from any state into the Library view and optionally sync progress."""
        try:
            current_state = state_machine._get_current_state()
            was_reading = current_state == AppState.READING
            logger.info(f"Current state before shutdown: {current_state.name} for {email}")

            if was_reading:
                logger.info(
                    f"User {email} was reading - will attempt to sync placemarks after navigating to library"
                )
                summary["placemark_sync_attempted"] = True

            final_state = state_machine.transition_to_library(max_transitions=10, server=self.server)
            if final_state == AppState.LIBRARY:
                logger.info("Successfully transitioned to Library view (%s)", email)
                if was_reading and state_machine.library_handler:
                    logger.info(f"Initiating placemark sync for {email} since they were reading...")
                    sync_success = self._sync_from_more_tab(state_machine)
                    summary["placemark_sync_success"] = sync_success
                elif was_reading and not state_machine.library_handler:
                    logger.error(
                        f"User {email} was reading but no library handler available - CANNOT SYNC PLACEMARKS!",
                        exc_info=True,
                    )
                    summary["placemark_sync_success"] = False
                time.sleep(1)  # Give Kindle a moment to flush state.
            else:
                logger.warning(
                    "Failed to transition to Library before shutdown (%s), ended in state: %s",
                    email,
                    final_state.name,
                )
                if was_reading:
                    logger.error(
                        f"User {email} was reading but failed to reach library - PLACEMARKS NOT SYNCED!",
                        exc_info=True,
                    )
                    summary["placemark_sync_success"] = False
        except Exception as exc:
            logger.error(f"Error while parking emulator {email} into Library: {exc}", exc_info=True)
            logger.error(
                f"CRITICAL: Shutdown navigation failed for {email} - placemarks may not be synced!",
                exc_info=True,
            )
            if summary.get("placemark_sync_attempted"):
                summary["placemark_sync_success"] = False

    @staticmethod
    def _sync_from_more_tab(state_machine: KindleStateMachine) -> bool:
        """Navigate to *More* tab and perform a manual sync.

        Returns:
            bool: True if sync was successful, False otherwise
        """
        lh = state_machine.library_handler
        if not lh:
            logger.warning("No library handler available for sync - cannot sync placemarks")
            return False

        logger.info("Attempting to sync placemarks before shutdown...")

        # Navigate to More tab
        if not lh.navigate_to_more_settings():
            logger.error(
                "Failed to navigate to More tab for sync - placemarks may not be synced!", exc_info=True
            )
            return False

        # Attempt sync
        sync_success = lh.sync_in_more_tab()
        if sync_success:
            logger.info("Successfully synced reading progress/placemarks before shutdown")
        else:
            logger.error("SYNC FAILED during shutdown - user's placemarks may not be saved!", exc_info=True)
            # Store diagnostic information
            try:
                from server.logging_config import store_page_source

                store_page_source(state_machine.driver.page_source, "sync_failure_during_shutdown")
                logger.error("Diagnostic page source saved for sync failure", exc_info=True)
            except Exception as e:
                logger.error(f"Failed to save diagnostic information: {e}", exc_info=True)

        # Always try to navigate back to library
        if not lh.navigate_from_more_to_library():
            logger.warning("Failed to navigate back to library after sync attempt")

        return sync_success

    # ----------------------------- snapshot ------------------------ #

    def _take_snapshot(self, automator, email: str, summary: Dict[str, bool]):
        launcher = automator.emulator_manager.emulator_launcher
        emulator_id, _ = launcher.get_running_emulator(email)
        if not emulator_id:
            logger.error(
                f"SNAPSHOT FAILURE: No emulator ID found for {email} - cannot take snapshot", exc_info=True
            )
            return
        logger.info(f"Taking ADB snapshot of emulator {emulator_id} for {email}")
        snapshot_start_time = time.time()
        if launcher.save_snapshot(email):
            summary["snapshot_taken"] = True
            self._update_snapshot_timestamp(email)
            logger.info(
                f"Snapshot completed successfully for {email} in {time.time() - snapshot_start_time:.1f}s"
            )
        else:
            logger.critical(
                f"SNAPSHOT FAILURE: Failed to save snapshot for {email} - user's reading position may be lost! "
                f"This will cause cold boot on next launch."
            )

    @staticmethod
    def _update_snapshot_timestamp(email: str):
        """Persist the default_boot snapshot timestamp to the user's AVD profile."""
        with contextlib.suppress(Exception):
            from views.core.avd_profile_manager import AVDProfileManager

            ts = datetime.now().isoformat()
            avd_mgr = AVDProfileManager.get_instance()
            avd_mgr.set_user_field(email, "last_snapshot_timestamp", ts)
            avd_mgr.set_user_field(email, "last_snapshot", None)
            logger.info("Updated default_boot snapshot timestamp to %s for %s", ts, email)

    # ------------------- stop emulator + processes ------------------ #

    def _stop_emulator_processes(self, automator, email: str, summary: Dict[str, bool]) -> Optional[int]:
        """Stop the running emulator and return its display number (if any)."""
        launcher = automator.emulator_manager.emulator_launcher
        emulator_id, display_num = None, None
        try:
            emulator_id, display_num = launcher.get_running_emulator(email)
        except Exception as exc:
            logger.error("Error getting running emulator info for %s: %s", email, exc, exc_info=True)
        finally:
            stopped = launcher.stop_emulator(email)
            summary["emulator_stopped"] = stopped
            if stopped:
                with contextlib.suppress(Exception):
                    VNCInstanceManager.get_instance().clear_emulator_id_for_profile(email)
        return display_num

    # ---------------------- resource cleanup ----------------------- #

    def _cleanup_display_resources(
        self,
        email: str,
        display_num: Optional[int],
        summary: Dict[str, bool],
    ) -> None:
        """Stop VNC/Xvfb/WebSocket resources depending on host platform."""
        if platform.system() == "Darwin":
            with contextlib.suppress(Exception):
                vnc_mgr = VNCInstanceManager.get_instance()
                vnc_mgr.release_instance_from_profile(email)
                summary["websocket_stopped"] = True
        elif display_num is not None:
            self._stop_vnc_xvfb(display_num, summary)
            with contextlib.suppress(Exception):
                VNCInstanceManager.get_instance().release_instance_from_profile(email)

    @staticmethod
    def _stop_vnc_xvfb(display_num: int, summary: Dict[str, bool]):
        """Terminate *x11vnc* and *Xvfb* processes tied to *display_num*."""
        from server.utils.port_utils import calculate_vnc_port

        vnc_port = calculate_vnc_port(display_num)
        # Use more specific patterns that match the actual command line format
        # The VNC process has "-rfbport 5901" (with dash), and we need to match the exact port
        for cmd, key in (
            (["pkill", "-f", f"x11vnc.*-rfbport {vnc_port}"], "vnc_stopped"),
            (["pkill", "-f", f"Xvfb :{display_num}"], "xvfb_stopped"),
        ):
            with contextlib.suppress(Exception):
                subprocess.run(cmd, check=False, timeout=3)
                summary[key] = True

        # Double-check VNC is actually killed - sometimes pkill doesn't work
        time.sleep(0.5)
        vnc_check = subprocess.run(
            ["pgrep", "-f", f"x11vnc.*-rfbport {vnc_port}"], capture_output=True, text=True
        )
        if vnc_check.returncode == 0 and vnc_check.stdout.strip():
            # VNC still running, force kill
            logger.warning(f"VNC process still running on port {vnc_port} after pkill, force killing")
            pids = vnc_check.stdout.strip().split("\n")
            for pid in pids:
                with contextlib.suppress(Exception):
                    subprocess.run(["kill", "-9", pid], check=False)
                    summary["vnc_stopped"] = True

        # Remove potential lock files left by Xvfb.
        with contextlib.suppress(Exception):
            subprocess.run(
                ["rm", "-f", f"/tmp/.X{display_num}-lock", f"/tmp/.X11-unix/X{display_num}"],
                check=False,
            )

    def _cleanup_automator(self, email: str, automator, summary: Dict[str, bool]):
        """Stop Appium (if still running) and cleanup automator instance."""
        import time as _time

        with contextlib.suppress(Exception):
            from server.utils.appium_driver import AppiumDriver

            ad = AppiumDriver.get_instance()
            if (info := ad.get_appium_process_info(email)) and info.get("running"):
                ad.stop_appium_for_profile(email)
        with contextlib.suppress(Exception):
            cleanup_start = _time.time()
            # Skip driver.quit() during shutdown since emulator is already stopped
            automator.cleanup(skip_driver_quit=True)
            logger.info(f"automator.cleanup() took {_time.time() - cleanup_start:.1f}s for {email}")
            summary["automator_cleaned"] = True
        # Clear reference even if cleanup errored.
        self.server.automators[email] = None

    # ------------------------------------------------------------------
    # Private helpers – generic utilities                               ──────
    # ------------------------------------------------------------------

    @staticmethod
    def _force_kill_emulator_process(port: str):
        """Brutally kill an emulator process by listening port."""
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            subprocess.run(["pkill", "-f", f"emulator.*-port {port}"], timeout=3)

    # Existing port‑cleanup helpers ––– signatures unchanged ---------- #

    def _cleanup_emulator_ports(self, emulator_id: str, email: str) -> None:  # noqa: D401, ANN001
        """Clean up all ports associated with *emulator_id* (unchanged signature)."""

        try:
            # CRITICAL: Verify this emulator belongs to this email before cleaning
            try:
                avd_result = subprocess.run(
                    [f"adb -s {emulator_id} emu avd name"],
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if avd_result.returncode == 0:
                    device_avd = avd_result.stdout.strip()
                    # Handle "AVD_NAME\nOK" format
                    if "\n" in device_avd:
                        device_avd = device_avd.split("\n")[0].strip()

                    logger.info(f"Emulator {emulator_id} is running AVD: {device_avd}")

                    # Get expected AVD from VNC instance or profile
                    vnc_mgr = VNCInstanceManager.get_instance()
                    vnc_instance = vnc_mgr.get_instance_for_profile(email)
                    if vnc_instance and vnc_instance.get("emulator_id") != emulator_id:
                        logger.error(
                            f"CRITICAL: Attempted to clean ports for emulator {emulator_id} "
                            f"but VNC instance shows {vnc_instance.get('emulator_id')} for {email}. "
                            f"REFUSING to prevent cross-user interference!"
                        )
                        return
                else:
                    logger.warning(f"Could not determine AVD for emulator {emulator_id}")
            except Exception as e:
                logger.warning(f"Error checking AVD: {e}")

            logger.info(f"Removing all ADB port forwards for {emulator_id}")
            with contextlib.suppress(Exception):
                subprocess.run(
                    [f"adb -s {emulator_id} forward --remove-all"],
                    shell=True,
                    capture_output=True,
                    timeout=5,
                )

            logger.info(f"Killing uiautomator processes on {emulator_id} for email={email}")
            with contextlib.suppress(Exception):
                subprocess.run(
                    [f"adb -s {emulator_id} shell pkill -f uiautomator"],
                    shell=True,
                    capture_output=True,
                    timeout=5,
                )
            vnc_mgr = VNCInstanceManager.get_instance()
            if instance := vnc_mgr.get_instance_for_profile(email):
                ports = [
                    instance.get("appium_port"),
                    instance.get("appium_system_port"),
                    instance.get("appium_chromedriver_port"),
                    instance.get("appium_mjpeg_server_port"),
                ]
                for p in filter(None, ports):
                    self._kill_process_on_port(p)
                if platform.system() == "Darwin":
                    from server.utils.websocket_proxy_manager import (
                        WebSocketProxyManager,
                    )

                    ws_mgr = WebSocketProxyManager.get_instance()
                    with contextlib.suppress(Exception):
                        if ws_mgr.is_proxy_running(email):
                            ws_mgr.stop_proxy(email)
        except Exception as exc:
            logger.error("Error in _cleanup_emulator_ports: %s", exc, exc_info=True)

    def _kill_process_on_port(self, port: int) -> None:  # noqa: ANN001, D401
        """Kill any process listening on *port* (signature unchanged)."""
        if not port:
            return
        try:
            result = subprocess.run(
                ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True
            )
            for pid in filter(None, result.stdout.split()):
                with contextlib.suppress(Exception):
                    os.kill(int(pid), signal.SIGTERM)
                    time.sleep(0.5)
                    os.kill(int(pid), signal.SIGKILL)
        except Exception as exc:
            logger.warning("Error checking/terminating processes on port %s: %s", port, exc)
