#!/usr/bin/env python3
"""Export users from PostgreSQL database to JSON format (like the original users.json)."""
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from database.connection import DatabaseConnection
from database.repositories.user_repository import UserRepository

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def export_users_to_json(output_file: str = None) -> None:
    """
    Export all users from the database to JSON format.

    Args:
        output_file: Path to output file. If None, prints to stdout.
    """
    try:
        # Initialize database connection
        db_connection = DatabaseConnection()
        db_connection.initialize()

        # Get all users from database
        with db_connection.get_session() as session:
            repo = UserRepository(session)
            users = repo.get_all_users()

            # Convert to dictionary format like original users.json
            users_dict = {}
            for user in users:
                user_data = repo.user_to_dict(user)
                # Remove database-specific fields
                user_data.pop("id", None)
                user_data.pop("created_at", None)
                user_data.pop("updated_at", None)
                users_dict[user.email] = user_data

        # Output the JSON
        json_output = json.dumps(users_dict, indent=2, sort_keys=True)

        if output_file:
            with open(output_file, "w") as f:
                f.write(json_output)
            logger.info(f"Exported {len(users_dict)} users to {output_file}")
        else:
            print(json_output)

    except Exception as e:
        logger.error(f"Failed to export users: {e}", exc_info=True)
        sys.exit(1)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Export users from database to JSON format")
    parser.add_argument("-o", "--output", help="Output file path (default: print to stdout)", default=None)
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty print with indentation (default: true)", default=True
    )

    args = parser.parse_args()

    export_users_to_json(args.output)


if __name__ == "__main__":
    main()
