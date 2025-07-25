#!/usr/bin/env python3
"""Migrate users.json data to PostgreSQL database."""
import configparser
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# Load environment variables BEFORE importing database modules
env_path = project_root / ".env"
load_dotenv(env_path)

# Now import database modules after environment is loaded
from database.connection import DatabaseConnection
from database.models import (
    DeviceIdentifiers,
    EmulatorSettings,
    LibrarySettings,
    ReadingSettings,
    UserPreference,
)
from database.repositories.user_repository import UserRepository

# Create a new database connection instance
db_connection = DatabaseConnection()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_users_json(file_path: str) -> dict:
    """Load users data from JSON file."""
    if not os.path.exists(file_path):
        logger.error(f"Users file not found: {file_path}")
        return {}

    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON file: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return {}


def get_avd_system_image(avd_name: str, avd_base_dir: str = "/opt/android-sdk") -> tuple[str, str]:
    """
    Extract system image info from AVD config file.

    Returns:
        tuple: (android_version, system_image) or (None, None) if not found
    """
    config_path = os.path.join(avd_base_dir, "avd", f"{avd_name}.avd", "config.ini")

    if not os.path.exists(config_path):
        logger.warning(f"Config file not found: {config_path}")
        return None, None

    try:
        config = configparser.ConfigParser()
        config.read(config_path)

        # Get image.sysdir.1 value
        # Example: "system-images/android-30/google_apis/x86_64/"
        sysdir = config.get("DEFAULT", "image.sysdir.1", fallback=None)

        if not sysdir:
            logger.warning(f"No image.sysdir.1 found in {config_path}")
            return None, None

        # Parse the system image info
        # Convert path format to sdkmanager format
        # "system-images/android-30/google_apis/x86_64/" -> "system-images;android-30;google_apis;x86_64"
        sysdir = sysdir.rstrip("/")  # Remove trailing slash
        parts = sysdir.split("/")

        if len(parts) >= 4:
            system_image = ";".join(parts)
            # Extract android version from "android-30" -> "30"
            android_version = parts[1].replace("android-", "")
            return android_version, system_image
        else:
            logger.warning(f"Unexpected sysdir format: {sysdir}")
            return None, None

    except Exception as e:
        logger.error(f"Error reading config file {config_path}: {e}")
        return None, None


def migrate_user_data(email: str, user_data: dict, repo: UserRepository) -> bool:
    """Migrate a single user's data to the database."""
    try:
        # Create or get the user
        user, created = repo.get_or_create_user(email, user_data.get("avd_name"))

        if created:
            logger.info(f"Created new user: {email}")
        else:
            logger.info(f"Updating existing user: {email}")

        # Instead of multiple individual updates, collect all updates and do them in one go
        # First, update the user object directly
        if "last_used" in user_data and user_data["last_used"]:
            user.last_used = datetime.fromtimestamp(user_data["last_used"])

        if "auth_date" in user_data and user_data["auth_date"]:
            user.auth_date = datetime.fromisoformat(user_data["auth_date"])

        # Update boolean fields
        bool_fields = [
            "was_running_at_restart",
            "styles_updated",
            "created_from_seed_clone",
            "post_boot_randomized",
            "needs_device_randomization",
        ]
        for field in bool_fields:
            if field in user_data:
                setattr(user, field, user_data[field])

        # Update string fields
        string_fields = ["timezone", "kindle_version_name", "kindle_version_code", "last_snapshot"]
        for field in string_fields:
            if field in user_data and user_data[field]:
                setattr(user, field, user_data[field])

        # Update timestamp fields
        if "last_snapshot_timestamp" in user_data and user_data["last_snapshot_timestamp"]:
            user.last_snapshot_timestamp = datetime.fromisoformat(user_data["last_snapshot_timestamp"])

        # Get system image info from AVD config if AVD name is available
        avd_name = user_data.get("avd_name") or user.avd_name
        if avd_name:
            android_version, system_image = get_avd_system_image(avd_name)
            if android_version and system_image:
                user.android_version = android_version
                user.system_image = system_image
                logger.info(f"Found system image for {email}: Android {android_version}")

        # Update emulator settings
        if "emulator_settings" in user_data:
            settings = user_data["emulator_settings"]
            if not user.emulator_settings:
                user.emulator_settings = EmulatorSettings(user=user)
            for key, value in settings.items():
                if key == "memory_optimization_timestamp" and value:
                    value = datetime.fromtimestamp(value)
                setattr(user.emulator_settings, key, value)

        # Update device identifiers
        if "device_identifiers" in user_data:
            identifiers = user_data["device_identifiers"]
            if not user.device_identifiers:
                user.device_identifiers = DeviceIdentifiers(user=user)
            # Map the JSON keys to database field names
            field_mapping = {
                "hw.wifi.mac": "hw_wifi_mac",
                "hw.ethernet.mac": "hw_ethernet_mac",
                "ro.serialno": "ro_serialno",
                "ro.build.id": "ro_build_id",
                "ro.product.name": "ro_product_name",
                "android_id": "android_id",
            }
            for json_key, db_field in field_mapping.items():
                if json_key in identifiers:
                    setattr(user.device_identifiers, db_field, identifiers[json_key])

        # Update library settings
        if "library_settings" in user_data:
            settings = user_data["library_settings"]
            if not user.library_settings:
                user.library_settings = LibrarySettings(user=user)
            for key, value in settings.items():
                setattr(user.library_settings, key, value)

        # Update reading settings
        if "reading_settings" in user_data:
            settings = user_data["reading_settings"]
            if not user.reading_settings:
                user.reading_settings = ReadingSettings(user=user)
            for key, value in settings.items():
                setattr(user.reading_settings, key, value)

        # Update preferences
        if "preferences" in user_data and user_data["preferences"]:
            for key, value in user_data["preferences"].items():
                # Find existing preference
                pref = next((p for p in user.preferences if p.preference_key == key), None)
                if pref:
                    pref.preference_value = json.dumps(value) if not isinstance(value, str) else value
                else:
                    new_pref = UserPreference(
                        user=user,
                        preference_key=key,
                        preference_value=json.dumps(value) if not isinstance(value, str) else value,
                    )
                    repo.session.add(new_pref)

        # Single commit for all changes
        repo.session.commit()
        logger.info(f"Successfully migrated user: {email}")
        return True

    except Exception as e:
        repo.session.rollback()
        logger.error(f"Error migrating user {email}: {e}", exc_info=True)
        return False


