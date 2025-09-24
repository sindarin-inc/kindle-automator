import logging
from datetime import datetime, timezone

from flask import request
from flask_restful import Resource

from server.utils.cold_storage_manager import ColdStorageManager
from views.core.avd_profile_manager import AVDProfileManager

logger = logging.getLogger(__name__)


class ColdStorageArchiveResource(Resource):
    """Resource for archiving eligible profiles to cold storage"""

    def __init__(self, **kwargs):
        # Accept kwargs but don't use them - for compatibility with server_instance
        super().__init__()

    def get(self):
        """Archive eligible profiles to cold storage (GET method)"""
        return self._handle_archive_request()

    def post(self):
        """Archive eligible profiles to cold storage (POST method)"""
        return self._handle_archive_request()

    def _handle_archive_request(self):
        """Handle archive request for both GET and POST"""
        try:
            # Get parameters from query params (GET) or JSON body (POST)
            if request.method == "GET":
                # Support both 'days' and 'days_inactive' for flexibility
                days_inactive = int(request.args.get("days", request.args.get("days_inactive", 30)))
                dry_run = request.args.get("dry_run", "false").lower() in ["true", "1", "yes"]
                user_email = request.args.get("user_email")
            else:  # POST
                json_data = request.json or {}
                # Support both 'days' and 'days_inactive' for flexibility
                days_inactive = json_data.get("days", json_data.get("days_inactive", 30))
                dry_run = json_data.get("dry_run", False)
                user_email = json_data.get("user_email")

            cold_storage_manager = ColdStorageManager.get_instance()

            # If user_email is specified, archive only that user
            if user_email:
                logger.info(f"Archiving specific user {user_email} to cold storage (dry_run={dry_run})")
                success, storage_info = cold_storage_manager.archive_specific_profile(
                    user_email, dry_run=dry_run
                )

                if success:
                    return {
                        "success": True,
                        "message": f"User {user_email} archived to cold storage",
                        "user_email": user_email,
                        "storage_info": storage_info,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "dry_run": dry_run,
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Failed to archive user {user_email}",
                        "user_email": user_email,
                        "error": storage_info.get("error") if storage_info else "Unknown error",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }, 400

            # Otherwise, archive all eligible profiles
            logger.info(
                f"Starting cold storage archival for profiles inactive for {days_inactive} days (dry_run={dry_run})"
            )
            success_count, failure_count, storage_info = cold_storage_manager.archive_eligible_profiles(
                days_inactive, dry_run=dry_run
            )

            message = (
                "Cold storage archival simulation complete" if dry_run else "Cold storage archival complete"
            )

            return {
                "success": True,
                "message": message,
                "success_count": success_count,
                "failure_count": failure_count,
                "storage_info": storage_info,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dry_run": dry_run,
            }

        except Exception as e:
            logger.error(f"Error during cold storage archival: {e}", exc_info=True)
            return {"success": False, "error": str(e)}, 500


