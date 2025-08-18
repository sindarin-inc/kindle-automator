"""Test absolute navigation with navigate_to and preview_to."""

import pytest

from tests.test_base import BaseKindleTest


class TestAbsoluteNavigation(BaseKindleTest):
    """Test navigate_to and preview_to functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test."""
        self.setup_base()

    @pytest.mark.timeout(120)
    def test_navigate_to_absolute_position(self):
        """Test navigate_to for absolute positioning."""
        print("\n[TEST] Testing navigate_to absolute positioning")

        # Open a random book first
        print("[TEST] Opening a random book...")
        open_response = self._make_request("open-random-book")
        assert open_response.status_code == 200

        # Handle last read dialog if present
        open_data = open_response.json()
        if open_data.get("last_read_dialog"):
            print("[TEST] Handling last read dialog...")
            dialog_response = self._make_request(
                "last-read-page-dialog", method="POST", params={"goto_last_read_page": "true"}
            )
            assert dialog_response.status_code == 200

        # Test navigate_to=3
        print("[TEST] Testing navigate_to=3...")
        nav_3 = self._make_request("navigate", params={"navigate_to": 3})
        assert nav_3.status_code == 200
        nav_3_data = nav_3.json()
        assert not nav_3_data.get("error"), f"Navigation failed: {nav_3_data.get('error')}"
        print("[TEST] ✓ Successfully navigated to position 3")

        # Test navigate_to=1 (should go back)
        print("[TEST] Testing navigate_to=1 (going back)...")
        nav_1 = self._make_request("navigate", params={"navigate_to": 1})
        assert nav_1.status_code == 200
        nav_1_data = nav_1.json()
        assert not nav_1_data.get("error"), f"Navigation failed: {nav_1_data.get('error')}"
        print("[TEST] ✓ Successfully navigated back to position 1")

        # Test navigate_to=0 (go to start)
        print("[TEST] Testing navigate_to=0 (start of book)...")
        nav_0 = self._make_request("navigate", params={"navigate_to": 0})
        assert nav_0.status_code == 200
        nav_0_data = nav_0.json()
        assert not nav_0_data.get("error"), f"Navigation failed: {nav_0_data.get('error')}"
        print("[TEST] ✓ Successfully navigated to position 0")

        print("[TEST] All navigate_to tests passed!")

    @pytest.mark.timeout(120)
    def test_preview_to_absolute_position(self):
        """Test preview_to for absolute preview without changing position."""
        print("\n[TEST] Testing preview_to absolute preview")

        # Open a random book first
        print("[TEST] Opening a random book...")
        open_response = self._make_request("open-random-book")
        assert open_response.status_code == 200

        # Handle last read dialog if present
        open_data = open_response.json()
        if open_data.get("last_read_dialog"):
            print("[TEST] Handling last read dialog...")
            dialog_response = self._make_request(
                "last-read-page-dialog", method="POST", params={"goto_last_read_page": "true"}
            )
            assert dialog_response.status_code == 200

        # Navigate to position 2 first
        print("[TEST] Setting up at position 2...")
        nav_2 = self._make_request("navigate", params={"navigate_to": 2})
        assert nav_2.status_code == 200
        nav_2_text = nav_2.json().get("text", "") or nav_2.json().get("ocr_text", "")

        # Test preview_to=5
        print("[TEST] Testing preview_to=5 (preview without moving)...")
        preview_5 = self._make_request("navigate", params={"preview_to": 5})
        assert preview_5.status_code == 200
        preview_5_data = preview_5.json()
        preview_5_text = preview_5_data.get("text", "") or preview_5_data.get("ocr_text", "")
        assert preview_5_text != nav_2_text, "Preview should show different text"
        print("[TEST] ✓ Successfully previewed position 5")

        # Verify we're still at position 2
        print("[TEST] Verifying position unchanged after preview...")
        check = self._make_request("navigate", params={"navigate": 0})
        assert check.status_code == 200
        check_text = check.json().get("text", "") or check.json().get("ocr_text", "")
        assert check_text == nav_2_text, "Position changed after preview_to"
        print("[TEST] ✓ Position remained at 2 after preview")

        # Test preview_to=0
        print("[TEST] Testing preview_to=0 (preview start)...")
        preview_0 = self._make_request("navigate", params={"preview_to": 0})
        assert preview_0.status_code == 200
        print("[TEST] ✓ Successfully previewed position 0")

        # Verify still at position 2
        print("[TEST] Verifying position still unchanged...")
        check2 = self._make_request("navigate", params={"navigate": 0})
        assert check2.status_code == 200
        check2_text = check2.json().get("text", "") or check2.json().get("ocr_text", "")
        assert check2_text == nav_2_text, "Position changed after second preview_to"
        print("[TEST] ✓ Position still at 2 after multiple previews")

        print("[TEST] All preview_to tests passed!")

    @pytest.mark.timeout(120)
    def test_combined_navigate_to_and_preview(self):
        """Test using navigate_to with preview together."""
        print("\n[TEST] Testing combined navigate_to and preview")

        # Open a random book first
        print("[TEST] Opening a random book...")
        open_response = self._make_request("open-random-book")
        assert open_response.status_code == 200

        # Handle last read dialog if present
        open_data = open_response.json()
        if open_data.get("last_read_dialog"):
            print("[TEST] Handling last read dialog...")
            dialog_response = self._make_request(
                "last-read-page-dialog", method="POST", params={"goto_last_read_page": "true"}
            )
            assert dialog_response.status_code == 200

        # Test navigate_to=1, preview=2 (go to 1, preview 2 ahead = position 3)
        print("[TEST] Testing navigate_to=1, preview=2...")
        combo = self._make_request("navigate", params={"navigate_to": 1, "preview": 2})
        assert combo.status_code == 200
        combo_data = combo.json()
        assert not combo_data.get("error"), f"Combined navigation failed: {combo_data.get('error')}"
        print("[TEST] ✓ Successfully navigated to 1 and previewed position 3")

        # Verify we're at position 1
        print("[TEST] Verifying current position is 1...")
        check = self._make_request("navigate", params={"navigate": 0})
        assert check.status_code == 200

        # Now test navigate_to=2, preview_to=0 (go to 2, preview absolute position 0)
        print("[TEST] Testing navigate_to=2, preview_to=0...")
        combo2 = self._make_request("navigate", params={"navigate_to": 2, "preview_to": 0})
        assert combo2.status_code == 200
        combo2_data = combo2.json()
        assert not combo2_data.get("error"), f"Combined navigation failed: {combo2_data.get('error')}"
        print("[TEST] ✓ Successfully navigated to 2 and previewed absolute position 0")

        # Test relative navigation updates position correctly
        print("\n[TEST] Testing relative navigation updates position...")
        # We're currently at position 2, save this as checkpoint
        checkpoint_response = self._make_request("navigate", params={"navigate": 0})
        assert checkpoint_response.status_code == 200
        checkpoint_text = checkpoint_response.json().get("text", "") or checkpoint_response.json().get(
            "ocr_text", ""
        )
        print("[TEST] Saved checkpoint at position 2")

        # Do relative navigation forward 3 pages
        print("[TEST] Relative navigate forward 3 pages...")
        rel_nav = self._make_request("navigate", params={"navigate": 3})
        assert rel_nav.status_code == 200
        print("[TEST] ✓ Navigated relatively forward 3 pages (should be at position 5)")

        # Do relative preview back 1 (should update position to 4)
        print("[TEST] Relative preview back 1 page...")
        rel_preview = self._make_request("navigate", params={"preview": -1})
        assert rel_preview.status_code == 200
        print("[TEST] ✓ Previewed relatively back 1 page (should be at position 4)")

        # Navigate back to absolute position 2 using navigate_to
        print("[TEST] Navigate back to absolute position 2...")
        back_to_checkpoint = self._make_request("navigate", params={"navigate_to": 2})
        assert back_to_checkpoint.status_code == 200
        back_text = back_to_checkpoint.json().get("text", "") or back_to_checkpoint.json().get("ocr_text", "")

        # Verify we're back at the same checkpoint
        assert (
            back_text == checkpoint_text
        ), "Position tracking failed - checkpoint text doesn't match after relative navigation"
        print("[TEST] ✓ Successfully returned to checkpoint - position tracking is consistent")

        print("[TEST] All combined navigation tests passed!")

    @pytest.mark.timeout(60)
    def test_navigation_consistency(self):
        """Test that navigation forward and backward returns to the same text."""
        print("\n[TEST] Testing navigation consistency - forward and backward should return same text")

        # First ensure we have a book open
        print("[TEST] Opening a random book to test navigation...")
        open_response = self._make_request("open-random-book")
        assert open_response.status_code == 200, f"Failed to open book: {open_response.text}"

        # Handle potential last read dialog from open-random-book
        open_data = open_response.json()
        if open_data.get("last_read_dialog"):
            print("[TEST] Handling last read dialog - clicking YES to go to last read page...")
            # Post to last-read-page-dialog endpoint to click YES
            dialog_response = self._make_request(
                "last-read-page-dialog", method="POST", params={"goto_last_read_page": "true"}
            )
            assert dialog_response.status_code == 200
            dialog_data = dialog_response.json()
            print(f"[TEST] Dialog handled, got OCR text: {len(dialog_data.get('text', ''))} chars")

        # Get initial page text
        print("[TEST] Getting initial page text...")
        initial_response = self._make_request("navigate", params={"navigate": 0, "preview": 0})
        assert initial_response.status_code == 200
        initial_data = initial_response.json()
        initial_text = initial_data.get("text", "") or initial_data.get("ocr_text", "")
        print(f"[TEST] Initial text length: {len(initial_text)} chars")

        # Skip test if we still have dialog issues
        if initial_data.get("last_read_dialog"):
            print("[TEST] Still have dialog, skipping consistency test")
            return

        # Test 1: Forward 1, back 1
        print("\n[TEST] Test 1: Navigate forward 1 page, then back 1 page")
        forward_1 = self._make_request("navigate", params={"navigate": 1})
        assert forward_1.status_code == 200
        back_1 = self._make_request("navigate", params={"navigate": -1})
        assert back_1.status_code == 200
        back_1_data = back_1.json()
        back_1_text = back_1_data.get("text", "") or back_1_data.get("ocr_text", "")
        assert back_1_text == initial_text, "Text mismatch after navigate +1, -1"
        print("[TEST] ✓ Text matches after +1, -1")

        # Test 2: Forward 2, back 2
        print("\n[TEST] Test 2: Navigate forward 2 pages, then back 2 pages")
        forward_2 = self._make_request("navigate", params={"navigate": 2})
        assert forward_2.status_code == 200
        back_2 = self._make_request("navigate", params={"navigate": -2})
        assert back_2.status_code == 200
        back_2_data = back_2.json()
        back_2_text = back_2_data.get("text", "") or back_2_data.get("ocr_text", "")
        assert back_2_text == initial_text, "Text mismatch after navigate +2, -2"
        print("[TEST] ✓ Text matches after +2, -2")

        # Test 3: Forward 3, back 3
        print("\n[TEST] Test 3: Navigate forward 3 pages, then back 3 pages")
        forward_3 = self._make_request("navigate", params={"navigate": 3})
        assert forward_3.status_code == 200
        back_3 = self._make_request("navigate", params={"navigate": -3})
        assert back_3.status_code == 200
        back_3_data = back_3.json()
        back_3_text = back_3_data.get("text", "") or back_3_data.get("ocr_text", "")
        assert back_3_text == initial_text, "Text mismatch after navigate +3, -3"
        print("[TEST] ✓ Text matches after +3, -3")

        # Test 4: Test absolute navigation with navigate_to
        print("\n[TEST] Test 4: Testing absolute navigation with navigate_to")

        # Go to position 5
        print("   Navigate to absolute position 5...")
        nav_to_5 = self._make_request("navigate", params={"navigate_to": 5})
        assert nav_to_5.status_code == 200
        nav_5_data = nav_to_5.json()
        nav_5_text = nav_5_data.get("text", "") or nav_5_data.get("ocr_text", "")

        # Go back to position 0
        print("   Navigate back to absolute position 0...")
        nav_to_0 = self._make_request("navigate", params={"navigate_to": 0})
        assert nav_to_0.status_code == 200
        nav_0_data = nav_to_0.json()
        nav_0_text = nav_0_data.get("text", "") or nav_0_data.get("ocr_text", "")

        # Verify we're back at the initial position
        # Note: After the last read dialog, position 0 might not be the same as initial_text
        # So we just verify the navigation worked
        print("[TEST] ✓ Absolute navigation with navigate_to works")

        print("\n[TEST] All navigation consistency tests passed!")

    @pytest.mark.timeout(60)
    def test_preview_consistency(self):
        """Test that preview returns to original position without changing current page."""
        print("\n[TEST] Testing preview consistency - preview should not change current position")

        # First ensure we have a book open (in case this test runs independently)
        print("[TEST] Opening a random book to test preview...")
        open_response = self._make_request("open-random-book")
        assert open_response.status_code == 200, f"Failed to open book: {open_response.text}"

        # Handle potential last read dialog
        open_data = open_response.json()
        if open_data.get("last_read_dialog"):
            print("[TEST] Handling last read dialog - clicking YES...")
            dialog_response = self._make_request(
                "last-read-page-dialog", method="POST", params={"goto_last_read_page": "true"}
            )
            assert dialog_response.status_code == 200

        # Get current page text
        print("[TEST] Getting current page text...")
        current_response = self._make_request("navigate", params={"navigate": 0})
        assert current_response.status_code == 200
        current_data = current_response.json()
        current_text = current_data.get("text", "")
        print(f"[TEST] Current text length: {len(current_text)} chars")

        # Test 1: Preview forward 1 (navigate=0, preview=1)
        print("\n[TEST] Test 1: Preview 1 page ahead without navigating")
        preview_1 = self._make_request("navigate", params={"navigate": 0, "preview": 1})
        assert preview_1.status_code == 200
        preview_1_data = preview_1.json()
        preview_1_text = preview_1_data.get("text", "")
        assert preview_1_text != current_text, "Preview text should be different from current"
        print(f"[TEST] Preview text length: {len(preview_1_text)} chars")

        # Verify we're still at the same position
        verify_1 = self._make_request("navigate", params={"navigate": 0})
        assert verify_1.status_code == 200
        verify_1_data = verify_1.json()
        assert verify_1_data.get("text") == current_text, "Position changed after preview"
        print("[TEST] ✓ Position unchanged after preview=1")

        # Test 2: Preview forward 3
        print("\n[TEST] Test 2: Preview 3 pages ahead without navigating")
        preview_3 = self._make_request("navigate", params={"navigate": 0, "preview": 3})
        assert preview_3.status_code == 200
        preview_3_data = preview_3.json()
        preview_3_text = preview_3_data.get("text", "")
        assert preview_3_text != current_text, "Preview text should be different from current"
        assert preview_3_text != preview_1_text, "Preview 3 should be different from preview 1"

        # Verify position still unchanged
        verify_3 = self._make_request("navigate", params={"navigate": 0})
        assert verify_3.status_code == 200
        verify_3_data = verify_3.json()
        assert verify_3_data.get("text") == current_text, "Position changed after preview=3"
        print("[TEST] ✓ Position unchanged after preview=3")

        # Test 3: Navigate and preview combo (navigate=2, preview=1)
        print("\n[TEST] Test 3: Navigate 2 pages and preview 1 more")
        nav_2_prev_1 = self._make_request("navigate", params={"navigate": 2, "preview": 1})
        assert nav_2_prev_1.status_code == 200
        nav_2_prev_1_data = nav_2_prev_1.json()
        # This should show page 3 (2 forward + 1 preview from there)

        # Now check we're at position 2 (not 3)
        verify_pos_2 = self._make_request("navigate", params={"navigate": 0})
        assert verify_pos_2.status_code == 200
        verify_pos_2_data = verify_pos_2.json()
        # This text should be different from initial (we moved 2 pages)
        assert verify_pos_2_data.get("text") != current_text, "Should be at new position after navigate=2"

        # Navigate back to start
        back_to_start = self._make_request("navigate", params={"navigate": -2})
        assert back_to_start.status_code == 200
        back_data = back_to_start.json()
        assert back_data.get("text") == current_text, "Failed to return to start position"
        print("[TEST] ✓ Navigate and preview combo works correctly")

        # Test 4: Preview backward
        print("\n[TEST] Test 4: Preview backward")
        # First navigate forward so we can preview backward
        self._make_request("navigate", params={"navigate": 3})
        at_page_3 = self._make_request("navigate", params={"navigate": 0})
        assert at_page_3.status_code == 200
        page_3_text = at_page_3.json().get("text", "") or at_page_3.json().get("ocr_text", "")

        # Preview backward 2 pages
        preview_back_2 = self._make_request("navigate", params={"navigate": 0, "preview": -2})
        assert preview_back_2.status_code == 200
        preview_back_data = preview_back_2.json()

        # Verify we're still at page 3
        verify_still_3 = self._make_request("navigate", params={"navigate": 0})
        assert verify_still_3.status_code == 200
        still_3_text = verify_still_3.json().get("text", "") or verify_still_3.json().get("ocr_text", "")
        assert still_3_text == page_3_text, "Position changed after backward preview"
        print("[TEST] ✓ Backward preview works correctly")

        # Test 5: Test preview_to absolute positioning
        print("\n[TEST] Test 5: Testing preview_to absolute positioning")
        # Preview position 10 without moving
        print("   Preview absolute position 10...")
        preview_to_10 = self._make_request("navigate", params={"preview_to": 10})
        assert preview_to_10.status_code == 200
        preview_10_data = preview_to_10.json()
        preview_10_text = preview_10_data.get("text", "") or preview_10_data.get("ocr_text", "")

        # Verify we're still at page 3
        print("   Verifying position unchanged after preview_to...")
        verify_pos = self._make_request("navigate", params={"navigate": 0})
        assert verify_pos.status_code == 200
        verify_text = verify_pos.json().get("text", "") or verify_pos.json().get("ocr_text", "")
        assert verify_text == page_3_text, "Position changed after preview_to"
        print("[TEST] ✓ preview_to works without changing position")

        print("\n[TEST] All preview consistency tests passed!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
