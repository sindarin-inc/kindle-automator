import logging
import os
import platform
import shutil
import socket
import tarfile
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import boto3
from botocore.client import Config
from dotenv import load_dotenv

from views.core.avd_creator import AVDCreator

load_dotenv()

logger = logging.getLogger(__name__)

# Singleton instance
_instance = None


class ColdStorageManager:
    """Manages AVD cold storage operations with DigitalOcean Spaces"""

    @classmethod
    def get_instance(cls) -> "ColdStorageManager":
        """
        Get the singleton instance of ColdStorageManager.

        Returns:
            ColdStorageManager: The singleton instance
        """
        global _instance
        if _instance is None:
            _instance = cls()
        return _instance

    def __init__(self):
        # Check if this is being called directly or through get_instance()
        if _instance is not None and _instance is not self:
            logger.warning("ColdStorageManager initialized directly. Use get_instance() instead.")

        self.bucket_name = os.getenv("DO_SPACES_BUCKET", "kindle-automator")
        self.s3_client = self._initialize_s3_client()
        self.cold_storage_prefix = "cold-storage/avds/"

        # Get AVD directory from profile manager to match the environment
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()
        self.avd_base_path = profile_manager.avd_dir

        # Local cold storage backup directory for dry runs
        self.local_cold_storage_dir = os.path.join(os.path.dirname(self.avd_base_path), "cold-storage-backup")
        os.makedirs(self.local_cold_storage_dir, exist_ok=True)

    def _initialize_s3_client(self):
        """Initialize S3 client for DigitalOcean Spaces"""
        try:
            endpoint = os.getenv("DO_SPACES_ENDPOINT", "https://nyc3.digitaloceanspaces.com")
            access_key = os.getenv("DO_SPACES_KEY")
            secret_key = os.getenv("DO_SPACES_SECRET")

            if not access_key or not secret_key:
                logger.warning("DO_SPACES_KEY or DO_SPACES_SECRET not set in environment")
                logger.warning("S3 operations will fail without these credentials")

            logger.info(f"Initializing S3 client with endpoint: {endpoint}")
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(s3={"addressing_style": "virtual"}),
            )
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}", exc_info=True)
            raise

    def _get_directory_size(self, path: str) -> int:
        """Get total size of a directory in bytes"""
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
        return total_size

    def _format_bytes(self, bytes_size: int) -> str:
        """Format bytes to human readable string"""
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f} PB"

    def _compress_and_upload_avd(
        self,
        email: str,
        avd_name: str,
        avd_path: str,
        ini_path: str,
        s3_prefix: str = "cold-storage/avds/",
        include_metadata: bool = False,
    ) -> Tuple[bool, Optional[dict]]:
        """
        Shared method to compress and upload AVD to S3.

        Args:
            email: Email address of the profile
            avd_name: Name of the AVD
            avd_path: Path to AVD directory
            ini_path: Path to AVD .ini file
            s3_prefix: S3 prefix for storage ("backups/avds/" or "cold-storage/avds/")
            include_metadata: Whether to include metadata in S3 upload

        Returns:
            Tuple[bool, Optional[dict]]: (success, storage_info)
        """
        temp_path = None
        try:
            # Calculate original size
            original_size = self._get_directory_size(avd_path) + os.path.getsize(ini_path)
            logger.info(f"Original AVD size: {self._format_bytes(original_size)}")

            # Create temporary archive
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_file:
                temp_path = temp_file.name
            logger.info(f"Temporary archive path: {temp_path}")

            # Compress AVD files
            logger.info(f"Compressing AVD files...")
            start_time = time.time()
            with tarfile.open(temp_path, "w:gz", compresslevel=1) as tar:  # Fast compression
                logger.info(f"Adding {avd_path} to archive...")
                tar.add(avd_path, arcname=f"{avd_name}.avd")
                logger.info(f"Adding {ini_path} to archive...")
                tar.add(ini_path, arcname=f"{avd_name}.ini")
            compression_time = time.time() - start_time
            logger.info(f"Compression completed in {compression_time:.2f} seconds")

            # Get compressed size
            compressed_size = os.path.getsize(temp_path)
            compression_ratio = (1 - compressed_size / original_size) * 100
            logger.info(
                f"Compressed size: {self._format_bytes(compressed_size)} ({compression_ratio:.1f}% compression)"
            )

            # Upload to S3
            archive_key = f"{s3_prefix}{email}/{avd_name}.tar.gz"
            logger.info(f"Uploading to S3: {self.bucket_name}/{archive_key}")
            upload_start = time.time()

            extra_args = {"ACL": "private"}
            if include_metadata:
                import socket

                extra_args["Metadata"] = {
                    "hostname": socket.gethostname(),
                    "backup_date": datetime.now(timezone.utc).isoformat(),
                    "email": email,
                }

            with open(temp_path, "rb") as f:
                self.s3_client.upload_fileobj(f, self.bucket_name, archive_key, ExtraArgs=extra_args)
            upload_time = time.time() - upload_start
            logger.info(f"S3 upload completed in {upload_time:.2f} seconds")

            # Calculate space saved (for cold storage)
            space_saved = original_size - compressed_size

            storage_info = {
                "original_size": original_size,
                "compressed_size": compressed_size,
                "compression_ratio": compression_ratio,
                "space_saved": space_saved,
                "original_size_human": self._format_bytes(original_size),
                "compressed_size_human": self._format_bytes(compressed_size),
                "space_saved_human": self._format_bytes(space_saved),
                "s3_key": archive_key,
                "upload_time": upload_time,
            }

            if include_metadata:
                import socket

                storage_info["backup_date"] = datetime.now(timezone.utc)
                storage_info["hostname"] = socket.gethostname()

            return True, storage_info

        except Exception as e:
            logger.error(f"Failed to compress and upload AVD for {email}: {e}", exc_info=True)
            return False, {"error": str(e)}
        finally:
            # Always clean up temp file
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                    logger.info("Temporary archive file cleaned up")
                except Exception as e:
                    logger.error(f"Failed to clean up temporary file: {e}", exc_info=True)

    def backup_avd(self, email: str) -> Tuple[bool, Optional[dict]]:
        """
        Create a backup of an AVD in cloud storage without deleting the local copy.
        This is called when a user successfully authenticates to ensure we have a backup.

        Args:
            email: Email address of the profile to backup

        Returns:
            Tuple[bool, Optional[dict]]: (success, backup_info)
        """
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()
        avd_name = profile_manager.get_avd_for_email(email)

        if not avd_name:
            logger.warning(f"No AVD name found for email {email}")
            return False, None

        avd_path = os.path.join(self.avd_base_path, f"{avd_name}.avd")
        ini_path = os.path.join(self.avd_base_path, f"{avd_name}.ini")

        if not os.path.exists(avd_path) or not os.path.exists(ini_path):
            logger.warning(f"AVD files not found for email {email}")
            return False, None

        # Take snapshot if emulator is running
        self._save_snapshot_if_running(email)

        logger.info(f"Starting AVD backup for email {email}")

        # Use shared compression and upload method
        return self._compress_and_upload_avd(
            email=email,
            avd_name=avd_name,
            avd_path=avd_path,
            ini_path=ini_path,
            s3_prefix="backups/avds/",
            include_metadata=True,
        )

    def _save_snapshot_if_running(self, email: str) -> bool:
        """
        Save a snapshot if the emulator is running.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if snapshot was saved or not needed, False if failed
        """
        from server.utils.vnc_instance_manager import VNCInstanceManager

        vnc_manager = VNCInstanceManager.get_instance()
        emulator_id = vnc_manager.get_emulator_id(email)

        if emulator_id:
            from views.core.emulator_manager import EmulatorManager

            emulator_manager = EmulatorManager.get_instance()

            if emulator_manager.is_emulator_running(email):
                logger.info(f"Emulator {emulator_id} is running for {email}, taking snapshot")
                try:
                    from server.utils.emulator_launcher import EmulatorLauncher

                    launcher = EmulatorLauncher(
                        os.environ.get("ANDROID_HOME", "/Users/sam/Library/Android/sdk"),
                        os.path.join(os.path.expanduser("~"), ".android/avd"),
                        platform.machine(),
                    )
                    if launcher.save_snapshot(email):
                        logger.info(f"Snapshot saved successfully for {email}")
                        return True
                    else:
                        logger.warning(f"Failed to save snapshot for {email}")
                        return False
                except Exception as e:
                    logger.error(f"Error saving snapshot for {email}: {e}", exc_info=True)
                    return False
        return True  # No snapshot needed

    def archive_avd_to_cold_storage(self, email: str, dry_run: bool = False) -> Tuple[bool, Optional[dict]]:
        """
        Archive an AVD to cold storage (uploads and DELETES local copy).

        This is for permanent cold storage when a user hasn't been active.
        For simple backups without deletion, use backup_avd() instead.

        Args:
            email: Email address of the profile to archive
            dry_run: If True, perform all operations except deletion of local files

        Returns:
            Tuple[bool, Optional[dict]]: (success, storage_info)
        """
        from server.utils.vnc_instance_manager import VNCInstanceManager
        from views.core.avd_profile_manager import AVDProfileManager
        from views.core.emulator_manager import EmulatorManager

        profile_manager = AVDProfileManager.get_instance()
        avd_name = profile_manager.get_avd_for_email(email)

        if not avd_name:
            logger.warning(f"No AVD name found for email {email}")
            return False, None

        # Stop emulator if running (required for cold storage)
        if not self._stop_emulator_if_running(email):
            return False, {"error": "Failed to stop running emulator"}

        avd_path = os.path.join(self.avd_base_path, f"{avd_name}.avd")
        ini_path = os.path.join(self.avd_base_path, f"{avd_name}.ini")

        if not os.path.exists(avd_path) or not os.path.exists(ini_path):
            logger.warning(f"AVD files not found for email {email}")
            return False, None

        logger.info(f"Starting cold storage archival for email {email}")

        # Use shared compression and upload method
        success, storage_info = self._compress_and_upload_avd(
            email=email,
            avd_name=avd_name,
            avd_path=avd_path,
            ini_path=ini_path,
            s3_prefix=self.cold_storage_prefix,
            include_metadata=False,
        )

        if not success:
            return False, storage_info

        # Handle local file deletion
        if dry_run:
            logger.info("DRY RUN: Moving files to local cold storage backup instead of deleting")
            # Create backup directory for this email
            backup_dir = os.path.join(self.local_cold_storage_dir, email)
            os.makedirs(backup_dir, exist_ok=True)

            # Move AVD files to backup directory
            backup_avd_path = os.path.join(backup_dir, f"{avd_name}.avd")
            backup_ini_path = os.path.join(backup_dir, f"{avd_name}.ini")

            # Remove existing backups if they exist
            if os.path.exists(backup_avd_path):
                shutil.rmtree(backup_avd_path)
            if os.path.exists(backup_ini_path):
                os.unlink(backup_ini_path)

            # Move files to backup
            shutil.move(avd_path, backup_avd_path)
            shutil.move(ini_path, backup_ini_path)
            logger.info(f"DRY RUN: Moved AVD files to {backup_dir}")
        else:
            # Normal operation - delete the files
            logger.info(f"Deleting local AVD files after successful upload")
            logger.info(f"Deleting AVD directory: {avd_path}")
            shutil.rmtree(avd_path)
            logger.info(f"Deleting INI file: {ini_path}")
            os.unlink(ini_path)

            # Verify deletion
            if os.path.exists(avd_path):
                logger.error(f"AVD directory still exists after deletion attempt: {avd_path}", exc_info=True)
                raise Exception(f"Failed to delete AVD directory: {avd_path}")
            if os.path.exists(ini_path):
                logger.error(f"INI file still exists after deletion attempt: {ini_path}", exc_info=True)
                raise Exception(f"Failed to delete INI file: {ini_path}")

            logger.info(f"Successfully deleted local AVD files for {email}")

        # Add dry_run flag to storage_info
        storage_info["dry_run"] = dry_run

        if dry_run:
            logger.info(f"DRY RUN: Successfully simulated archiving AVD for email {email}")
        else:
            logger.info(f"Successfully archived AVD for email {email} to cold storage")

        return True, storage_info

    def _stop_emulator_if_running(self, email: str) -> bool:
        """
        Stop emulator if it's running. Required for cold storage.

        Args:
            email: Email address of the profile

        Returns:
            bool: True if emulator was stopped or wasn't running, False if failed to stop
        """
        from server.utils.vnc_instance_manager import VNCInstanceManager
        from views.core.emulator_manager import EmulatorManager

        vnc_manager = VNCInstanceManager.get_instance()
        emulator_id = vnc_manager.get_emulator_id(email)

        if emulator_id:
            emulator_manager = EmulatorManager.get_instance()

            if emulator_manager.is_emulator_running(email):
                logger.warning(f"Cannot archive AVD for {email} - emulator {emulator_id} is still running")

                # Take a snapshot before stopping to preserve user state
                logger.info(f"Taking snapshot before stopping emulator {emulator_id} for archiving")
                self._save_snapshot_if_running(email)

                logger.info(f"Attempting to stop emulator {emulator_id} before archiving")
                # Try to stop the emulator
                if not emulator_manager.stop_specific_emulator(emulator_id):
                    logger.error(f"Failed to stop emulator {emulator_id} for {email}", exc_info=True)
                    return False

                # Wait a bit for the emulator to fully shut down
                time.sleep(3)

                # Double-check it's stopped
                if emulator_manager.is_emulator_running(email):
                    logger.error(f"Emulator {emulator_id} still running after stop attempt", exc_info=True)
                    return False

                logger.info(f"Successfully stopped emulator {emulator_id} for {email}")

                # Release the entire VNC instance since AVD is going to cold storage
                vnc_manager.release_instance_from_profile(email)

        return True

    def restore_avd_from_backup(self, email: str, force: bool = False) -> Tuple[bool, Optional[dict]]:
        """
        Restore an AVD from backup (not cold storage).

        This restores from the backup created during authentication,
        useful for moving AVDs between servers or recovering from issues.

        Args:
            email: Email address of the profile to restore
            force: If True, overwrite existing AVD files

        Returns:
            Tuple[bool, Optional[dict]]: (success, restore_info)
        """
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()
        avd_name = profile_manager.get_avd_for_email(email)

        if not avd_name:
            logger.warning(f"No AVD name found for email {email}")
            return False, {"error": "No AVD name found"}

        # Check if AVD already exists locally
        avd_path = os.path.join(self.avd_base_path, f"{avd_name}.avd")
        ini_path = os.path.join(self.avd_base_path, f"{avd_name}.ini")

        if not force and (os.path.exists(avd_path) or os.path.exists(ini_path)):
            logger.warning(f"AVD already exists locally for {email}, use force=True to overwrite")
            return False, {"error": "AVD already exists locally"}

        # Try backup location first
        backup_key = f"backups/avds/{email}/{avd_name}.tar.gz"
        archive_key = backup_key

        try:
            # Check if backup exists
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=backup_key)
            archive_size = int(response.get("ContentLength", 0))
            logger.info(f"Found backup in S3: {self._format_bytes(archive_size)}")
        except:
            # Fall back to cold storage location
            archive_key = f"{self.cold_storage_prefix}{email}/{avd_name}.tar.gz"
            try:
                response = self.s3_client.head_object(Bucket=self.bucket_name, Key=archive_key)
                archive_size = int(response.get("ContentLength", 0))
                logger.info(f"Found archive in cold storage: {self._format_bytes(archive_size)}")
            except:
                logger.error(f"No backup or cold storage archive found for {email}")
                return False, {"error": "No backup found"}

        temp_path = None
        try:
            # Download archive to temp file
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_file:
                temp_path = temp_file.name

            logger.info(f"Downloading archive from S3...")
            start_time = time.time()
            self.s3_client.download_file(self.bucket_name, archive_key, temp_path)
            download_time = time.time() - start_time
            logger.info(f"Download completed in {download_time:.2f} seconds")

            # Extract archive
            logger.info(f"Extracting archive to {self.avd_base_path}")
            with tarfile.open(temp_path, "r:gz") as tar:
                tar.extractall(self.avd_base_path)

            # Verify extraction
            if not os.path.exists(avd_path) or not os.path.exists(ini_path):
                raise Exception("AVD files not found after extraction")

            logger.info(f"Successfully restored AVD for {email} from backup")

            restore_info = {
                "archive_size": archive_size,
                "download_time": download_time,
                "s3_key": archive_key,
                "from_backup": "backups/" in archive_key,
            }

            return True, restore_info

        except Exception as e:
            logger.error(f"Failed to restore AVD from backup for {email}: {e}", exc_info=True)
            return False, {"error": str(e)}
        finally:
            # Clean up temp file
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.error(f"Failed to clean up temporary file: {e}", exc_info=True)

    def restore_avd_from_cold_storage(self, email: str, dry_run: bool = False) -> Tuple[bool, Optional[dict]]:
        """
        Restore an AVD from cold storage

        Args:
            email: Email address of the profile to restore
            dry_run: If True, download and verify archive without extracting or deleting from S3

        Returns:
            Tuple[bool, Optional[dict]]: (success, restore_info) where restore_info contains:
                - archive_size: Size of the downloaded archive
                - download_time: Time taken to download in seconds
                - s3_key: The S3 key that was used
                - dry_run: Whether this was a dry run
        """
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()
        avd_name = profile_manager.get_avd_for_email(email)

        if not avd_name:
            logger.warning(f"No AVD name found for email {email}")
            return False, {"error": "No AVD name found"}

        archive_key = f"{self.cold_storage_prefix}{email}/{avd_name}.tar.gz"
        temp_path = None

        try:
            logger.info(f"Starting cold storage restoration for email {email} (dry_run={dry_run})")

            # Check if archive exists in S3
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=archive_key)
            archive_size = int(response.get("ContentLength", 0))
            logger.info(f"Found archive in S3: {self._format_bytes(archive_size)}")

            # Download archive to temp file
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_file:
                temp_path = temp_file.name

            logger.info(f"Downloading archive from S3...")
            start_time = time.time()
            self.s3_client.download_file(self.bucket_name, archive_key, temp_path)
            download_time = time.time() - start_time
            logger.info(f"Download completed in {download_time:.2f} seconds")

            # Verify the archive
            logger.info(f"Verifying archive integrity...")
            try:
                with tarfile.open(temp_path, "r:gz") as tar:
                    members = tar.getmembers()
                    logger.info(f"Archive contains {len(members)} files")
                    for member in members:
                        logger.info(f"  - {member.name}: {self._format_bytes(member.size)}")
            except Exception as e:
                logger.error(f"Archive verification failed: {e}", exc_info=True)
                raise

            restore_info = {
                "archive_size": archive_size,
                "archive_size_human": self._format_bytes(archive_size),
                "download_time": download_time,
                "s3_key": archive_key,
                "dry_run": dry_run,
            }

            if dry_run:
                # Dry run - just verify and clean up
                logger.info(f"DRY RUN: Archive verified successfully, would restore {avd_name}")
                logger.info(f"DRY RUN: Cleaning up temporary file")
                os.unlink(temp_path)
                return True, restore_info
            else:
                # Real restore - extract and delete from S3
                logger.info(f"Extracting archive to {self.avd_base_path}...")
                with tarfile.open(temp_path, "r:gz") as tar:
                    tar.extractall(self.avd_base_path)

                os.unlink(temp_path)

                logger.info(f"Deleting archive from S3...")
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=archive_key)

                logger.info(f"Successfully restored AVD for email {email} from cold storage")
                return True, restore_info

        except self.s3_client.exceptions.NoSuchKey:
            logger.warning(f"No cold storage archive found for email {email}")
            return False, {"error": "Archive not found in S3"}
        except Exception as e:
            logger.error(f"Failed to restore AVD for email {email}: {e}", exc_info=True)
            if temp_path and os.path.exists(temp_path):
                logger.info(f"Cleaning up temporary file")
                os.unlink(temp_path)
            return False, {"error": str(e)}

    def is_in_cold_storage(self, email: str) -> bool:
        """Check if an AVD is in cold storage"""
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()
        avd_name = profile_manager.get_avd_for_email(email)

        if not avd_name:
            return False

        archive_key = f"{self.cold_storage_prefix}{email}/{avd_name}.tar.gz"

        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=archive_key)
            return True
        except self.s3_client.exceptions.NoSuchKey:
            return False
        except Exception as e:
            logger.error(f"Error checking cold storage for email {email}: {e}", exc_info=True)
            return False

    def get_profiles_eligible_for_cold_storage(self, days_inactive: int = 30) -> list:
        """Get list of profiles eligible for cold storage based on last usage"""
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()
        cutoff_date = datetime.now() - timedelta(days=days_inactive)

        # Use targeted query to get inactive profiles
        eligible_profiles = []
        inactive_profiles = profile_manager.get_inactive_profiles(cutoff_date)

        for profile in inactive_profiles:
            email = profile.get("email")

            # The query already filtered out seed clone and cold storage profiles
            # Just check if AVD exists
            avd_name = profile.get("avd_name")
            if avd_name:
                avd_path = os.path.join(self.avd_base_path, f"{avd_name}.avd")
                if os.path.exists(avd_path):
                    eligible_profiles.append(email)
                else:
                    logger.debug(f"Profile {email} eligible but AVD doesn't exist at {avd_path}")
            else:
                logger.debug(f"Profile {email} has no last_used timestamp and no AVD name")

        return eligible_profiles

    def archive_eligible_profiles(
        self, days_inactive: int = 30, dry_run: bool = False
    ) -> Tuple[int, int, dict]:
        """
        Archive all eligible profiles to cold storage

        Args:
            days_inactive: Number of days of inactivity before archiving
            dry_run: If True, perform all operations except deletion of local files

        Returns:
            Tuple[int, int, dict]: (success_count, failure_count, total_storage_info)
        """
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()
        eligible_profiles = self.get_profiles_eligible_for_cold_storage(days_inactive)

        success_count = 0
        failure_count = 0
        total_original_size = 0
        total_compressed_size = 0
        total_space_saved = 0

        for email in eligible_profiles:
            success, storage_info = self.archive_avd_to_cold_storage(email, dry_run=dry_run)
            if success and storage_info:
                # Always mark as in cold storage, even in dry run
                profile_manager.set_user_field(email, "cold_storage_date", datetime.now().isoformat())
                if dry_run:
                    profile_manager.set_user_field(email, "cold_storage_dry_run", True)
                success_count += 1
                total_original_size += storage_info["original_size"]
                total_compressed_size += storage_info["compressed_size"]
                total_space_saved += storage_info["space_saved"]
            else:
                failure_count += 1

        total_storage_info = {
            "total_original_size": total_original_size,
            "total_compressed_size": total_compressed_size,
            "total_space_saved": total_space_saved,
            "total_original_size_human": self._format_bytes(total_original_size),
            "total_compressed_size_human": self._format_bytes(total_compressed_size),
            "total_space_saved_human": self._format_bytes(total_space_saved),
            "average_compression_ratio": (
                (1 - total_compressed_size / total_original_size) * 100 if total_original_size > 0 else 0
            ),
            "dry_run": dry_run,
        }

        if dry_run:
            logger.info(
                f"DRY RUN: Cold storage simulation complete: {success_count} would be archived, {failure_count} would fail"
            )
            logger.info(
                f"DRY RUN: Total space that would be saved: {total_storage_info['total_space_saved_human']} (compressed from {total_storage_info['total_original_size_human']} to {total_storage_info['total_compressed_size_human']})"
            )
        else:
            logger.info(f"Cold storage archival complete: {success_count} succeeded, {failure_count} failed")
            logger.info(
                f"Total space saved: {total_storage_info['total_space_saved_human']} (compressed from {total_storage_info['total_original_size_human']} to {total_storage_info['total_compressed_size_human']})"
            )

        return success_count, failure_count, total_storage_info

    def archive_specific_profile(self, email: str, dry_run: bool = False) -> Tuple[bool, Optional[dict]]:
        """
        Archive a specific user's AVD to cold storage

        Args:
            email: Email address of the profile to archive
            dry_run: If True, perform all operations except deletion of local files

        Returns:
            Tuple[bool, Optional[dict]]: (success, storage_info)
        """
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()

        # Special case: never archive the seed clone AVD
        if email == AVDCreator.SEED_CLONE_EMAIL:
            logger.warning(f"Cannot archive seed clone AVD")
            return False, {"error": "Cannot archive seed clone AVD"}

        # Check if profile exists in database
        from database.connection import DatabaseConnection
        from database.repositories.user_repository import UserRepository

        with DatabaseConnection().get_session() as session:
            repo = UserRepository(session)
            user = repo.get_user_by_email(email)

        if not user:
            logger.warning(f"Profile not found for email {email}")
            return False, {"error": "Profile not found"}

        # Check if already in cold storage
        cold_storage_date = profile_manager.get_user_field(email, "cold_storage_date")
        if cold_storage_date and not dry_run:
            logger.warning(f"Profile {email} already in cold storage since {cold_storage_date}")
            return False, {"error": f"Already in cold storage since {cold_storage_date}"}

        # Archive the AVD
        success, storage_info = self.archive_avd_to_cold_storage(email, dry_run=dry_run)

        if success and storage_info:
            # Mark as in cold storage
            profile_manager.set_user_field(email, "cold_storage_date", datetime.now().isoformat())
            if dry_run:
                profile_manager.set_user_field(email, "cold_storage_dry_run", True)

            logger.info(f"Successfully archived specific profile {email} to cold storage")

        return success, storage_info

    def restore_from_local_backup(self, email: str) -> bool:
        """
        Restore AVD from local cold storage backup (used to revert dry runs)

        Args:
            email: Email address of the profile to restore

        Returns:
            bool: True if successful, False otherwise
        """
        from views.core.avd_profile_manager import AVDProfileManager

        profile_manager = AVDProfileManager.get_instance()
        avd_name = profile_manager.get_avd_for_email(email)

        if not avd_name:
            logger.warning(f"No AVD name found for email {email}")
            return False

        # Check if backup exists
        backup_dir = os.path.join(self.local_cold_storage_dir, email)
        backup_avd_path = os.path.join(backup_dir, f"{avd_name}.avd")
        backup_ini_path = os.path.join(backup_dir, f"{avd_name}.ini")

        if not os.path.exists(backup_avd_path) or not os.path.exists(backup_ini_path):
            logger.warning(f"No local backup found for {email}")
            return False

        try:
            # Restore AVD files
            target_avd_path = os.path.join(self.avd_base_path, f"{avd_name}.avd")
            target_ini_path = os.path.join(self.avd_base_path, f"{avd_name}.ini")

            # Remove existing files if they exist
            if os.path.exists(target_avd_path):
                shutil.rmtree(target_avd_path)
            if os.path.exists(target_ini_path):
                os.unlink(target_ini_path)

            # Move files back
            shutil.move(backup_avd_path, target_avd_path)
            shutil.move(backup_ini_path, target_ini_path)

            # Clean up backup directory
            shutil.rmtree(backup_dir)

            # Clear cold storage flags
            profile_manager.set_user_field(email, "cold_storage_date", None)
            profile_manager.set_user_field(email, "cold_storage_dry_run", None)

            logger.info(f"Successfully restored AVD for {email} from local backup")
            return True

        except Exception as e:
            logger.error(f"Failed to restore AVD from local backup for {email}: {e}", exc_info=True)
            return False
