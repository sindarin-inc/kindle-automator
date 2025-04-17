# ANSI Terminal Colors Module

This module provides a comprehensive set of ANSI color and style codes for formatting terminal output. It includes both direct color/style constants and helper functions to make terminal output more readable and user-friendly.

## Features

- Complete set of ANSI colors (standard, bright, and dim variants)
- Background colors
- Text styling (bold, italic, underline, etc.)
- Helper functions for common styling needs (error, warning, success, etc.)
- Terminal color support detection
- Functions to easily apply multiple styles at once

## Usage

### Basic Colors

```python
from server.ansi_colors import RED, GREEN, BLUE, RESET

print(f"{RED}This text is red{RESET}")
print(f"{GREEN}This text is green{RESET}")
print(f"{BLUE}This text is blue{RESET}")
```

### Bright and Dim Variants

```python
from server.ansi_colors import BRIGHT_RED, DIM_RED, RESET

print(f"{BRIGHT_RED}This text is bright red{RESET}")
print(f"{DIM_RED}This text is dim red{RESET}")
```

### Text Styles

```python
from server.ansi_colors import BOLD, UNDERLINE, ITALIC, RESET

print(f"{BOLD}This text is bold{RESET}")
print(f"{UNDERLINE}This text is underlined{RESET}")
print(f"{ITALIC}This text is italic{RESET} (not supported in all terminals)")
```

### Background Colors

```python
from server.ansi_colors import BG_BLUE, WHITE, RESET

print(f"{BG_BLUE}{WHITE}White text on blue background{RESET}")
```

### Combinations

```python
from server.ansi_colors import RED, BOLD, UNDERLINE, RESET

print(f"{RED}{BOLD}{UNDERLINE}Bold underlined red text{RESET}")
```

### Helper Functions

```python
from server.ansi_colors import error, warning, success, info, debug, highlight

print(error("An error occurred!"))
print(warning("Warning: This is important"))
print(success("Operation completed successfully"))
print(info("Here's some information"))
print(debug("Debug message"))
print(highlight("This text stands out"))
```

### Advanced Helpers

```python
from server.ansi_colors import color_text, style_text, CYAN, BOLD, UNDERLINE

# Apply a single color
print(color_text("This text is cyan", CYAN))

# Apply multiple styles at once
print(style_text("Bold underlined cyan", BOLD, UNDERLINE, CYAN))
```

### Color Support Detection

```python
from server.ansi_colors import supports_color

if supports_color():
    print("This terminal supports colors")
else:
    print("This terminal does not support colors")
```

## Demo

A demonstration script is included to showcase all available colors and styles:

```bash
python -m server.ansi_colors_demo
```

This will display all available colors, styles, and helper functions with examples.

## Notes

- Not all terminals support all ANSI color and style codes
- Some styles like italic and strikethrough have limited support
- Colors may appear differently depending on terminal color scheme settings
- The `supports_color()` function detects if a terminal likely supports colors, but it's not 100% reliable

## In the Codebase

This module is used throughout the application for:

- Request/response logging (paths in magenta, bodies in dim yellow)
- Error messages (bright red)
- Success confirmations (bright green)
- Debugging information (dim colors)
- Highlighting important information