class ColdStorageStatusResource(Resource):
    """Resource for checking cold storage status of profiles"""

    def __init__(self, **kwargs):
        # Accept kwargs but don't use them - for compatibility with server_instance
        super().__init__()

    def get(self):
        """Get cold storage status for all profiles"""
        try:
            # Get days parameter from query params
            days_inactive = int(request.args.get("days", request.args.get("days_inactive", 30)))
            logger.info(f"Checking cold storage status with days_inactive={days_inactive}")

            cold_storage_manager = ColdStorageManager.get_instance()
            profile_manager = AVDProfileManager.get_instance()

            # Get all profiles
            logger.info("Fetching all profiles...")
            all_profiles = profile_manager.list_profiles()
            logger.info(f"Found {len(all_profiles)} total profiles")

            cold_storage_profiles = []
            eligible_profiles = []
            active_profiles = []

            # Get eligible list once to avoid repeated calls
            logger.info("Getting list of profiles eligible for cold storage...")
            eligible_list = cold_storage_manager.get_profiles_eligible_for_cold_storage(days_inactive)
            logger.info(f"Found {len(eligible_list)} eligible profiles")

            logger.info("Processing individual profiles...")
            for i, (email, profile) in enumerate(all_profiles.items()):
                if i % 10 == 0:
                    logger.info(f"Processing profile {i+1}/{len(all_profiles)}")

                # Check if in cold storage
                cold_storage_date = profile_manager.get_user_field(email, "cold_storage_date")
                if cold_storage_date:
                    logger.debug(f"Profile {email} is in cold storage since {cold_storage_date}")
                    in_s3 = cold_storage_manager.is_in_cold_storage(email)
                    cold_storage_profiles.append(
                        {
                            "email": email,
                            "cold_storage_date": cold_storage_date,
                            "in_s3": in_s3,
                        }
                    )
                else:
                    # Get last_used timestamp and convert to ISO format
                    last_used = profile_manager.get_user_field(email, "last_used")
                    last_used_date = None
                    if last_used:
                        try:
                            # Convert Unix timestamp to ISO format string
                            last_used_date = datetime.fromtimestamp(last_used, tz=timezone.utc).isoformat()
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid last_used timestamp for {email}: {last_used}")
                    else:
                        logger.debug(f"Profile {email} has no last_used timestamp")

                    # Check if eligible for cold storage
                    if email in eligible_list:
                        eligible_profiles.append(
                            {
                                "email": email,
                                "last_used_date": last_used_date,
                            }
                        )
                    else:
                        active_profiles.append(
                            {
                                "email": email,
                                "last_used_date": last_used_date,
                            }
                        )

            logger.info(
                f"Status check complete: {len(cold_storage_profiles)} in cold storage, "
                f"{len(eligible_profiles)} eligible, {len(active_profiles)} active"
            )

            return {
                "success": True,
                "cold_storage_profiles": cold_storage_profiles,
                "eligible_profiles": eligible_profiles,
                "active_profiles": active_profiles,
                "days_threshold": days_inactive,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Error checking cold storage status: {e}", exc_info=True)
            return {"success": False, "error": str(e)}, 500


class ColdStorageRestoreResource(Resource):
    """Resource for restoring profiles from cold storage or local backup"""

    def __init__(self, **kwargs):
        # Accept kwargs but don't use them - for compatibility with server_instance
        super().__init__()

    def get(self):
        """Restore a profile from cold storage (GET method with query params)"""
        return self._handle_restore_request()

    def post(self):
        """Restore a profile from cold storage or local backup (POST method)"""
        return self._handle_restore_request()

    def _handle_restore_request(self):
        """Handle restore request for both GET and POST"""
        try:
            # Get parameters from query params (GET) or JSON body (POST)
            if request.method == "GET":
                user_email = request.args.get("user_email")
                from_backup = request.args.get("from_backup", "false").lower() in ["true", "1", "yes"]
                dry_run = request.args.get("dry_run", "false").lower() in ["true", "1", "yes"]
            else:  # POST
                json_data = request.json or {}
                user_email = json_data.get("user_email")
                from_backup = json_data.get("from_backup", False)
                dry_run = json_data.get("dry_run", False)

            if not user_email:
                return {"success": False, "error": "user_email is required"}, 400

            cold_storage_manager = ColdStorageManager.get_instance()

            if from_backup:
                # Restore from local backup (revert dry run)
                logger.info(f"Restoring {user_email} from local backup")
                success = cold_storage_manager.restore_from_local_backup(user_email)

                if success:
                    return {
                        "success": True,
                        "message": f"Successfully restored {user_email} from local backup",
                        "user_email": user_email,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Failed to restore {user_email} from local backup",
                        "user_email": user_email,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }, 400
            else:
                # Normal restore from cold storage
                logger.info(f"Restoring {user_email} from cold storage (dry_run={dry_run})")
                success, restore_info = cold_storage_manager.restore_avd_from_cold_storage(
                    user_email, dry_run=dry_run
                )

                if success:
                    if not dry_run:
                        # Clear cold storage date only if not a dry run
                        profile_manager = AVDProfileManager.get_instance()
                        profile_manager.set_user_field(user_email, "cold_storage_date", None)
                        profile_manager.set_user_field(user_email, "cold_storage_dry_run", None)

                    message = (
                        f"Successfully verified restoration capability for {user_email}"
                        if dry_run
                        else f"Successfully restored {user_email} from cold storage"
                    )

                    return {
                        "success": True,
                        "message": message,
                        "user_email": user_email,
                        "restore_info": restore_info,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "dry_run": dry_run,
                    }
                else:
                    return {
                        "success": False,
                        "message": f"Failed to restore {user_email} from cold storage",
                        "user_email": user_email,
                        "error": restore_info.get("error") if restore_info else "Unknown error",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }, 400

        except Exception as e:
            logger.error(f"Error during cold storage restore: {e}", exc_info=True)
            return {"success": False, "error": str(e)}, 500
