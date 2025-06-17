#!/usr/bin/env python3
"""Test script to verify authentication loop fix"""

import logging
from unittest.mock import MagicMock, Mock

from handlers.auth_handler import LoginVerificationState
from views.core.app_state import AppState
from views.transitions import StateTransitions

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_sign_in_handler_with_vnc_auth():
    """Test that handle_sign_in returns True when VNC auth is required"""

    # Create mock objects
    mock_view_inspector = Mock()
    mock_auth_handler = Mock()
    mock_permissions_handler = Mock()
    mock_library_handler = Mock()
    mock_reader_handler = Mock()

    # Create StateTransitions instance
    transitions = StateTransitions(
        mock_view_inspector,
        mock_auth_handler,
        mock_permissions_handler,
        mock_library_handler,
        mock_reader_handler,
    )

    # Mock the auth_handler.sign_in() to return VNC required error
    mock_auth_handler.sign_in.return_value = (
        LoginVerificationState.ERROR,
        "Authentication must be done manually via VNC",
    )

    # Test handle_sign_in
    result = transitions.handle_sign_in()

    # Verify it returns True (not False) to prevent loop
    assert result == True, f"Expected True, got {result}"
    logger.info("✓ handle_sign_in correctly returns True for VNC auth")


def test_sign_in_handler_with_no_credentials():
    """Test that handle_sign_in returns False when no credentials provided"""

    # Create mock objects
    mock_view_inspector = Mock()
    mock_auth_handler = Mock()
    mock_permissions_handler = Mock()
    mock_library_handler = Mock()
    mock_reader_handler = Mock()

    # Create StateTransitions instance
    transitions = StateTransitions(
        mock_view_inspector,
        mock_auth_handler,
        mock_permissions_handler,
        mock_library_handler,
        mock_reader_handler,
    )

    # Mock the auth_handler.sign_in() to return no credentials error
    mock_auth_handler.sign_in.return_value = (LoginVerificationState.ERROR, "No credentials provided")

    # Test handle_sign_in
    result = transitions.handle_sign_in()

    # Verify it returns False to stop transitions
    assert result == False, f"Expected False, got {result}"
    logger.info("✓ handle_sign_in correctly returns False for no credentials")


def test_library_sign_in_loop_prevention():
    """Test that transition_to_library prevents LIBRARY_SIGN_IN loops"""
    from views.state_machine import KindleStateMachine

    # Create mock driver
    mock_driver = MagicMock()
    mock_driver.automator = Mock()
    mock_driver.automator.profile_manager = Mock()
    mock_driver.automator.profile_manager.get_current_profile.return_value = {"email": "test@example.com"}

    # Create state machine
    state_machine = KindleStateMachine(mock_driver)

    # Mock the _get_current_state to simulate LIBRARY_SIGN_IN -> SIGN_IN sequence
    states = [AppState.LIBRARY_SIGN_IN, AppState.SIGN_IN, AppState.SIGN_IN]
    state_index = 0

    def mock_get_current_state():
        nonlocal state_index
        if state_index < len(states):
            state = states[state_index]
            state_index += 1
            return state
        return AppState.SIGN_IN

    state_machine._get_current_state = mock_get_current_state

    # Mock the handlers
    state_machine.transitions.handle_library_sign_in = Mock(return_value=True)
    state_machine.transitions.handle_sign_in = Mock(return_value=True)

    # Run transition_to_library with max_transitions=10
    result = state_machine.transition_to_library(max_transitions=10)

    # Verify it returns True (doesn't fail due to max transitions)
    assert result == True, f"Expected True, got {result}"

    # Verify we didn't hit max transitions
    assert (
        state_machine.transitions.handle_library_sign_in.call_count == 1
    ), f"handle_library_sign_in called {state_machine.transitions.handle_library_sign_in.call_count} times"

    logger.info("✓ transition_to_library correctly prevents LIBRARY_SIGN_IN loops")


if __name__ == "__main__":
    logger.info("Testing authentication loop fixes...")

    test_sign_in_handler_with_vnc_auth()
    test_sign_in_handler_with_no_credentials()
    test_library_sign_in_loop_prevention()

    logger.info("\nAll tests passed! ✓")
