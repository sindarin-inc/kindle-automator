"""Test concurrent access to the database."""

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv()

from database.connection import db_connection
from database.models import Base
from database.repositories.user_repository import UserRepository


class TestConcurrentAccess:
    """Test concurrent database access scenarios."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test database and clean up after tests."""
        # Initialize database connection
        db_connection.initialize()

        # Create all tables for testing
        Base.metadata.create_all(db_connection.engine)

        self.results = []
        self.errors = []

        yield

        # Cleanup after test
        if os.getenv("CI"):
            Base.metadata.drop_all(db_connection.engine)
        db_connection.dispose()

    def test_concurrent_user_creation(self):
        """Test multiple threads creating users simultaneously."""
        num_threads = 10

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

        # Assert that we created users successfully
        assert len(self.errors) == 0, f"Errors encountered: {self.errors}"
        assert len(self.results) == num_threads

    def test_concurrent_updates(self):
        """Test multiple threads updating the same user."""
        num_threads = 20
        self.errors = []  # Reset errors for this test
        self.results = []

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

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(update_user, i) for i in range(num_threads)]

            for future in as_completed(futures):
                result = future.result()
                self.results.append(result)

        # Assert all updates completed successfully
        assert len(self.errors) == 0, f"Errors encountered: {self.errors}"
        assert len(self.results) == num_threads

    def test_concurrent_reads_writes(self):
        """Test mixed read and write operations."""
        num_threads = 30
        self.errors = []  # Reset errors for this test
        self.results = []

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

        # Assert all operations completed successfully
        assert len(self.errors) == 0, f"Errors encountered: {self.errors}"
        assert len(self.results) == num_threads

    def test_transaction_isolation(self):
        """Test transaction isolation levels."""
        test_email = "isolation_test@solreader.com"
        results = []

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

                    # Simulate processing
                    time.sleep(2)

                    # Update after delay
                    repo.update_user_field(test_email, "timezone", "LongTransaction")
                    session.commit()
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
                    repo.update_user_field(test_email, "styles_updated", True)
                    session.commit()
                    return "Quick transaction completed"
            except Exception as e:
                return f"Quick transaction error: {e}"

        # Run both transactions concurrently
        with ThreadPoolExecutor(max_workers=2) as executor:
            long_future = executor.submit(long_transaction)
            quick_future = executor.submit(quick_transaction)

            long_result = long_future.result()
            quick_result = quick_future.result()
            results = [long_result, quick_result]

        # Both transactions should complete without errors
        for result in results:
            assert "error" not in result.lower(), f"Transaction failed: {result}"
        assert len(results) == 2

    def test_data_integrity(self):
        """Verify data integrity after concurrent operations."""
        # First create some users to ensure we have data to check
        test_emails = ["integrity_test_1@solreader.com", "integrity_test_2@solreader.com"]

        with db_connection.get_session() as session:
            repo = UserRepository(session)

            # Create test users
            for email in test_emails:
                user = repo.get_user_by_email(email)
                if not user:
                    repo.create_user(email, f"IntegrityTestAVD_{email}")

            # Now check all users
            all_users = repo.get_all_users()

            # Check for any inconsistencies
            missing_settings = []
            for user in all_users:
                # Verify required relationships exist
                if not user.emulator_settings:
                    missing_settings.append(f"User {user.email} missing emulator_settings")
                if not user.device_identifiers:
                    missing_settings.append(f"User {user.email} missing device_identifiers")
                if not user.library_settings:
                    missing_settings.append(f"User {user.email} missing library_settings")
                if not user.reading_settings:
                    missing_settings.append(f"User {user.email} missing reading_settings")

            assert len(missing_settings) == 0, f"Missing settings: {missing_settings}"

            # Check that we have created users from our tests
            assert len(all_users) > 0, "No users found in database"

            # Verify our test users were created
            created_emails = [user.email for user in all_users]
            for test_email in test_emails:
                assert test_email in created_emails, f"Test user {test_email} not found"
