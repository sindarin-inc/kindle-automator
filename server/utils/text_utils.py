"""Text processing utilities."""

import re


def strip_ansi_codes(text):
    """Remove ANSI color codes from text."""
    if text is None:
        return ""
    # Remove ANSI escape sequences (ESC[...m format)
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    text = ansi_escape.sub("", text)
    # Remove escaped ANSI codes (when stored as \u001b in logs)
    text = re.sub(r"\\u001b\[[0-9;]*m", "", text)
    text = re.sub(r"\u001b\[[0-9;]*m", "", text)
    return text
