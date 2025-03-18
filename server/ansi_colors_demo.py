#!/usr/bin/env python
"""
Demo script for ANSI colors module.

This script demonstrates the usage of the ANSI colors module by printing
sample text with different colors and styles.

Run this script directly to see all available colors and styles.
"""

from server.ansi_colors import (  # Basic colors; Bright colors; Dim colors; Background colors; Text styles; Reset; Helper functions
    BG_BLUE,
    BG_CYAN,
    BG_GREEN,
    BG_MAGENTA,
    BG_RED,
    BG_YELLOW,
    BLACK,
    BLUE,
    BOLD,
    BRIGHT_BLUE,
    BRIGHT_CYAN,
    BRIGHT_GREEN,
    BRIGHT_MAGENTA,
    BRIGHT_RED,
    BRIGHT_WHITE,
    BRIGHT_YELLOW,
    CYAN,
    DIM_BLUE,
    DIM_CYAN,
    DIM_GREEN,
    DIM_MAGENTA,
    DIM_RED,
    DIM_YELLOW,
    GRAY,
    GREEN,
    ITALIC,
    MAGENTA,
    RED,
    RESET,
    REVERSE,
    STRIKETHROUGH,
    UNDERLINE,
    WHITE,
    YELLOW,
    color_text,
    debug,
    error,
    highlight,
    info,
    style_text,
    success,
    supports_color,
    warning,
)


def print_color_samples():
    """Print samples of all colors and styles."""
    if not supports_color():
        print("Your terminal does not support colors. The examples below won't display correctly.")

    print("\n=== Basic Colors ===")
    print(f"{BLACK}BLACK{RESET} (might not be visible on dark backgrounds)")
    print(f"{RED}RED{RESET}")
    print(f"{GREEN}GREEN{RESET}")
    print(f"{YELLOW}YELLOW{RESET}")
    print(f"{BLUE}BLUE{RESET}")
    print(f"{MAGENTA}MAGENTA{RESET}")
    print(f"{CYAN}CYAN{RESET}")
    print(f"{WHITE}WHITE{RESET} (might not be visible on light backgrounds)")
    print(f"{GRAY}GRAY{RESET}")

    print("\n=== Bright Colors ===")
    print(f"{BRIGHT_RED}BRIGHT_RED{RESET}")
    print(f"{BRIGHT_GREEN}BRIGHT_GREEN{RESET}")
    print(f"{BRIGHT_YELLOW}BRIGHT_YELLOW{RESET}")
    print(f"{BRIGHT_BLUE}BRIGHT_BLUE{RESET}")
    print(f"{BRIGHT_MAGENTA}BRIGHT_MAGENTA{RESET}")
    print(f"{BRIGHT_CYAN}BRIGHT_CYAN{RESET}")

    print("\n=== Dim Colors ===")
    print(f"{DIM_RED}DIM_RED{RESET}")
    print(f"{DIM_GREEN}DIM_GREEN{RESET}")
    print(f"{DIM_YELLOW}DIM_YELLOW{RESET}")
    print(f"{DIM_BLUE}DIM_BLUE{RESET}")
    print(f"{DIM_MAGENTA}DIM_MAGENTA{RESET}")
    print(f"{DIM_CYAN}DIM_CYAN{RESET}")

    print("\n=== Background Colors ===")
    print(f"{BG_RED}BG_RED{RESET}")
    print(f"{BG_GREEN}BG_GREEN{RESET}")
    print(f"{BG_YELLOW}BG_YELLOW{RESET}")
    print(f"{BG_BLUE}BG_BLUE{RESET}")
    print(f"{BG_MAGENTA}BG_MAGENTA{RESET}")
    print(f"{BG_CYAN}BG_CYAN{RESET}")

    print("\n=== Text Styles ===")
    print(f"{BOLD}BOLD{RESET}")
    print(f"{ITALIC}ITALIC{RESET} (not supported in all terminals)")
    print(f"{UNDERLINE}UNDERLINE{RESET}")
    print(f"{REVERSE}REVERSE{RESET}")
    print(f"{STRIKETHROUGH}STRIKETHROUGH{RESET} (not supported in all terminals)")

    print("\n=== Combinations ===")
    print(f"{RED}{BOLD}RED + BOLD{RESET}")
    print(f"{BLUE}{UNDERLINE}BLUE + UNDERLINE{RESET}")
    print(f"{BG_YELLOW}{BLACK}BLACK ON YELLOW{RESET}")
    print(f"{BG_BLUE}{BRIGHT_WHITE}{BOLD}BOLD WHITE ON BLUE{RESET}")

    print("\n=== Helper Functions ===")
    print(f"color_text(): {color_text('This text is cyan', CYAN)}")
    print(f"style_text(): {style_text('Bold underlined red', BOLD, UNDERLINE, RED)}")
    print(f"error(): {error('This is an error message')}")
    print(f"warning(): {warning('This is a warning message')}")
    print(f"success(): {success('This is a success message')}")
    print(f"info(): {info('This is an info message')}")
    print(f"debug(): {debug('This is a debug message')}")
    print(f"highlight(): {highlight('This text is highlighted')}")


if __name__ == "__main__":
    print("ANSI Colors Demo")
    print("===============")
    print("\nThis script demonstrates the available colors and styles.")
    print_color_samples()
    print("\nUsage in code:")
    print("from server.ansi_colors import RED, BOLD, RESET")
    print('print(f"{RED}{BOLD}This is bold red text{RESET} and this is normal text")')
    print("\n# Or using helper functions:")
    print("from server.ansi_colors import error, success")
    print('print(f"{error("Error!")} Something went wrong")')
    print('print(f"{success("Success!")} Operation completed")')
