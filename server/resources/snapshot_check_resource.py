"""Snapshot check resource for diagnosing emulator boot behavior."""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

from flask_restful import Resource

from server.utils.request_utils import get_sindarin_email
from views.core.avd_profile_manager import AVDProfileManager

logger = logging.getLogger(__name__)


class SnapshotCheckResource(Resource):
    """Resource for checking snapshot status and predicting boot behavior."""

    def __init__(self, server_instance=None):
        """Initialize the snapshot check resource.

        Args:
            server_instance: The AutomationServer instance
        """
        self.server = server_instance
        super().__init__()

    def get(self):
        """Check snapshot status and predict next boot behavior for the current user.

        Returns detailed information about:
        - Snapshot existence and metadata
        - Predicted boot type (cold/warm)
        - Reasons for cold boot if applicable
        - AVD configuration related to snapshots
        - User profile flags affecting boot behavior
        """
        try:
            # Get the user's email
            sindarin_email = get_sindarin_email()

            if not sindarin_email:
                return {"error": "No email provided", "message": "Email parameter is required"}, 400

            # Get the profile manager instance
            profile_manager = AVDProfileManager.get_instance()

            # Check if profile exists
            if sindarin_email not in profile_manager.profiles_index:
                return {
                    "email": sindarin_email,
                    "has_profile": False,
                    "message": "No profile exists for this user",
                }, 200

            # Get emulator launcher to check snapshot existence
            emulator_launcher = None
            if self.server and hasattr(self.server, "automators"):
                # Try to get launcher from any automator or create one
                for automator in self.server.automators.values():
                    if automator and hasattr(automator, "emulator_manager"):
                        emulator_launcher = automator.emulator_manager.emulator_launcher
                        break

            # Extract AVD name
            avd_name = self._extract_avd_name_from_email(sindarin_email)
            if not avd_name:
                return {
                    "email": sindarin_email,
                    "error": "Could not determine AVD name",
                }, 500

            # Check snapshot existence
            snapshot_info = self._check_snapshot_existence(avd_name, emulator_launcher)

            # Get user profile data
            profile_data = self._get_profile_snapshot_data(sindarin_email, profile_manager)

            # Check AVD configuration
            avd_config = self._check_avd_config(avd_name)

            # Determine boot type and reasons
            boot_prediction = self._predict_boot_type(
                snapshot_info, profile_data, avd_config, emulator_launcher, sindarin_email
            )

            # Check if emulator is currently running
            is_running = self._check_if_running(sindarin_email)

            return {
                "email": sindarin_email,
                "has_profile": True,
                "avd_name": avd_name,
                "emulator_running": is_running,
                "snapshot_info": snapshot_info,
                "profile_data": profile_data,
                "avd_config": avd_config,
                "boot_prediction": boot_prediction,
                "timestamp": datetime.now().isoformat(),
            }, 200

        except Exception as e:
            logger.error(f"Error checking snapshot status: {e}")
            return {"error": "Failed to check snapshot status", "message": str(e)}, 500

    def _extract_avd_name_from_email(self, email: str) -> Optional[str]:
        """Extract AVD name from email address."""
        try:
            # Convert email to AVD name format
            avd_identifier = email.replace("@", "_").replace(".", "_")
            return f"KindleAVD_{avd_identifier}"
        except Exception as e:
            logger.error(f"Error extracting AVD name from email {email}: {e}")
            return None

    def _check_snapshot_existence(self, avd_name: str, emulator_launcher=None) -> Dict[str, any]:
        """Check if snapshots exist for the AVD."""
        snapshot_info = {
            "default_boot_exists": False,
            "snapshot_path": None,
            "snapshot_size_mb": None,
            "all_snapshots": [],
        }

        try:
            # Get AVD directory from environment
            android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
            avd_dir = os.path.join(android_home, "avd")
            avd_path = os.path.join(avd_dir, f"{avd_name}.avd")
            snapshots_dir = os.path.join(avd_path, "snapshots")

            # Check default_boot snapshot
            default_boot_path = os.path.join(snapshots_dir, "default_boot")
            if os.path.exists(default_boot_path):
                snapshot_info["default_boot_exists"] = True
                snapshot_info["snapshot_path"] = default_boot_path

                # Calculate snapshot size
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(default_boot_path):
                    for filename in filenames:
                        filepath = os.path.join(dirpath, filename)
                        if os.path.exists(filepath):
                            total_size += os.path.getsize(filepath)
                snapshot_info["snapshot_size_mb"] = round(total_size / (1024 * 1024), 2)

            # List all snapshots
            if os.path.exists(snapshots_dir):
                for entry in os.listdir(snapshots_dir):
                    snapshot_path = os.path.join(snapshots_dir, entry)
                    if os.path.isdir(snapshot_path):
                        snapshot_info["all_snapshots"].append(entry)

        except Exception as e:
            logger.error(f"Error checking snapshot existence: {e}")
            snapshot_info["error"] = str(e)

        return snapshot_info

    def _get_profile_snapshot_data(self, email: str, profile_manager: AVDProfileManager) -> Dict[str, any]:
        """Get snapshot-related data from user profile."""
        return {
            "last_snapshot_timestamp": profile_manager.get_user_field(email, "last_snapshot_timestamp"),
            "created_from_seed_clone": profile_manager.get_user_field(
                email, "created_from_seed_clone", False
            ),
            "needs_device_randomization": profile_manager.get_user_field(
                email, "needs_device_randomization", False
            ),
            "post_boot_randomized": profile_manager.get_user_field(email, "post_boot_randomized", False),
            "auth_date": profile_manager.get_user_field(email, "auth_date"),
            "auth_failed_date": profile_manager.get_user_field(email, "auth_failed_date"),
        }

    def _check_avd_config(self, avd_name: str) -> Dict[str, any]:
        """Check AVD configuration related to snapshots."""
        config_data = {
            "config_exists": False,
            "snapshot_present": None,
            "quickboot_choice": None,
            "hw_ramSize": None,
            "hw_gfxstream": None,
        }

        try:
            android_home = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
            avd_dir = os.path.join(android_home, "avd")
            config_path = os.path.join(avd_dir, f"{avd_name}.avd", "config.ini")

            if os.path.exists(config_path):
                config_data["config_exists"] = True

                with open(config_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("snapshot.present="):
                            config_data["snapshot_present"] = line.split("=")[1] == "yes"
                        elif line.startswith("quickbootChoice="):
                            config_data["quickboot_choice"] = int(line.split("=")[1])
                        elif line.startswith("hw.ramSize="):
                            config_data["hw_ramSize"] = int(line.split("=")[1])
                        elif line.startswith("hw.gfxstream="):
                            config_data["hw_gfxstream"] = int(line.split("=")[1])

        except Exception as e:
            logger.error(f"Error checking AVD config: {e}")
            config_data["error"] = str(e)

        return config_data

    def _predict_boot_type(
        self,
        snapshot_info: Dict,
        profile_data: Dict,
        avd_config: Dict,
        emulator_launcher,
        email: str,
    ) -> Dict[str, any]:
        """Predict the next boot type and provide reasons."""
        cold_boot_reasons = []
        next_boot_type = "warm"

        # Check if snapshot exists
        if not snapshot_info.get("default_boot_exists"):
            cold_boot_reasons.append("No default_boot snapshot exists")
            next_boot_type = "cold"

        # Check if device randomization is needed
        if profile_data.get("created_from_seed_clone") or profile_data.get("needs_device_randomization"):
            if not profile_data.get("post_boot_randomized"):
                cold_boot_reasons.append(
                    "Device randomization needed (created from seed or needs randomization)"
                )
                next_boot_type = "cold"

        # Check AVD configuration
        if avd_config.get("snapshot_present") is False:
            cold_boot_reasons.append("AVD config has snapshot.present=no")
            next_boot_type = "cold"

        if avd_config.get("quickboot_choice") == 1:  # 1 = cold boot
            cold_boot_reasons.append("AVD config has quickbootChoice=1 (cold boot)")
            next_boot_type = "cold"

        # Check if gfxstream is enabled (can affect snapshots)
        if avd_config.get("hw_gfxstream") == 1:
            cold_boot_reasons.append("hw.gfxstream=1 may cause snapshot compatibility issues")
            # This doesn't force cold boot but can cause issues

        # If user lost authentication, they might need a cold boot
        if profile_data.get("auth_failed_date") and not profile_data.get("auth_date"):
            cold_boot_reasons.append("User authentication failed, may need fresh start")
            # This is informational, doesn't force cold boot

        return {
            "next_boot_type": next_boot_type,
            "cold_boot_reasons": cold_boot_reasons,
            "snapshot_will_be_used": next_boot_type == "warm" and snapshot_info.get("default_boot_exists"),
        }

    def _check_if_running(self, email: str) -> bool:
        """Check if emulator is currently running for this user."""
        try:
            if self.server and hasattr(self.server, "automators"):
                automator = self.server.automators.get(email)
                if automator and hasattr(automator, "emulator_manager"):
                    emulator_id, _ = automator.emulator_manager.emulator_launcher.get_running_emulator(email)
                    return emulator_id is not None
        except Exception as e:
            logger.error(f"Error checking if emulator is running: {e}")

        return False
