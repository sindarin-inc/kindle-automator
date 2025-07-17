#!/usr/bin/env python3
"""Migrate users.json data to PostgreSQL database."""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# Load environment variables BEFORE importing database modules
env_path = project_root / '.env'
load_dotenv(env_path)

# Now import database modules after environment is loaded
from database.connection import DatabaseConnection
from database.repositories.user_repository import UserRepository

# Create a new database connection instance
db_connection = DatabaseConnection()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
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


def migrate_user_data(email: str, user_data: dict, repo: UserRepository) -> bool:
    """Migrate a single user's data to the database."""
    try:
        # Create or get the user
        user, created = repo.get_or_create_user(email, user_data.get("avd_name"))
        
        if created:
            logger.info(f"Created new user: {email}")
        else:
            logger.info(f"Updating existing user: {email}")
        
        # Update basic user fields
        if "last_used" in user_data and user_data["last_used"]:
            repo.update_user_field(email, "last_used", datetime.fromtimestamp(user_data["last_used"]))
        
        if "auth_date" in user_data and user_data["auth_date"]:
            repo.update_user_field(email, "auth_date", datetime.fromisoformat(user_data["auth_date"]))
        
        # Update boolean fields
        bool_fields = [
            "was_running_at_restart", "styles_updated", "created_from_seed_clone",
            "post_boot_randomized", "needs_device_randomization"
        ]
        for field in bool_fields:
            if field in user_data:
                repo.update_user_field(email, field, user_data[field])
        
        # Update string fields
        string_fields = ["timezone", "kindle_version_name", "kindle_version_code", "last_snapshot"]
        for field in string_fields:
            if field in user_data and user_data[field]:
                repo.update_user_field(email, field, user_data[field])
        
        # Update timestamp fields
        if "last_snapshot_timestamp" in user_data and user_data["last_snapshot_timestamp"]:
            repo.update_user_field(
                email, 
                "last_snapshot_timestamp", 
                datetime.fromisoformat(user_data["last_snapshot_timestamp"])
            )
        
        # Update emulator settings
        if "emulator_settings" in user_data:
            settings = user_data["emulator_settings"]
            for key, value in settings.items():
                if key == "memory_optimization_timestamp" and value:
                    value = datetime.fromtimestamp(value)
                repo.update_user_field(email, f"emulator_settings.{key}", value)
        
        # Update device identifiers
        if "device_identifiers" in user_data:
            identifiers = user_data["device_identifiers"]
            # Map the JSON keys to database field names
            field_mapping = {
                "hw.wifi.mac": "hw_wifi_mac",
                "hw.ethernet.mac": "hw_ethernet_mac",
                "ro.serialno": "ro_serialno",
                "ro.build.id": "ro_build_id",
                "ro.product.name": "ro_product_name",
                "android_id": "android_id"
            }
            for json_key, db_field in field_mapping.items():
                if json_key in identifiers:
                    repo.update_user_field(email, f"device_identifiers.{db_field}", identifiers[json_key])
        
        # Update library settings
        if "library_settings" in user_data:
            settings = user_data["library_settings"]
            for key, value in settings.items():
                repo.update_user_field(email, f"library_settings.{key}", value)
        
        # Update reading settings
        if "reading_settings" in user_data:
            settings = user_data["reading_settings"]
            for key, value in settings.items():
                repo.update_user_field(email, f"reading_settings.{key}", value)
        
        # Update preferences
        if "preferences" in user_data and user_data["preferences"]:
            for key, value in user_data["preferences"].items():
                repo.update_user_field(email, f"preferences.{key}", value)
        
        logger.info(f"Successfully migrated user: {email}")
        return True
        
    except Exception as e:
        logger.error(f"Error migrating user {email}: {e}", exc_info=True)
        return False


def main():
    """Main migration function."""
    # Determine the users.json file path
    users_file = os.path.join(project_root, "user_data", "users.json")
    
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
        os.system("cd /Users/sclay/projects/sindarin/kindle-automator && alembic upgrade head")
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