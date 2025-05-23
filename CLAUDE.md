# Kindle Automator Project Guide

## Commands

- `make server`: Start the Flask server
- `make deps`: Install dependencies using uv
- `make lint`: Run isort, black, and flake8
- `make test-*`: Run various API endpoint tests (e.g. `make test-init`, `make test-books`)
- `make reinstall`: Reinstall the application
- `make kill-server`: Kill server and appium processes

## Virtualenv Management

- `workon kindle-automator`: Source the virtualenv for the Kindle Automator project, activating the virtual environment located at ~/.virtualenvs/kindle-automator/bin/activate
- You need to have already setup the kindle-automator virutalenv when running `make server`

## Ansible Commands

- `ansible-playbook ansible/provision.yml -t vnc`: Setup VNC server role
- `ansible-playbook ansible/provision.yml -t android-x86`: Setup Android x86 role
- `ansible-playbook ansible/provision.yml -t server`: Setup server role
- `ansible-playbook ansible/deploy.yml`: Deploy Flask server to prod

## Code Style

- **Formatting**: 110 character line length with Black
- **Imports**: Standard library first, third-party second, local modules last
- **Naming**: Snake case for functions/variables, PascalCase for classes
- **Error handling**: Try/except with detailed logging
- **Functions**: Document with docstrings
- **State machine**: Core architecture pattern for app state management
- **Exception handling**: Use decorators like `ensure_automator_healthy` for cross-cutting concerns
- **XPATHs**: All XPATHs should be defined in view_strategies.py or interaction_strategies.py files within the corresponding view directory
- **Diagnostics**: Add page source XML dump and screenshot capture to error paths using `store_page_source()` and `driver.save_screenshot()`
- **Git commits**: Keep commit messages short and focused on a single change
- **Backwards compatibility**: Don't ever write logic to handle backwards compatibility unless asked
- **DRY**: Keep it DRY, so do extra thinking to ensure we don't repeat code
- **Comments**: Only include comments if they add context that's not readily apparent in the next line of code or if the code block has some complexity
- **Comments**: Don't add comments that are simply addressing the prompt, only add them if the comments clear up confusion

## Project Structure

- **server/**: Flask REST API (server.py is the entrypoint)
- **views/**: App state management, UI interactions, state transitions
- **handlers/**: Implements actions for different app states
- **fixtures/**: XML dumps and views for testing

## Development Guidelines

- Don't make test files unless directed to
