"""
ANSI color codes for terminal text formatting.

This module provides a comprehensive set of ANSI color and style codes
that can be used to format terminal output text.

Usage:
    from server.ansi_colors import GREEN, BOLD, RESET
    print(f"{GREEN}{BOLD}Success!{RESET} The operation completed.")
"""

# Regular colors
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
GRAY = "\033[90m"

# Bright colors
BRIGHT_BLACK = "\033[90m"  # Often appears as dark gray
BRIGHT_RED = "\033[91m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_BLUE = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"

# Dim colors (reduced intensity)
DIM_BLACK = "\033[30;2m"
DIM_RED = "\033[31;2m"
DIM_GREEN = "\033[32;2m"
DIM_YELLOW = "\033[33;2m"
DIM_BLUE = "\033[34;2m"
DIM_MAGENTA = "\033[35;2m"
DIM_CYAN = "\033[36;2m"
DIM_WHITE = "\033[37;2m"
DIM_GRAY = "\033[90;2m"

# Background colors
BG_BLACK = "\033[40m"
BG_RED = "\033[41m"
BG_GREEN = "\033[42m"
BG_YELLOW = "\033[43m"
BG_BLUE = "\033[44m"
BG_MAGENTA = "\033[45m"
BG_CYAN = "\033[46m"
BG_WHITE = "\033[47m"

# Bright background colors
BG_BRIGHT_BLACK = "\033[100m"
BG_BRIGHT_RED = "\033[101m"
BG_BRIGHT_GREEN = "\033[102m"
BG_BRIGHT_YELLOW = "\033[103m"
BG_BRIGHT_BLUE = "\033[104m"
BG_BRIGHT_MAGENTA = "\033[105m"
BG_BRIGHT_CYAN = "\033[106m"
BG_BRIGHT_WHITE = "\033[107m"

# Text styles
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
BLINK = "\033[5m"
REVERSE = "\033[7m"  # Reverse foreground & background colors
HIDDEN = "\033[8m"
STRIKETHROUGH = "\033[9m"

# Reset codes
RESET = "\033[0m"  # Reset all styles and colors
RESET_BOLD = "\033[21m"
RESET_DIM = "\033[22m"
RESET_ITALIC = "\033[23m"
RESET_UNDERLINE = "\033[24m"
RESET_BLINK = "\033[25m"
RESET_REVERSE = "\033[27m"
RESET_HIDDEN = "\033[28m"
RESET_STRIKETHROUGH = "\033[29m"


def color_text(text, color_code):
    """Wrap text with the specified color code and reset code.

    Args:
        text (str): The text to colorize
        color_code (str): ANSI color code to apply

    Returns:
        str: Colorized text string with reset code appended
    """
    return f"{color_code}{text}{RESET}"


def style_text(text, *style_codes):
    """Apply multiple styles to text.

    Args:
        text (str): The text to style
        *style_codes: Variable number of ANSI style/color codes

    Returns:
        str: Styled text string with reset code appended
    """
    return f"{''.join(style_codes)}{text}{RESET}"


# Common combinations
def error(text):
    """Format text as an error message (bright red)."""
    return style_text(text, BRIGHT_RED, BOLD)


def warning(text):
    """Format text as a warning message (bright yellow)."""
    return style_text(text, BRIGHT_YELLOW)


def success(text):
    """Format text as a success message (bright green)."""
    return style_text(text, BRIGHT_GREEN)


def info(text):
    """Format text as an informational message (bright cyan)."""
    return style_text(text, BRIGHT_CYAN)


def debug(text):
    """Format text as a debug message (dim gray)."""
    return style_text(text, DIM_GRAY)


def highlight(text):
    """Format text as highlighted (magenta background, white text)."""
    return style_text(text, BG_MAGENTA, WHITE)


# Detect if terminal supports colors
def supports_color():
    """Determine if the current terminal supports ANSI color codes.

    Returns:
        bool: True if terminal supports colors, False otherwise
    """
    import os
    import sys

    # Return False if stdout is not a terminal
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False

    # Check environment variables
    if "NO_COLOR" in os.environ:
        return False

    if "TERM" in os.environ:
        return os.environ["TERM"] != "dumb"

    # Default to True for posix systems, False otherwise
    return os.name == "posix"
