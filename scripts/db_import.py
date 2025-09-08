#!/usr/bin/env python3
"""Import database from JSON format backup."""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.connection import DatabaseConnection
from database.models import (
    BookPosition,
    DeviceIdentifiers,
    EmulatorSettings,
    EmulatorShutdownFailure,
    LibrarySettings,
    ReadingSettings,
    StaffToken,
    User,
    UserPreference,
    VNCInstance,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def parse_datetime(date_string):
    """Parse ISO format datetime string."""
    if date_string is None:
        return None
    if isinstance(date_string, str):
        return datetime.fromisoformat(date_string)
    return date_string


def import_table_from_dict(session: Session, model_class, records, field_mappings=None):
    """Import records into a table from dictionary data."""
    field_mappings = field_mappings or {}
    imported_count = 0

    for record_dict in records:
        try:
            # Apply field mappings and conversions
            processed_dict = {}
            for key, value in record_dict.items():
                # Skip if field should be excluded
                if key in field_mappings and field_mappings[key] is None:
                    continue

                # Apply field mapping if exists
                mapped_key = field_mappings.get(key, key)

                # Convert datetime strings
                if "date" in key or "time" in key or key.endswith("_at"):
                    value = parse_datetime(value)

                processed_dict[mapped_key] = value

            # Create new record
            record = model_class(**processed_dict)
            session.add(record)
            imported_count += 1

        except Exception as e:
            logger.warning(f"Could not import record from {model_class.__tablename__}: {e}")
            logger.debug(f"Failed record: {record_dict}")

    return imported_count


def import_database(input_file: str, clear_existing: bool = False) -> None:
    """
    Import database from JSON format.

    Args:
        input_file: Path to input JSON file.
        clear_existing: If True, clear existing data before import.
    """
    try:
        # Load JSON data
        with open(input_file, "r") as f:
            import_data = json.load(f)

        logger.info(f"Loading data from {input_file}")
        logger.info(f"Export timestamp: {import_data.get('export_timestamp', 'Unknown')}")

        # Initialize database connection
        db_connection = DatabaseConnection()
        db_connection.initialize()

        with db_connection.get_session() as session:
            if clear_existing:
                logger.warning("Clearing existing database data...")
                # Clear tables in reverse dependency order
                tables_to_clear = [
                    BookPosition,
                    EmulatorShutdownFailure,
                    StaffToken,
                    VNCInstance,
                    UserPreference,
                    ReadingSettings,
                    LibrarySettings,
                    DeviceIdentifiers,
                    EmulatorSettings,
                    User,
                ]

                for model_class in tables_to_clear:
                    try:
                        session.query(model_class).delete()
                        logger.info(f"Cleared {model_class.__tablename__}")
                    except Exception as e:
                        logger.warning(f"Could not clear {model_class.__tablename__}: {e}")

                session.commit()

            # Import tables in dependency order
            import_order = [
                (User, "users", {}),
                (EmulatorSettings, "emulator_settings", {}),
                (DeviceIdentifiers, "device_identifiers", {}),
                (LibrarySettings, "library_settings", {}),
                (ReadingSettings, "reading_settings", {}),
                (UserPreference, "user_preferences", {}),
                (VNCInstance, "vnc_instances", {}),
                (StaffToken, "staff_tokens", {"token": None}),  # Don't import token values
                (EmulatorShutdownFailure, "emulator_shutdown_failures", {}),
                (BookPosition, "book_positions", {}),
            ]

            total_imported = 0
            tables_data = import_data.get("tables", {})

            for model_class, table_name, field_mappings in import_order:
                if table_name in tables_data:
                    logger.info(f"Importing {table_name}...")
                    records = tables_data[table_name]
                    count = import_table_from_dict(session, model_class, records, field_mappings)
                    logger.info(f"Imported {count} records into {table_name}")
                    total_imported += count
                else:
                    logger.warning(f"No data found for {table_name}")

            # Commit all changes
            session.commit()

            # Reset sequences if PostgreSQL
            if "postgresql" in str(session.bind.url):
                logger.info("Resetting PostgreSQL sequences...")
                for model_class, _, _ in import_order:
                    table_name = model_class.__tablename__
                    if hasattr(model_class, "id"):
                        try:
                            session.execute(
                                text(
                                    f"""
                                SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), 
                                             COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1, 
                                             false);
                            """
                                )
                            )
                        except Exception as e:
                            logger.debug(f"Could not reset sequence for {table_name}: {e}")

                session.commit()

        logger.info(f"Database import completed successfully")
        print(f"✓ Database imported from {input_file}")
        print(f"  - Imported {len(tables_data)} tables")
        print(f"  - Total records: {total_imported}")

    except FileNotFoundError:
        logger.error(f"Input file not found: {input_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in input file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to import database: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Import database from JSON format")
    parser.add_argument("input", help="Input JSON file path")
    parser.add_argument(
        "--clear", action="store_true", help="Clear existing data before import (WARNING: destructive!)"
    )

    args = parser.parse_args()

    if args.clear:
        response = input("WARNING: This will delete all existing data. Continue? (yes/no): ")
        if response.lower() != "yes":
            print("Import cancelled.")
            sys.exit(0)

    import_database(args.input, args.clear)


if __name__ == "__main__":
    main()
