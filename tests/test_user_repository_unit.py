"""Unit tests for UserRepository."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.connection import db_connection
from database.models import Base
from database.repositories.user_repository import UserRepository


@pytest.fixture(scope="function")
def test_db():
    """Create a test database for each test function."""
    # Use an in-memory SQLite database for tests
    engine = create_engine("sqlite:///:memory:")

    # Create all tables
    Base.metadata.create_all(engine)

    # Create session factory
    TestSession = sessionmaker(bind=engine)

    yield TestSession

    # Cleanup
    engine.dispose()


@pytest.fixture
def repo(test_db):
    """Create a UserRepository instance with test database."""
    session = test_db()
    yield UserRepository(session)
    session.close()


class TestUserRepository:
    """Test cases for UserRepository."""

    def test_create_user(self, repo):
        """Test creating a new user."""
        email = "test@example.com"
        avd_name = "TestAVD"

        user = repo.create_user(email, avd_name)

        assert user.email == email
        assert user.avd_name == avd_name
        assert user.emulator_settings is not None
        assert user.device_identifiers is not None
        assert user.library_settings is not None
        assert user.reading_settings is not None

    def test_get_user_by_email(self, repo):
        """Test retrieving a user by email."""
        email = "test@example.com"
        repo.create_user(email, "TestAVD")

        user = repo.get_user_by_email(email)

        assert user is not None
        assert user.email == email

    def test_get_nonexistent_user(self, repo):
        """Test retrieving a non-existent user."""
        user = repo.get_user_by_email("nonexistent@example.com")
        assert user is None

    def test_get_or_create_user_existing(self, repo):
        """Test get_or_create with existing user."""
        email = "test@example.com"
        repo.create_user(email, "TestAVD")

        user, created = repo.get_or_create_user(email, "NewAVD")

        assert user.email == email
        assert user.avd_name == "TestAVD"  # Should not update existing
        assert created is False

    def test_get_or_create_user_new(self, repo):
        """Test get_or_create with new user."""
        email = "new@example.com"

        user, created = repo.get_or_create_user(email, "NewAVD")

        assert user.email == email
        assert user.avd_name == "NewAVD"
        assert created is True

    def test_update_user_field(self, repo):
        """Test updating a user field."""
        email = "test@example.com"
        repo.create_user(email, "TestAVD")

        # Update timezone
        success = repo.update_user_field(email, "timezone", "America/New_York")
        assert success is True

        # Verify update
        user = repo.get_user_by_email(email)
        assert user.timezone == "America/New_York"

    def test_update_nested_field(self, repo):
        """Test updating a nested field."""
        email = "test@example.com"
        repo.create_user(email, "TestAVD")

        # Update emulator setting
        success = repo.update_user_field(email, "emulator_settings.hw_overlays_disabled", True)
        assert success is True

        # Verify update
        user = repo.get_user_by_email(email)
        assert user.emulator_settings.hw_overlays_disabled is True

    def test_update_preference(self, repo):
        """Test updating user preferences."""
        email = "test@example.com"
        repo.create_user(email, "TestAVD")

        # Add preference
        success = repo.update_user_field(email, "preferences.theme", "dark")
        assert success is True

        # Verify preference
        user = repo.get_user_by_email(email)
        theme_pref = next((p for p in user.preferences if p.preference_key == "theme"), None)
        assert theme_pref is not None
        assert theme_pref.preference_value == "dark"

    def test_update_last_used(self, repo):
        """Test updating last_used timestamp."""
        email = "test@example.com"
        repo.create_user(email, "TestAVD")

        # Update last_used
        success = repo.update_last_used(email, "emulator-123")
        assert success is True

        # Verify update
        user = repo.get_user_by_email(email)
        assert user.last_used is not None
        assert isinstance(user.last_used, datetime)

    def test_update_auth_state(self, repo):
        """Test updating authentication state."""
        email = "test@example.com"
        repo.create_user(email, "TestAVD")

        # Update auth state
        success = repo.update_auth_state(email, True)
        assert success is True

        # Verify update
        user = repo.get_user_by_email(email)
        assert user.auth_date is not None

    def test_get_all_users(self, repo):
        """Test retrieving all users."""
        # Create multiple users
        emails = ["user1@example.com", "user2@example.com", "user3@example.com"]
        for email in emails:
            repo.create_user(email, f"AVD_{email}")

        # Get all users
        users = repo.get_all_users()
        assert len(users) == 3
        assert all(user.email in emails for user in users)

    def test_get_recently_used_users(self, repo):
        """Test retrieving recently used users."""
        # Create users with different last_used times
        for i in range(5):
            email = f"user{i}@example.com"
            repo.create_user(email, f"AVD_{i}")
            if i < 3:  # Only update last_used for first 3
                repo.update_last_used(email)

        # Get recently used
        recent_users = repo.get_recently_used_users(limit=2)
        assert len(recent_users) == 2
        # Should be ordered by last_used DESC
        assert all(user.last_used is not None for user in recent_users)

    def test_user_to_dict(self, repo):
        """Test converting user to dictionary."""
        email = "test@example.com"
        user = repo.create_user(email, "TestAVD")

        # Update some fields
        repo.update_user_field(email, "timezone", "UTC")
        repo.update_user_field(email, "emulator_settings.animations_disabled", True)
        repo.update_user_field(email, "library_settings.view_type", "grid")
        repo.update_user_field(email, "preferences.lang", "en")

        # Convert to dict
        user = repo.get_user_by_email(email)
        user_dict = repo.user_to_dict(user)

        # Verify structure
        assert user_dict["email"] == email
        assert user_dict["avd_name"] == "TestAVD"
        assert user_dict["timezone"] == "UTC"
        assert user_dict["emulator_settings"]["animations_disabled"] is True
        assert user_dict["library_settings"]["view_type"] == "grid"
        assert user_dict["preferences"]["lang"] == "en"

    def test_concurrent_updates(self, repo, test_db):
        """Test concurrent updates to the same user."""
        email = "test@example.com"
        repo.create_user(email, "TestAVD")

        # Simulate concurrent sessions
        session1 = test_db()
        session2 = test_db()
        repo1 = UserRepository(session1)
        repo2 = UserRepository(session2)

        # Both try to update different fields
        success1 = repo1.update_user_field(email, "timezone", "UTC")
        success2 = repo2.update_user_field(email, "styles_updated", True)

        assert success1 is True
        assert success2 is True

        # Verify both updates succeeded
        user = repo.get_user_by_email(email)
        assert user.timezone == "UTC"
        assert user.styles_updated is True

        session1.close()
        session2.close()

    def test_datetime_json_serialization(self, repo, test_db):
        """Test that datetime fields from database can be JSON serialized."""
        email = "test@example.com"
        user = repo.create_user(email, "TestAVD")
        
        # Update library settings with a datetime
        current_time = datetime.now(timezone.utc)
        repo.update_user_field(email, "library_settings.last_series_group_check", current_time)
        
        # Reload the user with library settings
        user = repo.get_user_by_email(email)
        assert user.library_settings is not None
        assert user.library_settings.last_series_group_check is not None
        
        # Test 1: Direct serialization with custom encoder should work
        from server.server import DateTimeJSONEncoder
        
        # Create a dict that includes the datetime object
        test_dict = {
            "email": email,
            "library_settings": {
                "last_series_group_check": user.library_settings.last_series_group_check,
                "view_type": user.library_settings.view_type,
                "group_by_series": user.library_settings.group_by_series
            }
        }
        
        # This should not raise an exception
        json_str = json.dumps(test_dict, cls=DateTimeJSONEncoder)
        assert json_str is not None
        
        # Verify the datetime was converted to ISO format string
        parsed = json.loads(json_str)
        assert isinstance(parsed["library_settings"]["last_series_group_check"], str)
        assert "T" in parsed["library_settings"]["last_series_group_check"]  # ISO format includes 'T'
        
        # Test 2: Without custom encoder, it should fail
        with pytest.raises(TypeError) as exc_info:
            json.dumps(test_dict)
        assert "not JSON serializable" in str(exc_info.value)
        
        # Test 3: Test with other datetime fields
        repo.update_user_field(email, "last_used", datetime.now(timezone.utc))
        repo.update_user_field(email, "auth_date", datetime.now(timezone.utc))
        repo.update_user_field(email, "snapshot_dirty_since", datetime.now(timezone.utc))
        
        # Reload to get the updated values
        user = repo.get_user_by_email(email)
        
        # Create a dict with multiple datetime fields
        test_dict_multiple = {
            "email": email,
            "last_used": user.last_used,
            "auth_date": user.auth_date,
            "snapshot_dirty_since": user.snapshot_dirty_since,
            "library_settings": {
                "last_series_group_check": user.library_settings.last_series_group_check
            }
        }
        
        # Should work with custom encoder
        json_str = json.dumps(test_dict_multiple, cls=DateTimeJSONEncoder)
        parsed = json.loads(json_str)
        
        # All datetime fields should be strings
        assert isinstance(parsed["last_used"], str)
        assert isinstance(parsed["auth_date"], str)
        assert isinstance(parsed["snapshot_dirty_since"], str)
        assert isinstance(parsed["library_settings"]["last_series_group_check"], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
