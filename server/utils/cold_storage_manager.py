import logging
import os
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

import boto3
from botocore.client import Config
from dotenv import load_dotenv

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
        global _instance
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
            logger.error(f"Failed to initialize S3 client: {e}")
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

    def archive_avd_to_cold_storage(self, email: str, dry_run: bool = False) -> Tuple[bool, Optional[dict]]:
        """
        Archive an AVD to cold storage

        Args:
            email: Email address of the profile to archive
            dry_run: If True, perform all operations except deletion of local files

        Returns:
            Tuple[bool, Optional[dict]]: (success, storage_info) where storage_info contains:
                - original_size: Size of AVD before compression
                - compressed_size: Size of compressed archive
                - space_saved: Space saved in bytes
                - compression_ratio: Compression ratio percentage
                - dry_run: Whether this was a dry run
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

        temp_path = None
        try:
            logger.info(f"Starting cold storage archival for email {email}")

            # Calculate original size
            original_size = self._get_directory_size(avd_path) + os.path.getsize(ini_path)
            logger.info(f"Original AVD size: {self._format_bytes(original_size)}")

            logger.info(f"Creating temporary archive file...")
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_file:
                temp_path = temp_file.name
            logger.info(f"Temporary archive path: {temp_path}")

            logger.info(f"Starting compression of AVD files...")
            start_time = time.time()
            with tarfile.open(temp_path, "w:gz", compresslevel=1) as tar:  # Use faster compression
                logger.info(f"Adding {avd_path} to archive...")
                tar.add(avd_path, arcname=f"{avd_name}.avd")
                logger.info(f"Adding {ini_path} to archive...")
                tar.add(ini_path, arcname=f"{avd_name}.ini")
            compression_time = time.time() - start_time
            logger.info(f"Compression completed in {compression_time:.2f} seconds")

            # Get compressed size
            compressed_size = os.path.getsize(temp_path)
            logger.info(f"Compressed size: {self._format_bytes(compressed_size)}")

            # Calculate savings
            space_saved = original_size - compressed_size
            compression_ratio = (1 - compressed_size / original_size) * 100

            logger.info(
                f"Space saved: {self._format_bytes(space_saved)} ({compression_ratio:.1f}% compression)"
            )

            # Always upload to S3, even in dry run
            archive_key = f"{self.cold_storage_prefix}{email}/{avd_name}.tar.gz"

            logger.info(f"Starting S3 upload to {self.bucket_name}/{archive_key}")
            upload_start = time.time()
            try:
                with open(temp_path, "rb") as f:
                    self.s3_client.upload_fileobj(
                        f, self.bucket_name, archive_key, ExtraArgs={"ACL": "private"}
                    )
                upload_time = time.time() - upload_start
                logger.info(f"S3 upload completed in {upload_time:.2f} seconds")
            except Exception as e:
                logger.error(f"S3 upload failed: {e}")
                raise

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
                shutil.rmtree(avd_path)
                os.unlink(ini_path)

            storage_info = {
                "original_size": original_size,
                "compressed_size": compressed_size,
                "space_saved": space_saved,
                "compression_ratio": compression_ratio,
                "original_size_human": self._format_bytes(original_size),
                "compressed_size_human": self._format_bytes(compressed_size),
                "space_saved_human": self._format_bytes(space_saved),
                "dry_run": dry_run,
            }

            if dry_run:
                logger.info(f"DRY RUN: Successfully simulated archiving AVD for email {email}")
            else:
                logger.info(f"Successfully archived AVD for email {email} to cold storage")
            return True, storage_info

        except Exception as e:
            logger.error(f"Failed to archive AVD for email {email}: {e}")
            return False, None
        finally:
            # Always clean up the temp file
            if temp_path and os.path.exists(temp_path):
                logger.info(f"Cleaning up temporary archive file: {temp_path}")
                try:
                    os.unlink(temp_path)
                    logger.info("Temporary file cleaned up successfully")
                except Exception as e:
                    logger.error(f"Failed to clean up temporary file: {e}")

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
            archive_size = int(response.get('ContentLength', 0))
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
                logger.error(f"Archive verification failed: {e}")
                raise

            restore_info = {
                "archive_size": archive_size,
                "archive_size_human": self._format_bytes(archive_size),
                "download_time": download_time,
                "s3_key": archive_key,
                "dry_run": dry_run
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
            logger.error(f"Failed to restore AVD for email {email}: {e}")
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
            logger.error(f"Error checking cold storage for email {email}: {e}")
            return False

    def get_profiles_eligible_for_cold_storage(self, days_inactive: int = 30) -> list:
        """Get list of profiles eligible for cold storage based on last usage"""
        from views.core.avd_profile_manager import AVDProfileManager

        eligible_profiles = []
        profile_manager = AVDProfileManager.get_instance()
        cutoff_date = datetime.now() - timedelta(days=days_inactive)

        all_profiles = profile_manager.list_profiles()

        for profile in all_profiles:
            email = profile["email"]

            cold_storage_date = profile_manager.get_user_field(email, "cold_storage_date")
            if cold_storage_date:
                continue

            last_used_date = profile_manager.get_user_field(email, "last_used_date")
            if last_used_date:
                last_used_dt = datetime.fromisoformat(last_used_date)
                if last_used_dt < cutoff_date:
                    avd_name = profile["avd_name"]
                    avd_path = os.path.join(self.avd_base_path, f"{avd_name}.avd")
                    if os.path.exists(avd_path):
                        eligible_profiles.append(email)

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

        # Check if profile exists
        if email not in profile_manager.profiles_index:
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
            logger.error(f"Failed to restore AVD from local backup for {email}: {e}")
            return False
