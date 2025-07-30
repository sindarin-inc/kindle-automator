#!/usr/bin/env python3
"""Database connection utility for Makefile commands.
Detects if running locally with Docker or remotely with DATABASE_URL.
"""

import argparse
import os
import subprocess
import sys
from urllib.parse import urlparse

# Debug: Script started
if "--debug" in sys.argv:
    print("Debug: Script started", file=sys.stderr)
    sys.stderr.flush()

import psycopg2
from psycopg2.extras import RealDictCursor

# Default values
DOCKER_CONTAINER = "sol_postgres"
LOCAL_DB_PORT = "5496"
LOCAL_DB_USER = "local"
LOCAL_DB_NAME = "kindle_dev"


def is_docker_running():
    """Check if Docker container is running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=True
        )
        return DOCKER_CONTAINER in result.stdout.strip().split("\n")
    except subprocess.CalledProcessError:
        return False


def ensure_local_db_exists():
    """Create local development database if it doesn't exist."""
    # Check if database already exists
    check_cmd = [
        "docker",
        "exec",
        DOCKER_CONTAINER,
        "psql",
        "-p",
        LOCAL_DB_PORT,
        "-U",
        LOCAL_DB_USER,
        "-d",
        "sol_dev",
        "-tAc",
        f"SELECT 1 FROM pg_database WHERE datname = '{LOCAL_DB_NAME}'",
    ]

    result = subprocess.run(check_cmd, capture_output=True, text=True)

    if result.stdout.strip() != "1":
        # Database doesn't exist, create it
        create_cmd = [
            "docker",
            "exec",
            DOCKER_CONTAINER,
            "psql",
            "-p",
            LOCAL_DB_PORT,
            "-U",
            LOCAL_DB_USER,
            "-d",
            "sol_dev",
            "-c",
            f"CREATE DATABASE {LOCAL_DB_NAME}",
        ]
        try:
            subprocess.run(create_cmd, check=True, capture_output=True, text=True)
            print(f"Created local database '{LOCAL_DB_NAME}'")
        except subprocess.CalledProcessError as e:
            # Database might already exist or other error
            if "already exists" not in e.stderr:
                print(f"Warning: Could not create database: {e.stderr}")
                # Continue anyway - the connection will fail later if there's a real problem


def get_connection_params(debug=False):
    """Get database connection parameters."""
    if is_docker_running():
        if debug:
            print(f"Debug: Docker container '{DOCKER_CONTAINER}' is running")
        # Use Docker container for local development
        # Ensure database exists first
        ensure_local_db_exists()
        params = {
            "host": "localhost",
            "port": LOCAL_DB_PORT,
            "user": LOCAL_DB_USER,
            "database": LOCAL_DB_NAME,
            "password": "local",  # Default password for local development
        }
        if debug:
            print(
                f"Debug: Using local Docker connection - host={params['host']}, port={params['port']}, db={params['database']}"
            )
        return params
    else:
        if debug:
            print(f"Debug: Docker container '{DOCKER_CONTAINER}' not running, using DATABASE_URL")
        # Use DATABASE_URL from environment
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print(
                "Error: DATABASE_URL not set and Docker container '{}' not running".format(DOCKER_CONTAINER)
            )
            sys.exit(1)

        # Strip quotes from DATABASE_URL
        database_url = database_url.strip('"')

        if debug:
            # Mask password in debug output
            masked_url = database_url
            if "@" in masked_url and ":" in masked_url:
                start = masked_url.find("://") + 3
                at_pos = masked_url.find("@")
                colon_pos = masked_url.rfind(":", start, at_pos)
                if colon_pos > start:
                    masked_url = masked_url[: colon_pos + 1] + "****" + masked_url[at_pos:]
            print(f"Debug: Using DATABASE_URL = {masked_url}")

        # Parse DATABASE_URL
        parsed = urlparse(database_url)
        params = {
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "user": parsed.username,
            "database": parsed.path[1:] if parsed.path else None,
            "password": parsed.password,
        }
        if debug:
            print(
                f"Debug: Parsed connection - host={params['host']}, port={params['port']}, db={params['database']}, user={params['user']}"
            )
        return params