def main():
    """Main migration function."""

    # Determine the users.json file path based on environment
    # Check multiple possible locations for users.json
    possible_paths = [
        # Mac development environment path
        os.path.join(project_root, "user_data", "users.json"),
        # Production/staging path (AVD profile manager location)
        "/opt/android-sdk/profiles/users.json",
        # Alternative production path
        "/opt/android-sdk/user_data/users.json",
    ]

    users_file = None
    for path in possible_paths:
        if os.path.exists(path):
            users_file = path
            break

    if not users_file:
        logger.error(f"Could not find users.json in any of these locations: {possible_paths}")
        logger.info("Checking what files exist in /opt/android-sdk/...")

        # List directories in /opt/android-sdk to help debug
        if os.path.exists("/opt/android-sdk"):
            for root, dirs, files in os.walk("/opt/android-sdk"):
                if "users.json" in files:
                    logger.info(f"Found users.json at: {os.path.join(root, 'users.json')}")
                # Only go 2 levels deep
                if root.count(os.sep) - "/opt/android-sdk".count(os.sep) >= 2:
                    dirs[:] = []
        return

    logger.info(f"Starting migration from {users_file}")

    # Load users data
    users_data = load_users_json(users_file)
    if not users_data:
        logger.warning("No users data found to migrate")
        return

    logger.info(f"Found {len(users_data)} users to migrate")

    # Initialize database connection
    try:
        db_connection.initialize()
        db_connection.create_schema()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return

    # Run migrations to create tables
    logger.info("Running database migrations...")
    try:
        # Change to project root and run alembic
        os.chdir(project_root)
        result = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to run migrations: {result.stderr}")
            return
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Failed to run migrations: {e}")
        return

    # Migrate each user
    success_count = 0
    error_count = 0

    with db_connection.get_session() as session:
        repo = UserRepository(session)

        for email, user_data in users_data.items():
            if migrate_user_data(email, user_data, repo):
                success_count += 1
            else:
                error_count += 1

    # Create backup of original file
    backup_path = users_file + ".backup"
    try:
        import shutil

        shutil.copy2(users_file, backup_path)
        logger.info(f"Created backup at {backup_path}")
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")

    # Summary
    logger.info(f"Migration completed: {success_count} successful, {error_count} errors")

    if error_count == 0:
        logger.info("All users migrated successfully!")
        logger.info(f"Original file backed up to: {backup_path}")
        logger.info("You can now update AVDProfileManager to use the database")
    else:
        logger.warning(f"Migration completed with {error_count} errors. Please check the logs.")


if __name__ == "__main__":
    main()
