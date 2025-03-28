import os
import sys
import unittest

# Adjust path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from views.core.avd_profile_manager import AVDProfileManager


class TestAVDProfileManager(unittest.TestCase):
    """Tests for the AVD Profile Manager"""
    
    def setUp(self):
        """Set up test environment"""
        # Use a test directory for profile management
        self.test_dir = "/tmp/test_avd_profiles"
        os.makedirs(self.test_dir, exist_ok=True)
        
        # Create profile manager with test directory
        self.profile_manager = AVDProfileManager(base_dir=self.test_dir)
        
        # Test email addresses
        self.test_email1 = "test1@example.com"
        self.test_email2 = "test2@example.com"
        
    def tearDown(self):
        """Clean up after tests"""
        # In a real environment, we'd delete the test directory
        # Here we'll just leave it for inspection
        pass
        
    def test_profile_creation(self):
        """Test profile creation functionality"""
        # Since we're using a mock directory, we'll mock the AVD creation
        # by patching the create_new_avd method
        
        original_method = self.profile_manager.create_new_avd
        
        def mock_create_new_avd(email):
            """Mock implementation that doesn't actually create an AVD"""
            email_prefix = email.split('@')[0].replace('.', '_')
            avd_name = f"KindleAVD_{email_prefix}"
            
            # Create mock AVD directories
            avd_path = os.path.join(self.test_dir, "avd", f"{avd_name}.avd")
            os.makedirs(avd_path, exist_ok=True)
            
            # Create mock config.ini file
            with open(os.path.join(avd_path, "config.ini"), 'w') as f:
                f.write("# Mock AVD config\n")
                f.write("hw.ramSize=4096\n")
            
            return True, avd_name
            
        # Replace with mock method
        self.profile_manager.create_new_avd = mock_create_new_avd
        
        try:
            # Test creating a profile
            success, message = self.profile_manager.create_profile(self.test_email1)
            self.assertTrue(success, f"Profile creation failed: {message}")
            
            # Verify profile was added to index
            self.assertIn(self.test_email1, self.profile_manager.profiles_index)
            avd_name = self.profile_manager.profiles_index[self.test_email1]
            self.assertTrue(avd_name.startswith("KindleAVD_"))
            
            # Test creating a second profile
            success, message = self.profile_manager.create_profile(self.test_email2)
            self.assertTrue(success, f"Second profile creation failed: {message}")
            
            # Verify both profiles exist
            profiles = self.profile_manager.list_profiles()
            self.assertEqual(len(profiles), 2, "Should have 2 profiles")
            
            # Emails should be in profiles list
            emails = [p["email"] for p in profiles]
            self.assertIn(self.test_email1, emails)
            self.assertIn(self.test_email2, emails)
            
        finally:
            # Restore original method
            self.profile_manager.create_new_avd = original_method
            
    def test_profile_deletion(self):
        """Test profile deletion functionality"""
        # First create a profile to delete
        original_method = self.profile_manager.create_new_avd
        
        def mock_create_new_avd(email):
            """Mock implementation that doesn't actually create an AVD"""
            email_prefix = email.split('@')[0].replace('.', '_')
            avd_name = f"KindleAVD_{email_prefix}"
            
            # Create mock AVD directories
            avd_path = os.path.join(self.test_dir, "avd", f"{avd_name}.avd")
            os.makedirs(avd_path, exist_ok=True)
            
            # Create mock config.ini file
            with open(os.path.join(avd_path, "config.ini"), 'w') as f:
                f.write("# Mock AVD config\n")
                f.write("hw.ramSize=4096\n")
                
            # Create mock ini file
            with open(os.path.join(self.test_dir, "avd", f"{avd_name}.ini"), 'w') as f:
                f.write("# Mock AVD ini\n")
            
            return True, avd_name
            
        # Replace with mock method
        self.profile_manager.create_new_avd = mock_create_new_avd
        
        # Also mock the is_emulator_running and stop_emulator methods
        self.profile_manager.is_emulator_running = lambda: False
        self.profile_manager.stop_emulator = lambda: True
        
        try:
            # Create a profile
            self.profile_manager.create_profile(self.test_email1)
            
            # Test deleting a profile
            success, message = self.profile_manager.delete_profile(self.test_email1)
            self.assertTrue(success, f"Profile deletion failed: {message}")
            
            # Verify profile was removed from index
            self.assertNotIn(self.test_email1, self.profile_manager.profiles_index)
            
            # Test deleting a non-existent profile
            success, message = self.profile_manager.delete_profile("nonexistent@example.com")
            self.assertFalse(success, "Should fail when deleting non-existent profile")
            
        finally:
            # Restore original method
            self.profile_manager.create_new_avd = original_method
            
    def test_current_profile(self):
        """Test current profile tracking"""
        # Mock methods that interact with the emulator
        original_create = self.profile_manager.create_new_avd
        original_is_running = self.profile_manager.is_emulator_running
        original_start = self.profile_manager.start_emulator
        original_stop = self.profile_manager.stop_emulator
        
        def mock_create_new_avd(email):
            email_prefix = email.split('@')[0].replace('.', '_')
            avd_name = f"KindleAVD_{email_prefix}"
            return True, avd_name
            
        self.profile_manager.create_new_avd = mock_create_new_avd
        self.profile_manager.is_emulator_running = lambda: False
        self.profile_manager.start_emulator = lambda avd_name: True
        self.profile_manager.stop_emulator = lambda: True
        
        try:
            # Test switching to a new profile
            success, message = self.profile_manager.switch_profile(self.test_email1)
            self.assertTrue(success, f"Profile switch failed: {message}")
            
            # Verify current profile is set
            current = self.profile_manager.get_current_profile()
            self.assertIsNotNone(current)
            self.assertEqual(current["email"], self.test_email1)
            
            # Test switching to another profile
            success, message = self.profile_manager.switch_profile(self.test_email2)
            self.assertTrue(success, f"Second profile switch failed: {message}")
            
            # Verify current profile is updated
            current = self.profile_manager.get_current_profile()
            self.assertEqual(current["email"], self.test_email2)
            
        finally:
            # Restore original methods
            self.profile_manager.create_new_avd = original_create
            self.profile_manager.is_emulator_running = original_is_running
            self.profile_manager.start_emulator = original_start
            self.profile_manager.stop_emulator = original_stop


if __name__ == "__main__":
    unittest.main()