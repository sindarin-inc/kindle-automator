import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.user_data_manager import UserDataManager


class TestUserDataManager(unittest.TestCase):
    """Test case for UserDataManager class"""

    @patch("server.user_data_manager.subprocess.run")
    def setUp(self, mock_run):
        # Setup mock for subprocess.run
        mock_process = MagicMock()
        mock_process.stdout = "Success"
        mock_run.return_value = mock_process

        # Create test instance
        self.user_manager = UserDataManager("emulator-5554")

        # Create test user data directory
        self.test_user_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data"
        )
        os.makedirs(self.test_user_dir, exist_ok=True)

    def test_user_exists(self):
        """Test user_exists method"""
        # Mock _get_users_index to return test data
        self.user_manager._get_users_index = MagicMock(
            return_value={"users": {"test@example.com": {"last_saved": "2025-03-25T12:00:00"}}}
        )

        # Test existing user
        self.assertTrue(self.user_manager.user_exists("test@example.com"))

        # Test non-existing user
        self.assertFalse(self.user_manager.user_exists("nonexistent@example.com"))

    def test_list_users(self):
        """Test list_users method"""
        # Mock _get_users_index to return test data
        self.user_manager._get_users_index = MagicMock(
            return_value={"users": {"user1@example.com": {}, "user2@example.com": {}}}
        )

        # Test listing users
        users = self.user_manager.list_users()
        self.assertEqual(len(users), 2)
        self.assertIn("user1@example.com", users)
        self.assertIn("user2@example.com", users)

    @patch("server.user_data_manager.subprocess.run")
    def test_switch_user(self, mock_run):
        """Test switch_user method"""
        # Mock subprocess.run to simulate success
        mock_process = MagicMock()
        mock_process.stdout = "Success"
        mock_run.return_value = mock_process

        # Mock relevant methods
        self.user_manager.save_current_user_data = MagicMock(return_value=True)
        self.user_manager.load_user_data = MagicMock(return_value=True)
        self.user_manager.user_exists = MagicMock(return_value=True)

        # Test switching user
        self.user_manager.current_user = "currentuser@example.com"
        result = self.user_manager.switch_user("newuser@example.com")

        # Verify methods were called
        self.user_manager.save_current_user_data.assert_called_once()
        self.user_manager.load_user_data.assert_called_once_with("newuser@example.com")
        self.assertTrue(result)

    @patch("os.path.exists")
    @patch("server.user_data_manager.subprocess.run")
    def test_save_current_user_data(self, mock_run, mock_path_exists):
        """Test save_current_user_data method"""
        # Mock subprocess.run to simulate success
        mock_process = MagicMock()
        mock_process.stdout = "Success"
        mock_run.return_value = mock_process

        # Set up the test
        self.user_manager.current_user = "test@example.com"
        self.user_manager._get_users_index = MagicMock(return_value={"users": {}})
        self.user_manager._save_users_index = MagicMock()
        mock_path_exists.return_value = True

        # Mock _run_adb_command to simulate success
        self.user_manager._run_adb_command = MagicMock(return_value=(True, "Success"))

        # Test saving user data
        result = self.user_manager.save_current_user_data()

        # Verify results
        self.assertTrue(result)
        self.assertEqual(self.user_manager._run_adb_command.call_count, 4)
        self.user_manager._save_users_index.assert_called_once()


if __name__ == "__main__":
    unittest.main()
