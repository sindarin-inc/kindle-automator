#!/usr/bin/env python3
"""Database connection utility for Makefile commands.
Detects if running locally with Docker or remotely with DATABASE_URL.
"""

import argparse
import os
import subprocess
import sys
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor

# Default values
DOCKER_CONTAINER = "sol_postgres"
LOCAL_DB_PORT = "5496"
LOCAL_DB_USER = "local"
LOCAL_DB_NAME = "sol_dev"
KINDLE_DB_NAME = "kindle_db"
KINDLE_SCHEMA = "kindle_automator"


def is_docker_running():
    """Check if Docker container is running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=True
        )
        return DOCKER_CONTAINER in result.stdout.strip().split("\n")
    except subprocess.CalledProcessError:
        return False


def get_connection_params(use_kindle_db=False):
    """Get database connection parameters."""
    if is_docker_running():
        # Use Docker container
        db_name = KINDLE_DB_NAME if use_kindle_db else LOCAL_DB_NAME
        return {
            "host": "localhost",
            "port": LOCAL_DB_PORT,
            "user": LOCAL_DB_USER,
            "database": db_name,
            "password": "local",  # Default password for local development
        }
    else:
        # Use DATABASE_URL from environment
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print(
                "Error: DATABASE_URL not set and Docker container '{}' not running".format(DOCKER_CONTAINER)
            )
            sys.exit(1)

        # Strip quotes from DATABASE_URL
        database_url = database_url.strip('"')

        # Parse DATABASE_URL
        parsed = urlparse(database_url)
        return {
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "user": parsed.username,
            "database": parsed.path[1:] if parsed.path else None,
            "password": parsed.password,
        }


def execute_query(query, use_kindle_db=False):
    """Execute a SQL query and return results."""
    params = get_connection_params(use_kindle_db)

    try:
        conn = psycopg2.connect(**params)
        conn.autocommit = True

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)

            # Check if query returns results
            if cur.description:
                results = cur.fetchall()
                if results:
                    # Print results in a nice format
                    headers = list(results[0].keys())

                    # Calculate column widths
                    widths = {}
                    for header in headers:
                        widths[header] = max(
                            len(str(header)), max(len(str(row.get(header, ""))) for row in results)
                        )

                    # Print header
                    header_line = " | ".join(str(header).ljust(widths[header]) for header in headers)
                    print(header_line)
                    print("-" * len(header_line))

                    # Print rows
                    for row in results:
                        print(
                            " | ".join(str(row.get(header, "")).ljust(widths[header]) for header in headers)
                        )
                else:
                    print("(No results)")
            else:
                print("Query executed successfully")

    except psycopg2.Error as e:
        print(f"Database error: {e}")
        sys.exit(1)
    finally:
        if "conn" in locals():
            conn.close()


def execute_file(sql_file, use_kindle_db=False):
    """Execute SQL from a file."""
    if not os.path.exists(sql_file):
        print(f"Error: SQL file not found: {sql_file}")
        sys.exit(1)

    with open(sql_file, "r") as f:
        sql_content = f.read()

    params = get_connection_params(use_kindle_db)

    try:
        conn = psycopg2.connect(**params)
        conn.autocommit = True

        with conn.cursor() as cur:
            cur.execute(sql_content)
            print(f"Executed SQL from {sql_file}")

    except psycopg2.Error as e:
        print(f"Database error: {e}")
        sys.exit(1)
    finally:
        if "conn" in locals():
            conn.close()


def interactive_session():
    """Start an interactive database session."""
    params = get_connection_params(use_kindle_db=True)

    if is_docker_running():
        # Use docker exec for interactive session
        cmd = [
            "docker",
            "exec",
            "-it",
            DOCKER_CONTAINER,
            "psql",
            "-p",
            LOCAL_DB_PORT,
            "-U",
            LOCAL_DB_USER,
            "-d",
            KINDLE_DB_NAME,
        ]
        subprocess.run(cmd)
    else:
        # Use psql with DATABASE_URL
        database_url = os.environ.get("DATABASE_URL")
        subprocess.run(["psql", database_url])


def dump_database(output_file):
    """Dump the database schema."""
    params = get_connection_params(use_kindle_db=True)

    if is_docker_running():
        cmd = [
            "docker",
            "exec",
            DOCKER_CONTAINER,
            "pg_dump",
            "-p",
            LOCAL_DB_PORT,
            "-U",
            LOCAL_DB_USER,
            "-d",
            KINDLE_DB_NAME,
            "-n",
            KINDLE_SCHEMA,
        ]
        with open(output_file, "w") as f:
            subprocess.run(cmd, stdout=f, check=True)
    else:
        database_url = os.environ.get("DATABASE_URL")
        cmd = ["pg_dump", database_url, "-n", KINDLE_SCHEMA]
        with open(output_file, "w") as f:
            subprocess.run(cmd, stdout=f, check=True)

    print(f"Database dumped to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Database connection utility")
    parser.add_argument(
        "--command",
        required=True,
        choices=["init", "query", "interactive", "dump"],
        help="Command to execute",
    )
    parser.add_argument("--env", default=".env", help="Environment file to load")
    parser.add_argument("--file", help="SQL file to execute")
    parser.add_argument("--args", help="Arguments for the command")

    args = parser.parse_args()

    # Load environment file if it exists
    if os.path.exists(args.env):
        with open(args.env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ[key] = value

    # Execute command
    if args.command == "init":
        if args.file:
            execute_file(args.file, use_kindle_db=False)
        else:
            print("Error: --file required for init command")
            sys.exit(1)

    elif args.command == "query":
        if args.args:
            execute_query(args.args, use_kindle_db=True)
        elif args.file:
            execute_file(args.file, use_kindle_db=True)
        else:
            print("Error: --args or --file required for query command")
            sys.exit(1)

    elif args.command == "interactive":
        interactive_session()

    elif args.command == "dump":
        if args.args:
            dump_database(args.args)
        else:
            print("Error: --args (output file) required for dump command")
            sys.exit(1)


if __name__ == "__main__":
    main()
