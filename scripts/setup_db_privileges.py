#!/usr/bin/env python3
"""Setup database privileges for the Kindle Automator user."""

import os
import sys
from urllib.parse import urlparse

import psycopg2


def setup_privileges(admin_url, target_user):
    """Grant necessary privileges to the target user."""

    # Parse the admin URL
    parsed = urlparse(admin_url)

    # Connect as admin
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path[1:] if parsed.path else None,
        user=parsed.username,
        password=parsed.password,
        sslmode="require",
    )
    conn.autocommit = True

    try:
        with conn.cursor() as cur:
            print(f"Connected as {parsed.username} to setup privileges...")

            # Get the database name
            cur.execute("SELECT current_database();")
            db_name = cur.fetchone()[0]

            # Check if user already has CREATE privilege on database
            cur.execute(f"SELECT has_database_privilege('{target_user}', '{db_name}', 'CREATE');")
            has_create = cur.fetchone()[0]

            if not has_create:
                print(f"Granting CREATE privilege on database {db_name} to {target_user}...")
                cur.execute(f'GRANT CREATE ON DATABASE "{db_name}" TO "{target_user}";')
            else:
                print(f"User {target_user} already has CREATE privilege on database {db_name}")

            # Check schema privileges
            cur.execute(
                f"""
                SELECT has_schema_privilege('{target_user}', 'public', 'CREATE') AND
                       has_schema_privilege('{target_user}', 'public', 'USAGE');
            """
            )
            has_schema_privs = cur.fetchone()[0]

            if not has_schema_privs:
                print(f"Granting ALL privileges on schema public to {target_user}...")
                cur.execute(f'GRANT ALL ON SCHEMA public TO "{target_user}";')
            else:
                print(f"User {target_user} already has privileges on schema public")

            # Grant privileges on existing objects (always run as new objects may have been created)
            print(f"Ensuring privileges on existing objects...")
            cur.execute(f'GRANT ALL ON ALL TABLES IN SCHEMA public TO "{target_user}";')
            cur.execute(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO "{target_user}";')
            cur.execute(f'GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO "{target_user}";')

            # Check and set default privileges
            # Check if default privileges already exist
            cur.execute(
                f"""
                SELECT COUNT(*) FROM pg_default_acl 
                WHERE defaclrole = (SELECT oid FROM pg_roles WHERE rolname = current_user)
                AND defaclnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
            """
            )
            default_privs_count = cur.fetchone()[0]

            print(f"Setting default privileges for future objects...")
            # These are idempotent - they replace existing default privileges
            cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{target_user}";')
            cur.execute(
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{target_user}";'
            )
            cur.execute(
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO "{target_user}";'
            )

            # Also grant privileges for objects created by doadmin
            cur.execute(
                f'ALTER DEFAULT PRIVILEGES FOR ROLE "{parsed.username}" IN SCHEMA public GRANT ALL ON TABLES TO "{target_user}";'
            )
            cur.execute(
                f'ALTER DEFAULT PRIVILEGES FOR ROLE "{parsed.username}" IN SCHEMA public GRANT ALL ON SEQUENCES TO "{target_user}";'
            )

            print("Privileges setup completed successfully!")

    except psycopg2.Error as e:
        print(f"Database error: {e}")
        # Don't exit with error if privileges already exist
        if "already exists" in str(e) or "duplicate" in str(e):
            print("Some privileges may already exist, continuing...")
        else:
            raise
    finally:
        conn.close()


def main():
    # Load environment
    if len(sys.argv) > 1:
        env_file = sys.argv[1]
    else:
        env_file = ".env.staging"

    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        value = value.strip('"')
                        os.environ[key] = value

    # Get the admin URL
    admin_url = os.environ.get("POSTGRES_DOADMIN_DATABASE_URL")
    if not admin_url:
        print("Error: POSTGRES_DOADMIN_DATABASE_URL not found in environment")
        sys.exit(1)

    # Get the regular database URL to extract the user
    regular_url = os.environ.get("DATABASE_URL")
    if not regular_url:
        print("Error: DATABASE_URL not found in environment")
        sys.exit(1)

    # Extract the target user from the regular URL
    parsed_regular = urlparse(regular_url.strip('"'))
    target_user = parsed_regular.username

    print(f"Setting up privileges for user: {target_user}")
    setup_privileges(admin_url.strip('"'), target_user)


if __name__ == "__main__":
    main()
