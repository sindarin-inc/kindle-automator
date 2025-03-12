# Kindle Automator Project Guide

## Commands
- `make server`: Start the Flask server
- `make deps`: Install dependencies using uv
- `make lint`: Run isort, black, and flake8
- `make test-*`: Run various API endpoint tests (e.g. `make test-init`, `make test-books`)
- `make reinstall`: Reinstall the application
- `make kill-server`: Kill server and appium processes

## Code Style
- **Formatting**: 110 character line length with Black
- **Imports**: Standard library first, third-party second, local modules last
- **Naming**: Snake case for functions/variables, PascalCase for classes
- **Error handling**: Try/except with detailed logging
- **Functions**: Document with docstrings
- **State machine**: Core architecture pattern for app state management
- **Exception handling**: Use decorators like `ensure_automator_healthy` for cross-cutting concerns
- **XPATHs**: All XPATHs should be defined in view_strategies.py or interaction_strategies.py files within the corresponding view directory

## Project Structure
- **server/**: Flask REST API (server.py is the entrypoint)
- **views/**: App state management, UI interactions, state transitions
- **handlers/**: Implements actions for different app states
- **fixtures/**: XML dumps and views for testing