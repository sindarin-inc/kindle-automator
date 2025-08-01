# Kindle Automator Project Guide

## Testing

- **Local testing email**: Always use `sam@solreader.com` when testing API endpoints locally
- **Staff token generation**: To test with different user emails (e.g., `recreate@solreader.com`):

  ```bash
  # Generate token and use it inline
  TOKEN=$(curl -s -X GET "http://localhost:4098/staff-auth?auth=1" | jq -r '.token')

  # Use the token in requests
  curl -X GET "http://localhost:4098/auth?user_email=recreate@solreader.com&recreate=1" \
    -H "Cookie: staff_token=$TOKEN"
  ```

## Issue References

- When you see references to KINDLE-AUTOMATOR-[A-Z0-9]+ (e.g., KINDLE-AUTOMATOR-8), use the Sentry MCP tools to look up the issue details
- Never use Sentry's Seer AI analysis - fix issues using Claude Code instead
- When investigating a Sentry issue, look for the user's email address in the ticket details
- Fetch the user's log file from production using SCP: `scp PROD:/opt/kindle-automator/logs/email_log/<user_email>.log .`
- The PROD server's credentials are the same as specified in the Makefile's `make ssh` command
- This provides detailed logs for debugging exactly what's happening to that specific user

## Commands

- **Running Python scripts**: Use `uv run` to execute any Python script (e.g., `uv run python script.py`, `uv run pytest tests/`)
- `make claude-run`: Start the Flask server in the background. It will auto-kill other running servers.
  - **Port conflict handling**: If `make claude-run` fails with "Port 4098 is in use", just run it again - it auto-kills the conflicting server
- `make deps`: Install dependencies using uv
- `make lint`: Run isort, black, and flake8
- `make test-*`: Run various API endpoint tests (e.g. `make test-init`, `make test-books`)
- `make reinstall`: Reinstall the application
- `make ssh`: Use the Makefile to SSH into prod or staging with the appropriate non-interactive command prefix

## Running the server

```bash
# Start server in background (automatically kills existing server)
make claude-run

# The server starts instantly - no need to sleep before making requests
curl -s http://localhost:4098/emulators/active

# Monitor server logs in real-time
tail -f logs/server_output.log

# Monitor DEBUG-level server logs + sql queries in real-time
tail -f logs/debug_server.log

# Or just check the last 20 lines
tail -n 20 logs/server_output.log
```

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
- **Git commits**: Keep commit messages short and focused on a single change. Don't use git add or git commit commands - instead, include a one-line commit message in your summary when you want to commit changes
- **Backwards compatibility**: Don't ever write logic to handle backwards compatibility unless asked
- **DRY**: Keep it DRY, so do extra thinking to ensure we don't repeat code
- **Comments**: Only include comments if they add context that's not readily apparent in the next line of code or if the code block has some complexity
- **Comments**: Don't add comments that are simply addressing the prompt, only add them if the comments clear up confusion
- **Linting**: Run `make lint` after making code changes to ensure formatting compliance

## Linting & Formatting

- Run formatting tools: `make lint`
- **Important**: Always run `make lint` after changing Python code to ensure proper formatting and import sorting

## Project Structure

- **server/**: Flask REST API (server.py is the entrypoint)
- **views/**: App state management, UI interactions, state transitions
- **handlers/**: Implements actions for different app states
- **fixtures/**: XML dumps and views for testing

## Development Guidelines

- Don't make test files unless directed to
- If you need to use ssh for prod or staging, read the Makefile to see how `make ssh` and `make ssh-staging` work so you can make a non-interactive ssh command prefix for what you want to do on prod or staging
- **Never kill emulators or servers directly**: Always use `make claude-run` to restart the server (it auto-kills existing servers) or the `/shutdown` API endpoint to gracefully shutdown emulators
- **Always pass sindarin_email parameter**: When using staff authentication, include `sindarin_email` parameter in each request body/params to properly identify the user context

## SQL Query Logging

In development mode (`FLASK_ENV=development`), all SQL queries are logged with:

- **Colorization**: SELECT queries in yellow, UPDATE queries in teal
- **Timing**: Shows execution time for each query
- **Full values**: Parameters are rendered with actual values
- **To disable**: Set `SQL_LOGGING=false` before starting the server
  ```bash
  SQL_LOGGING=false make claude-run
  ```
