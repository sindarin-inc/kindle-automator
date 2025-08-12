"""Test concurrent access to the database."""

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv()

from database.connection import db_connection
from database.repositories.user_repository import UserRepository


class ConcurrentAccessTester:
    """Test concurrent database access scenarios."""

    def __init__(self):
        # Initialize database connection
        db_connection.initialize()
        db_connection.create_schema()
        self.results = []
        self.errors = []

    def test_concurrent_user_creation(self, num_threads=10):
        """Test multiple threads creating users simultaneously."""
        print(f"\n=== Testing concurrent user creation with {num_threads} threads ===")

        def create_user(thread_id):
            try:
                with db_connection.get_session() as session:
                    repo = UserRepository(session)
                    email = f"thread_{thread_id}@solreader.com"
                    # First try to get existing user
                    user = repo.get_user_by_email(email)
                    if user:
                        return f"Thread {thread_id}: User {email} already exists"
                    user = repo.create_user(email, f"AVD_Thread_{thread_id}")
                    return f"Thread {thread_id}: Created user {email}"
            except Exception as e:
                if "already exists" in str(e):
                    return f"Thread {thread_id}: User already exists (race condition)"
                error_msg = f"Thread {thread_id}: Error - {str(e)}"
                self.errors.append(error_msg)
                return error_msg

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(create_user, i) for i in range(num_threads)]

            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                print(result)

        print(f"Created {len(self.results) - len(self.errors)} users successfully")
        print(f"Errors: {len(self.errors)}")

    def test_concurrent_updates(self, num_threads=20):
        """Test multiple threads updating the same user."""
        print(f"\n=== Testing concurrent updates with {num_threads} threads ===")

        # Create or get test user first
        test_email = "concurrent_test@solreader.com"
        with db_connection.get_session() as session:
            repo = UserRepository(session)
            user = repo.get_user_by_email(test_email)
            if not user:
                repo.create_user(test_email, "ConcurrentTestAVD")

        def update_user(thread_id):
            try:
                with db_connection.get_session() as session:
                    repo = UserRepository(session)

                    # Each thread updates different fields
                    if thread_id % 4 == 0:
                        field = "timezone"
                        value = f"UTC+{thread_id}"
                        repo.update_user_field(test_email, field, value)
                    elif thread_id % 4 == 1:
                        field = "emulator_settings.animations_disabled"
                        value = thread_id % 2 == 0
                        repo.update_user_field(test_email, field, value)
                    elif thread_id % 4 == 2:
                        field = "library_settings.view_type"
                        value = "grid" if thread_id % 2 == 0 else "list"
                        repo.update_user_field(test_email, field, value)
                    else:
                        field = "preferences.test_pref"
                        value = f"value_{thread_id}"
                        repo.update_user_field(test_email, field, value)

                    return f"Thread {thread_id}: Updated {field} = {value}"
            except Exception as e:
                error_msg = f"Thread {thread_id}: Error - {str(e)}"
                self.errors.append(error_msg)
                return error_msg

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(update_user, i) for i in range(num_threads)]

            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                print(result)

        elapsed_time = time.time() - start_time
        print(f"\nCompleted {num_threads} updates in {elapsed_time:.2f} seconds")
        print(f"Successful updates: {len(self.results) - len(self.errors)}")
        print(f"Errors: {len(self.errors)}")

    def test_concurrent_reads_writes(self, num_threads=30):
        """Test mixed read and write operations."""
        print(f"\n=== Testing concurrent reads and writes with {num_threads} threads ===")

        # Create or get test users
        test_emails = [f"readwrite_{i}@solreader.com" for i in range(5)]
        with db_connection.get_session() as session:
            repo = UserRepository(session)
            for email in test_emails:
                user = repo.get_user_by_email(email)
                if not user:
                    repo.create_user(email, f"AVD_{email}")

        def mixed_operations(thread_id):
            try:
                with db_connection.get_session() as session:
                    repo = UserRepository(session)

                    # Mix of operations
                    operation = thread_id % 3
                    email = test_emails[thread_id % len(test_emails)]

                    if operation == 0:  # Read
                        user = repo.get_user_by_email(email)
                        return f"Thread {thread_id}: Read user {email} - AVD: {user.avd_name}"
                    elif operation == 1:  # Update
                        repo.update_last_used(email, f"emulator_{thread_id}")
                        return f"Thread {thread_id}: Updated last_used for {email}"
                    else:  # Complex update
                        repo.update_user_field(
                            email, f"preferences.thread_{thread_id}", datetime.now(timezone.utc).isoformat()
                        )
                        return f"Thread {thread_id}: Added preference for {email}"
            except Exception as e:
                error_msg = f"Thread {thread_id}: Error - {str(e)}"
                self.errors.append(error_msg)
                return error_msg

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(mixed_operations, i) for i in range(num_threads)]

            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)
                print(result)

        print(f"\nCompleted {num_threads} operations")
        print(f"Successful operations: {len(self.results) - len(self.errors)}")
        print(f"Errors: {len(self.errors)}")

    def test_transaction_isolation(self):
        """Test transaction isolation levels."""
        print("\n=== Testing transaction isolation ===")

        test_email = "isolation_test@solreader.com"

        # Create or get test user
        with db_connection.get_session() as session:
            repo = UserRepository(session)
            user = repo.get_user_by_email(test_email)
            if not user:
                repo.create_user(test_email, "IsolationTestAVD")

        def long_transaction():
            """Simulate a long-running transaction."""
            try:
                with db_connection.get_session() as session:
                    repo = UserRepository(session)

                    # Start transaction
                    user = repo.get_user_by_email(test_email)
                    print("Long transaction: Got user, sleeping...")

                    # Simulate processing
                    time.sleep(2)

                    # Update after delay
                    repo.update_user_field(test_email, "timezone", "LongTransaction")
                    session.commit()
                    print("Long transaction: Committed")
                    return "Long transaction completed"
            except Exception as e:
                return f"Long transaction error: {e}"

        def quick_transaction():
            """Simulate a quick transaction."""
            try:
                time.sleep(0.5)  # Let long transaction start first

                with db_connection.get_session() as session:
                    repo = UserRepository(session)

                    # Try to update same user
                    print("Quick transaction: Attempting update...")
                    repo.update_user_field(test_email, "styles_updated", True)
                    session.commit()
                    print("Quick transaction: Committed")
                    return "Quick transaction completed"
            except Exception as e:
                return f"Quick transaction error: {e}"

        # Run both transactions concurrently
        with ThreadPoolExecutor(max_workers=2) as executor:
            long_future = executor.submit(long_transaction)
            quick_future = executor.submit(quick_transaction)

            print(long_future.result())
            print(quick_future.result())

    def verify_data_integrity(self):
        """Verify data integrity after concurrent operations."""
        print("\n=== Verifying data integrity ===")

        with db_connection.get_session() as session:
            repo = UserRepository(session)

            # Check all users
            all_users = repo.get_all_users()
            print(f"Total users in database: {len(all_users)}")

            # Check for any inconsistencies
            for user in all_users:
                # Verify required relationships exist
                if not user.emulator_settings:
                    print(f"WARNING: User {user.email} missing emulator_settings")
                if not user.device_identifiers:
                    print(f"WARNING: User {user.email} missing device_identifiers")
                if not user.library_settings:
                    print(f"WARNING: User {user.email} missing library_settings")
                if not user.reading_settings:
                    print(f"WARNING: User {user.email} missing reading_settings")

            # Check version numbers (should increment with updates)
            for user in all_users:
                if user.version > 1:
                    print(f"User {user.email} has version {user.version} (updated)")

    def cleanup_test_data(self):
        """Clean up test data."""
        print("\n=== Skipping cleanup (shared dev DB) ===")
        # Don't delete users since we're using the same DB as dev
        pass


def main():
    """Run all concurrent access tests."""
    tester = ConcurrentAccessTester()

    try:
        # Run tests
        tester.test_concurrent_user_creation(num_threads=10)
        tester.test_concurrent_updates(num_threads=20)
        tester.test_concurrent_reads_writes(num_threads=30)
        tester.test_transaction_isolation()
        tester.verify_data_integrity()

        # Summary
        print("\n=== Test Summary ===")
        print(f"Total operations: {len(tester.results)}")
        print(f"Total errors: {len(tester.errors)}")

        if tester.errors:
            print("\nErrors encountered:")
            for error in tester.errors:
                print(f"  - {error}")

    finally:
        # Cleanup
        tester.cleanup_test_data()
        db_connection.dispose()


if __name__ == "__main__":
    main()
