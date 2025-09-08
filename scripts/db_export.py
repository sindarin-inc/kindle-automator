#!/usr/bin/env python3
"""Export entire database to JSON format for backup and migration."""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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


def datetime_handler(obj):
    """JSON serializer for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def export_table_to_dict(session: Session, model_class, exclude_fields=None):
    """Export a table to a dictionary."""
    exclude_fields = exclude_fields or []
    results = []

    try:
        for record in session.query(model_class).all():
            record_dict = {}
            for column in model_class.__table__.columns:
                if column.name not in exclude_fields:
                    value = getattr(record, column.name)
                    record_dict[column.name] = value
            results.append(record_dict)
    except Exception as e:
        logger.warning(f"Could not export {model_class.__tablename__}: {e}")

    return results


def export_database(output_file: str = None) -> None:
    """
    Export entire database to JSON format.

    Args:
        output_file: Path to output file. If None, uses default path with timestamp.
    """
    try:
        # Initialize database connection
        db_connection = DatabaseConnection()
        db_connection.initialize()

        # Prepare export data
        export_data = {"export_timestamp": datetime.now().isoformat(), "tables": {}}

        with db_connection.get_session() as session:
            # Export all tables
            tables_to_export = [
                (User, ["password"]),  # Exclude password field for security
                (EmulatorSettings, []),
                (DeviceIdentifiers, []),
                (LibrarySettings, []),
                (ReadingSettings, []),
                (UserPreference, []),
                (VNCInstance, []),
                (StaffToken, ["token"]),  # Exclude token for security
                (EmulatorShutdownFailure, []),
                (BookPosition, []),
            ]

            for model_class, exclude_fields in tables_to_export:
                table_name = model_class.__tablename__
                logger.info(f"Exporting {table_name}...")
                export_data["tables"][table_name] = export_table_to_dict(session, model_class, exclude_fields)
                logger.info(f"Exported {len(export_data['tables'][table_name])} records from {table_name}")

        # Generate output filename if not provided
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"backups/kindle_db_export_{timestamp}.json"

        # Ensure backup directory exists
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)

        # Write JSON output
        with open(output_file, "w") as f:
            json.dump(export_data, f, indent=2, default=datetime_handler, sort_keys=True)

        logger.info(f"Database exported successfully to {output_file}")
        print(f"✓ Database exported to {output_file}")

        # Print summary
        total_records = sum(len(records) for records in export_data["tables"].values())
        print(f"  - Exported {len(export_data['tables'])} tables")
        print(f"  - Total records: {total_records}")

    except Exception as e:
        logger.error(f"Failed to export database: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Export entire database to JSON format")
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (default: backups/kindle_db_export_TIMESTAMP.json)",
        default=None,
    )

    args = parser.parse_args()
    export_database(args.output)


if __name__ == "__main__":
    main()
