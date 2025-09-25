"""Test utilities for fuzzy text matching and other test helpers."""

import difflib


def fuzzy_match_ocr_text(text1, text2, min_length=100, min_similarity=0.95):
    """
    Check if two OCR'd text strings are similar enough to be considered equal.

    OCR is non-deterministic and may produce slightly different results for the same image.
    This function allows for fuzzy matching when:
    1. Both texts are long enough (>= min_length characters)
    2. They are similar enough (>= min_similarity ratio)

    Args:
        text1: First text string
        text2: Second text string
        min_length: Minimum length for fuzzy matching (default 100)
        min_similarity: Minimum similarity ratio (default 0.95 = 95%)

    Returns:
        True if texts match (either exactly or fuzzily), False otherwise
    """
    # Handle None/empty cases
    if not text1 or not text2:
        return text1 == text2

    # Exact match is always good
    if text1 == text2:
        return True

    # For short texts, require exact match
    if len(text1) < min_length or len(text2) < min_length:
        return False

    # Calculate similarity ratio using SequenceMatcher
    # This gives us a ratio between 0 and 1 indicating how similar the strings are
    similarity = difflib.SequenceMatcher(None, text1, text2).ratio()

    # Return True if similarity is above threshold
    return similarity >= min_similarity


def assert_ocr_text_match(text1, text2, message=None, min_length=100, min_similarity=0.95):
    """
    Assert that two OCR'd texts match, allowing for fuzzy matching on long texts.

    Args:
        text1: First text string
        text2: Second text string
        message: Optional assertion message
        min_length: Minimum length for fuzzy matching (default 100)
        min_similarity: Minimum similarity ratio (default 0.95 = 95%)

    Raises:
        AssertionError if texts don't match
    """
    if fuzzy_match_ocr_text(text1, text2, min_length, min_similarity):
        return

    # Calculate similarity for error message
    similarity = 0.0
    if text1 and text2:
        similarity = difflib.SequenceMatcher(None, text1, text2).ratio()

    # Build detailed error message
    error_parts = []
    if message:
        error_parts.append(message)

    error_parts.extend(
        [
            f"OCR texts don't match (similarity: {similarity:.2%})",
            f"Text 1 length: {len(text1) if text1 else 0} chars",
            f"Text 2 length: {len(text2) if text2 else 0} chars",
        ]
    )

    # Show first 200 chars of each for debugging
    if text1:
        error_parts.append(f"Text 1: {text1[:200]}...")
    if text2:
        error_parts.append(f"Text 2: {text2[:200]}...")

    # If they're long enough for fuzzy matching but didn't match, show why
    if text1 and text2 and len(text1) >= min_length and len(text2) >= min_length:
        error_parts.append(
            f"Note: Texts are long enough for fuzzy matching (>= {min_length} chars) "
            f"but similarity ({similarity:.2%}) is below threshold ({min_similarity:.0%})"
        )

    raise AssertionError("\n".join(error_parts))
