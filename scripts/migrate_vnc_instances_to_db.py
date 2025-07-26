#!/usr/bin/env python3
"""Script to migrate VNC instances from JSON file to database."""

import json
import logging
import os
import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

from database.connection import db_connection
from database.models import VNCInstance
from database.repositories.vnc_instance_repository import VNCInstanceRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_json_instances(json_path: str) -> list:
    """Load VNC instances from JSON file."""
    if not os.path.exists(json_path):
        logger.warning(f"JSON file not found: {json_path}")
        return []

    try:
        with open(json_path, "r") as f:
            data = json.load(f)
            return data.get("instances", [])
    except Exception as e:
        logger.error(f"Error loading JSON file: {e}")
        return []


def migrate_instances(json_path: str, dry_run: bool = False) -> None:
    """Migrate VNC instances from JSON to database."""
    logger.info(f"Starting VNC instance migration from {json_path}")
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    # Load instances from JSON
    json_instances = load_json_instances(json_path)
    if not json_instances:
        logger.info("No instances found in JSON file")
        return

    logger.info(f"Found {len(json_instances)} instances in JSON file")

    repository = VNCInstanceRepository()

    # Check if database already has instances
    existing_count = repository.count_instances()
    if existing_count > 0 and not dry_run:
        logger.warning(f"Database already contains {existing_count} VNC instances")
        response = input("Do you want to continue and add these instances? (y/n): ")
        if response.lower() != "y":
            logger.info("Migration cancelled")
            return

    # Prepare instances for bulk creation
    instances_to_create = []
    skipped = 0
    migrated = 0

    with db_connection.get_session() as session:
        for json_instance in json_instances:
            instance_id = json_instance.get("id")

            # Check if instance already exists
            existing = session.query(VNCInstance).filter_by(id=instance_id).first()
            if existing:
                logger.info(f"Instance {instance_id} already exists in database, skipping")
                skipped += 1
                continue

            # Prepare instance data
            instance_data = {
                "id": instance_id,
                "display": json_instance.get("display", instance_id),
                "vnc_port": json_instance.get("vnc_port"),
                "appium_port": json_instance.get("appium_port"),
                "emulator_port": json_instance.get("emulator_port"),
                "emulator_id": json_instance.get("emulator_id"),
                "assigned_profile": json_instance.get("assigned_profile"),
                "appium_pid": json_instance.get("appium_pid"),
                "appium_running": json_instance.get("appium_running", False),
                "appium_last_health_check": None,  # Will need to convert timestamp if needed
                "appium_system_port": json_instance.get("appium_system_port"),
                "appium_chromedriver_port": json_instance.get("appium_chromedriver_port"),
                "appium_mjpeg_server_port": json_instance.get("appium_mjpeg_server_port"),
            }

            # Handle appium_last_health_check timestamp conversion
            if json_instance.get("appium_last_health_check"):
                from datetime import datetime

                try:
                    timestamp = float(json_instance["appium_last_health_check"])
                    instance_data["appium_last_health_check"] = datetime.fromtimestamp(timestamp)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid timestamp for instance {instance_id}: {json_instance.get('appium_last_health_check')}"
                    )

            if dry_run:
                logger.info(f"Would create instance: {instance_data}")
            else:
                instances_to_create.append(instance_data)

            migrated += 1

    # Bulk create instances if not dry run
    if not dry_run and instances_to_create:
        try:
            created = repository.bulk_create_instances(instances_to_create)
            logger.info(f"Successfully created {len(created)} VNC instances in database")
        except Exception as e:
            logger.error(f"Error creating instances: {e}")
            raise

    # Summary
    logger.info(f"\nMigration Summary:")
    logger.info(f"  Total instances in JSON: {len(json_instances)}")
    logger.info(f"  Instances migrated: {migrated}")
    logger.info(f"  Instances skipped (already exist): {skipped}")

    if not dry_run and migrated > 0:
        # Backup the JSON file
        backup_path = f"{json_path}.backup"
        try:
            import shutil

            shutil.copy2(json_path, backup_path)
            logger.info(f"Created backup of JSON file at: {backup_path}")
        except Exception as e:
            logger.warning(f"Could not create backup: {e}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Migrate VNC instances from JSON to database")
    parser.add_argument(
        "--json-path",
        default="user_data/vnc_instance_map.json",
        help="Path to the VNC instance JSON file (default: user_data/vnc_instance_map.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without making any changes",
    )

    args = parser.parse_args()

    # Convert to absolute path
    json_path = os.path.abspath(args.json_path)

    try:
        migrate_instances(json_path, dry_run=args.dry_run)
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