def execute_query(query, debug=False):
    """Execute a SQL query and return results."""
    params = get_connection_params(debug)

    try:
        if debug:
            print(f"Debug: Attempting to connect to database...")
            print(f"Debug: Connection timeout set to 10 seconds")

        # Add connection timeout and SSL mode handling
        connect_params = params.copy()
        connect_params["connect_timeout"] = 10

        # Handle SSL mode from DATABASE_URL
        if "sslmode" not in connect_params:
            # Check if it's in the database URL as a query parameter
            if not is_docker_running():
                database_url = os.environ.get("DATABASE_URL", "").strip('"')
                if "sslmode=" in database_url:
                    sslmode = database_url.split("sslmode=")[1].split("&")[0]
                    connect_params["sslmode"] = sslmode
                    if debug:
                        print(f"Debug: SSL mode = {sslmode}")

        conn = psycopg2.connect(**connect_params)
        conn.autocommit = True
        if debug:
            print(f"Debug: Connected successfully!")

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

    except psycopg2.OperationalError as e:
        print(f"Database connection error: {e}")
        if debug:
            print(f"Debug: Connection failed with parameters:")
            print(f"Debug:   host={params['host']}")
            print(f"Debug:   port={params['port']}")
            print(f"Debug:   database={params['database']}")
            print(f"Debug:   user={params['user']}")
            if "sslmode" in connect_params:
                print(f"Debug:   sslmode={connect_params['sslmode']}")
        sys.exit(1)
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        sys.exit(1)
    finally:
        if "conn" in locals():
            conn.close()


def execute_file(sql_file, debug=False):
    """Execute SQL from a file."""
    if not os.path.exists(sql_file):
        print(f"Error: SQL file not found: {sql_file}")
        sys.exit(1)

    with open(sql_file, "r") as f:
        sql_content = f.read()

    params = get_connection_params(debug)

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
    params = get_connection_params()

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
            LOCAL_DB_NAME,
        ]
        subprocess.run(cmd)
    else:
        # Use psql with DATABASE_URL
        database_url = os.environ.get("DATABASE_URL")
        subprocess.run(["psql", database_url])


def dump_database(output_file):
    """Dump the database."""
    params = get_connection_params()

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
            LOCAL_DB_NAME,
        ]
        with open(output_file, "w") as f:
            subprocess.run(cmd, stdout=f, check=True)
    else:
        database_url = os.environ.get("DATABASE_URL")
        cmd = ["pg_dump", database_url]
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
    parser.add_argument("--debug", action="store_true", help="Enable debug output")

    args = parser.parse_args()

    # Enable debug mode
    debug = args.debug

    if debug:
        print(f"Debug: Command = {args.command}")
        print(f"Debug: Environment file = {args.env}")
        print(f"Debug: File exists = {os.path.exists(args.env)}")

    # Load environment file if it exists
    if os.path.exists(args.env):
        if debug:
            print(f"Debug: Loading environment from {args.env}")
        with open(args.env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        # Strip quotes from value
                        value = value.strip('"')
                        os.environ[key] = value
                        if debug and key == "DATABASE_URL":
                            # Mask password in debug output
                            masked_url = value
                            if "@" in masked_url and ":" in masked_url:
                                start = masked_url.find("://") + 3
                                at_pos = masked_url.find("@")
                                colon_pos = masked_url.rfind(":", start, at_pos)
                                if colon_pos > start:
                                    masked_url = masked_url[: colon_pos + 1] + "****" + masked_url[at_pos:]
                            print(f"Debug: Set DATABASE_URL = {masked_url}")
    else:
        if debug:
            print(f"Debug: Environment file {args.env} not found")

    # Execute command
    if args.command == "init":
        if args.file:
            execute_file(args.file, debug)
        else:
            print("Error: --file required for init command")
            sys.exit(1)

    elif args.command == "query":
        if args.args:
            execute_query(args.args, debug)
        elif args.file:
            execute_file(args.file, debug)
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
