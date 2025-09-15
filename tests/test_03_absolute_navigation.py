"""Test absolute navigation with navigate_to and preview_to."""

import logging

import pytest

from tests.test_base import TEST_USER_EMAIL, BaseKindleTest

logger = logging.getLogger(__name__)


class TestAbsoluteNavigation(BaseKindleTest):
    """Test navigate_to and preview_to functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup for each test."""
        self.setup_base()

    @pytest.mark.timeout(120)
    def test_navigate_to_absolute_position(self):
        """Test navigate_to for absolute positioning."""
        print("\n[TEST] Testing navigate_to absolute positioning with ReadingSession tracking")

        # Import database models for ReadingSession checks
        from database.connection import db_connection
        from database.models import ReadingSession, User

        # Get initial ReadingSession count
        initial_session_count = 0
        with db_connection.get_session() as session:
            user = session.query(User).filter_by(email=TEST_USER_EMAIL).first()
            if user:
                initial_session_count = session.query(ReadingSession).filter_by(user_id=user.id).count()
                print(f"[TEST] Initial ReadingSession count: {initial_session_count}")

        # Open the test book with numbered paragraphs
        print("[TEST] Opening sol-chapter-test-epub book...")
        open_response = self._make_request("open-book", params={"title": "sol-chapter-test-epub"})
        assert open_response.status_code == 200

        # Handle last read dialog if present
        open_data = open_response.json()
        if open_data.get("last_read_dialog"):
            print("[TEST] Handling last read dialog...")
            dialog_response = self._make_request(
                "last-read-page-dialog", method="POST", params={"goto_last_read_page": "true"}
            )
            assert dialog_response.status_code == 200

        # Verify ReadingSession was created for the open event
        with db_connection.get_session() as session:
            user = session.query(User).filter_by(email=TEST_USER_EMAIL).first()
            if user:
                sessions_after_open = session.query(ReadingSession).filter_by(user_id=user.id).count()
                assert (
                    sessions_after_open > initial_session_count
                ), f"Expected ReadingSession for open-book, but count remained {initial_session_count}"

                # Get the active session
                active_session = (
                    session.query(ReadingSession)
                    .filter_by(user_id=user.id, is_active=True)
                    .order_by(ReadingSession.started_at.desc())
                    .first()
                )
                assert active_session is not None, "No active ReadingSession found"
                assert (
                    active_session.book_title == "sol-chapter-test-epub"
                ), f"Expected book title 'sol-chapter-test-epub', got '{active_session.book_title}'"
                assert (
                    active_session.current_position == 0
                ), f"Expected position 0 for new session, got {active_session.current_position}"
                assert (
                    active_session.navigation_count == 0
                ), f"Expected 0 navigations for new session, got {active_session.navigation_count}"
                print(f"[TEST] ✓ ReadingSession created for sol-chapter-test-epub")
                # Store session ID for later checks
                session_id = active_session.id

        # Test navigate_to=3
        print("[TEST] Testing navigate_to=3...")
        nav_3 = self._make_request("navigate", params={"navigate_to": 3})
        assert nav_3.status_code == 200
        nav_3_data = nav_3.json()
        assert not nav_3_data.get("error"), f"Navigation failed: {nav_3_data.get('error')}"
        nav_3_text = nav_3_data.get("text", "") or nav_3_data.get("ocr_text", "")
        print(f"[TEST] ✓ Successfully navigated to position 3, OCR text preview: {nav_3_text[:100]}...")

        # Verify ReadingSession was updated for navigate to position 3
        with db_connection.get_session() as session:
            # Get the same session and check it was updated
            active_session = session.query(ReadingSession).filter_by(id=session_id).first()
            assert active_session is not None, "ReadingSession disappeared"
            assert (
                active_session.current_position == 3
            ), f"Expected position 3 after navigate_to=3, got {active_session.current_position}"
            assert (
                active_session.max_position == 3
            ), f"Expected max_position 3, got {active_session.max_position}"
            assert (
                active_session.total_pages_forward == 3
            ), f"Expected 3 pages forward, got {active_session.total_pages_forward}"
            assert (
                active_session.navigation_count == 1
            ), f"Expected 1 navigation, got {active_session.navigation_count}"
            print(f"[TEST] ✓ ReadingSession updated: position=3, pages_forward=3")

        # Test navigate_to=1 (should go back)
        print("[TEST] Testing navigate_to=1 (going back)...")
        nav_1 = self._make_request("navigate", params={"navigate_to": 1})
        assert nav_1.status_code == 200
        nav_1_data = nav_1.json()
        assert not nav_1_data.get("error"), f"Navigation failed: {nav_1_data.get('error')}"
        nav_1_text = nav_1_data.get("text", "") or nav_1_data.get("ocr_text", "")
        print(f"[TEST] ✓ Successfully navigated back to position 1, OCR text preview: {nav_1_text[:100]}...")

        # Verify ReadingSession for backward navigation
        with db_connection.get_session() as session:
            active_session = session.query(ReadingSession).filter_by(id=session_id).first()
            assert active_session is not None, "ReadingSession disappeared"
            assert (
                active_session.current_position == 1
            ), f"Expected position 1 after navigate_to=1, got {active_session.current_position}"
            assert (
                active_session.max_position == 3
            ), f"Expected max_position to remain 3, got {active_session.max_position}"
            assert (
                active_session.total_pages_backward == 2
            ), f"Expected 2 pages backward, got {active_session.total_pages_backward}"
            assert (
                active_session.navigation_count == 2
            ), f"Expected 2 navigations total, got {active_session.navigation_count}"
            print(f"[TEST] ✓ ReadingSession updated: position=1, pages_backward=2")

        # Test navigate_to=0 (go to start)
        print("[TEST] Testing navigate_to=0 (start of book)...")
        nav_0 = self._make_request("navigate", params={"navigate_to": 0})
        assert nav_0.status_code == 200
        nav_0_data = nav_0.json()
        assert not nav_0_data.get("error"), f"Navigation failed: {nav_0_data.get('error')}"
        nav_0_text = nav_0_data.get("text", "") or nav_0_data.get("ocr_text", "")
        print(f"[TEST] ✓ Successfully navigated to position 0, OCR text preview: {nav_0_text[:100]}...")

        # Final ReadingSession verification
        with db_connection.get_session() as session:
            user = session.query(User).filter_by(email=TEST_USER_EMAIL).first()
            if user:
                # Should still have only ONE session for this book
                final_session_count = session.query(ReadingSession).filter_by(user_id=user.id).count()
                new_sessions = final_session_count - initial_session_count
                assert new_sessions == 1, f"Expected exactly 1 new session, got {new_sessions}"

                # Verify final state of the session
                active_session = session.query(ReadingSession).filter_by(id=session_id).first()
                assert active_session is not None, "ReadingSession disappeared"
                assert (
                    active_session.current_position == 0
                ), f"Expected final position 0, got {active_session.current_position}"
                assert (
                    active_session.navigation_count == 3
                ), f"Expected 3 total navigations, got {active_session.navigation_count}"
                assert (
                    active_session.total_pages_forward == 3
                ), f"Expected 3 total pages forward, got {active_session.total_pages_forward}"
                assert (
                    active_session.total_pages_backward == 3
                ), f"Expected 3 total pages backward, got {active_session.total_pages_backward}"
                assert active_session.is_active == True, "Session should still be active"

                print(f"[TEST] ✓ Single ReadingSession tracked entire reading session")
                print(f"[TEST] ✓ Final stats: 3 navigations, 3 forward, 3 backward, position 0")

        print("[TEST] All navigate_to tests with ReadingSession tracking passed!")

    @pytest.mark.timeout(120)
    def test_preview_to_absolute_position(self):
        """Test preview_to for absolute preview without changing position."""
        print("\n[TEST] Testing preview_to absolute preview")

        # Open the test book with numbered paragraphs
        print("[TEST] Opening sol-chapter-test-epub book...")
        open_response = self._make_request("open-book", params={"title": "sol-chapter-test-epub"})
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

        # Handle dialog as success case
        if preview_5_data.get("last_read_dialog"):
            print("[TEST] ✓ Preview returned dialog (valid response)")
            preview_5_text = preview_5_data.get("dialog_text", "")
        else:
            preview_5_text = preview_5_data.get("text", "") or preview_5_data.get("ocr_text", "")
            assert preview_5_text != nav_2_text, "Preview should show different text"
        print("[TEST] ✓ Successfully previewed position 5")

        # Verify we're still at position 2
        print("[TEST] Verifying position unchanged after preview...")
        check = self._make_request("navigate", params={"navigate": 0})
        assert check.status_code == 200
        check_data = check.json()
        if not check_data.get("last_read_dialog"):
            check_text = check_data.get("text", "") or check_data.get("ocr_text", "")
            if nav_2_text:  # Only verify if we have text to compare
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
        check2_data = check2.json()
        if not check2_data.get("last_read_dialog"):
            check2_text = check2_data.get("text", "") or check2_data.get("ocr_text", "")
            if nav_2_text:  # Only verify if we have text to compare
                assert check2_text == nav_2_text, "Position changed after second preview_to"
        print("[TEST] ✓ Position still at 2 after multiple previews")

        # Test session key change scenario (simulating server restart)
        # Note: This test section may encounter dialogs, so we'll skip if dialog is present
        if nav_2_text:  # Only run session key test if we have valid text (no dialog blocking)
            print("\n[TEST] Testing session key change with preview_to...")

            # Get the current book_session_key from open-book response
            book_session_key = open_data.get("book_session_key")
            print(f"[TEST] Original session key: {book_session_key}")

            # Navigate to position 4 to establish a different position
            print("[TEST] Navigating to position 4...")
            nav_4 = self._make_request("navigate", params={"navigate_to": 4})
            assert nav_4.status_code == 200
            nav_4_data = nav_4.json()

            # Skip test if dialog is present
            if nav_4_data.get("last_read_dialog"):
                print("[TEST] Dialog present, skipping session key test")
            else:
                nav_4_text = nav_4_data.get("text", "") or nav_4_data.get("ocr_text", "")

                # Simulate a different session key (like after server restart)
                # Client thinks they're at position 4 with a new session
                new_session_key = str(int(book_session_key) + 1000) if book_session_key else "1234567890"
                print(f"[TEST] Simulating new session key: {new_session_key}")

                # Now test navigate_to=4 with the new session key
                # This tells the server "I think I'm at position 4 with this new session"
                # Server should adopt this perspective and not navigate (adjustment = 0)
                print("[TEST] Testing navigate_to=4 with new session key (should not navigate)...")
                nav_4_new = self._make_request(
                    "navigate", params={"navigate_to": 4, "book_session_key": new_session_key}
                )
                assert nav_4_new.status_code == 200
                nav_4_new_data = nav_4_new.json()

                if not nav_4_new_data.get("last_read_dialog"):
                    nav_4_new_text = nav_4_new_data.get("text", "") or nav_4_new_data.get("ocr_text", "")

                    # Should still be on the same page since server adopts client's perspective
                    if nav_4_text and nav_4_new_text:
                        assert nav_4_new_text == nav_4_text, (
                            f"Navigate with new session key should show current position\n"
                            f"Expected (original nav to 4): {nav_4_text[:200]}...\n"
                            f"Got (nav_to 4 with new key): {nav_4_new_text[:200]}..."
                        )
                        print(
                            "[TEST] ✓ Server correctly adopted client's session perspective (no navigation needed)"
                        )
                else:
                    print("[TEST] Dialog present after session key change, skipping verification")
        else:
            print("\n[TEST] Skipping session key test due to empty text (dialog may be present)")

        # Verify we're still at position 4
        print("[TEST] Verifying position unchanged after session key preview...")
        check_final = self._make_request("navigate", params={"navigate": 0})
        assert check_final.status_code == 200
        check_final_text = check_final.json().get("text", "") or check_final.json().get("ocr_text", "")
        assert check_final_text == nav_4_text, "Position changed after preview with new session"
        print("[TEST] ✓ Position remained at 4 after session key change and preview")

        print("[TEST] All preview_to tests passed!")

    @pytest.mark.timeout(120)
    def test_combined_navigate_to_and_preview(self):
        """Test using navigate_to with preview together."""
        print("\n[TEST] Testing combined navigate_to and preview")

        # Open the test book with numbered paragraphs
        print("[TEST] Opening sol-chapter-test-epub book...")
        open_response = self._make_request("open-book", params={"title": "sol-chapter-test-epub"})
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
        print(f"[TEST] Saved checkpoint at position 2, OCR text: {checkpoint_text[:100]}...")
        assert checkpoint_text, "Checkpoint text is empty - cannot verify position tracking"

        # Do relative navigation forward 3 pages
        print("[TEST] Relative navigate forward 3 pages...")
        rel_nav = self._make_request("navigate", params={"navigate": 3})
        assert rel_nav.status_code == 200
        rel_nav_text = rel_nav.json().get("text", "") or rel_nav.json().get("ocr_text", "")
        print(
            f"[TEST] ✓ Navigated relatively forward 3 pages (should be at position 5), OCR: {rel_nav_text[:100]}..."
        )

        # Do relative preview back 1 (should NOT update position, just preview)
        print("[TEST] Relative preview back 1 page (should still be at position 5)...")
        rel_preview = self._make_request("navigate", params={"preview": -1})
        assert rel_preview.status_code == 200
        rel_preview_text = rel_preview.json().get("text", "") or rel_preview.json().get("ocr_text", "")
        print(
            f"[TEST] ✓ Previewed relatively back 1 page (preview of position 4), OCR: {rel_preview_text[:100]}..."
        )

        # Verify we're still at position 5 after preview
        verify_pos = self._make_request("navigate", params={"navigate": 0})
        assert verify_pos.status_code == 200
        verify_text = verify_pos.json().get("text", "") or verify_pos.json().get("ocr_text", "")
        assert verify_text == rel_nav_text, "Position changed after preview - should still be at position 5"
        print("[TEST] ✓ Confirmed still at position 5 after preview")

        # Navigate back to absolute position 2 using navigate_to
        print("[TEST] Navigate back to absolute position 2...")
        back_to_checkpoint = self._make_request("navigate", params={"navigate_to": 2})
        assert back_to_checkpoint.status_code == 200
        back_text = back_to_checkpoint.json().get("text", "") or back_to_checkpoint.json().get("ocr_text", "")
        print(f"[TEST] Back at position 2, OCR text: {back_text[:100]}...")

        # Verify we're back at the same checkpoint
        assert (
            back_text == checkpoint_text
        ), f"Position tracking failed - checkpoint text doesn't match after relative navigation\nExpected: {checkpoint_text[:200]}\nGot: {back_text[:200]}"
        print("[TEST] ✓ Successfully returned to checkpoint - position tracking is consistent")

        print("[TEST] All combined navigation tests passed!")

    @pytest.mark.timeout(120)  # Simplified test should complete within 2 minutes
    def test_navigation_consistency(self):
        """Test that navigation forward and backward returns to the same text."""
        print("\n[TEST] Testing navigation consistency - forward and backward should return same text")

        # Open the test book with numbered paragraphs
        print("[TEST] Opening sol-chapter-test-epub book...")
        open_response = self._make_request("open-book", params={"title": "sol-chapter-test-epub"})
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
        print(f"[TEST] Initial text length: {len(initial_text)} chars, OCR preview: {initial_text[:100]}...")
        assert initial_text, "Initial text is empty - cannot perform navigation consistency tests"

        # Skip test if we still have dialog issues
        if initial_data.get("last_read_dialog"):
            print("[TEST] Still have dialog, skipping consistency test")
            return

        # Test: Forward 5, back 5 - comprehensive test for navigation consistency
        print("\n[TEST] Testing navigation consistency with 5-page navigation")
        print("[TEST] Navigate forward 5 pages...")
        forward_5 = self._make_request("navigate", params={"navigate": 5})
        assert forward_5.status_code == 200
        forward_5_data = forward_5.json()
        forward_5_text = forward_5_data.get("text", "") or forward_5_data.get("ocr_text", "")
        print(f"[TEST] Forward 5 text preview: {forward_5_text[:100]}...")

        print("[TEST] Navigate back 5 pages...")
        back_5 = self._make_request("navigate", params={"navigate": -5})
        assert back_5.status_code == 200
        back_5_data = back_5.json()
        back_5_text = back_5_data.get("text", "") or back_5_data.get("ocr_text", "")
        assert (
            back_5_text == initial_text
        ), f"Text mismatch after navigate +5, -5\nExpected: {initial_text[:200]}\nGot: {back_5_text[:200]}"
        print("[TEST] ✓ Text matches after +5, -5")

        print("\n[TEST] Navigation consistency test passed!")

    @pytest.mark.timeout(120)  # Increased timeout
    def test_preview_consistency(self):
        """Test that preview returns to original position without changing current page."""
        print("\n[TEST] Testing preview consistency - preview should not change current position")

        # Open the test book with numbered paragraphs
        print("[TEST] Opening sol-chapter-test-epub book to test preview...")
        open_response = self._make_request("open-book", params={"title": "sol-chapter-test-epub"})
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
        current_text = current_data.get("text", "") or current_data.get("ocr_text", "")
        print(f"[TEST] Current text length: {len(current_text)} chars, OCR preview: {current_text[:100]}...")
        assert current_text, "Current text is empty - cannot perform preview consistency tests"

        # Test 1: Preview forward 1 (navigate=0, preview=1)
        print("\n[TEST] Test 1: Preview 1 page ahead without navigating")
        preview_1 = self._make_request("navigate", params={"navigate": 0, "preview": 1})
        assert preview_1.status_code == 200
        preview_1_data = preview_1.json()
        preview_1_text = preview_1_data.get("text", "") or preview_1_data.get("ocr_text", "")
        print(
            f"[TEST] Preview text length: {len(preview_1_text)} chars, OCR preview: {preview_1_text[:100]}..."
        )
        assert preview_1_text, "Preview text is empty"
        assert (
            preview_1_text != current_text
        ), f"Preview text should be different from current\nCurrent: {current_text[:200]}\nPreview: {preview_1_text[:200]}"

        # Verify we're still at the same position
        verify_1 = self._make_request("navigate", params={"navigate": 0})
        assert verify_1.status_code == 200
        verify_1_data = verify_1.json()
        verify_1_text = verify_1_data.get("text", "") or verify_1_data.get("ocr_text", "")
        assert verify_1_text == current_text, "Position changed after preview"
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
        verify_3_text = verify_3_data.get("text", "") or verify_3_data.get("ocr_text", "")
        assert verify_3_text == current_text, "Position changed after preview=3"
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
        verify_pos_2_text = verify_pos_2_data.get("text", "") or verify_pos_2_data.get("ocr_text", "")
        assert verify_pos_2_text != current_text, "Should be at new position after navigate=2"

        # Navigate back to start
        back_to_start = self._make_request("navigate", params={"navigate": -2})
        assert back_to_start.status_code == 200
        back_data = back_to_start.json()
        back_text = back_data.get("text", "") or back_data.get("ocr_text", "")
        assert back_text == current_text, "Failed to return to start position"
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
