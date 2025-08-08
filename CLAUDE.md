# Kindle Automator Project Guide

## Important: Linting

Always run `make lint` after making Python code changes to ensure proper formatting (Black, isort, flake8).

## Redis Access

The project uses Redis on port 6479 (database 1) via Docker container `sol_redis`. 
To access Redis for debugging:

```bash
# Check active requests
docker exec sol_redis redis-cli -p 6479 -n 1 keys "kindle:active_request:*"

# Get specific request data
docker exec sol_redis redis-cli -p 6479 -n 1 get "kindle:active_request:user@email.com"

# Monitor Redis commands in real-time
docker exec sol_redis redis-cli -p 6479 -n 1 monitor
```

## Commands

- **`make lint`**: Run isort, black, and flake8 formatting tools
- **`make claude-run`**: Start Flask server in background (auto-kills existing servers)
  - If "Port 4098 is in use", just run it again
- **`make deps`**: Install dependencies using uv
- **`make test-*`**: Run API endpoint tests (e.g. `make test-init`, `make test-books`)
- **`make ssh`**: SSH to prod/staging (see Makefile for non-interactive command prefix)
- **Running Python**: Use `uv run dotenv run` for scripts needing env vars, `uv run` for tools
- **Running tests**: Use `uv run pytest` directly (no PYTHONPATH needed)

## Running the Server

```bash
# Start server (auto-kills existing)
make claude-run

# IMPORTANT: Wait at least 20 seconds for emulators to boot before making requests
# The server starts instantly, but emulators need time to become ready
sleep 20

# Now you can make requests
curl -s http://localhost:4098/emulators/active

# Monitor logs
tail -f logs/server_output.log       # Standard logs, clears every `make claude-run`
tail -f logs/server.log              # Same as server_output.log, but persists between runs
tail -f logs/debug_server.log        # DEBUG logs + SQL queries, also persists
```

## Issue References

- **KINDLE-AUTOMATOR-XXX**: Use Sentry MCP tools to look up (never use Seer AI)
- **Debug user issues**:
  1. Find user email in Sentry ticket
  2. Fetch logs: `scp PROD:/opt/kindle-automator/logs/email_log/<user_email>.log .`
  3. PROD credentials are in Makefile's `make ssh` command

## Testing

- **Local email**: Always use `sam@solreader.com`
- **Staff token for other emails**:
  ```bash
  # Use cookie jar (recommended)
  curl -s -c cookies.txt -X GET "http://localhost:4098/staff-auth?auth=1" > /dev/null
  curl -b cookies.txt -X GET "http://localhost:4098/auth?user_email=recreate@solreader.com&recreate=1"
  ```
  Note: Full token only in Set-Cookie header, not JSON response

## Code Style

- **Formatting**: 110 char line length with Black
- **Imports**: All imports at the top of the file
- **Naming**: snake_case for functions/variables, PascalCase for classes
- **State machine**: Core architecture pattern
- **XPATHs**: Define in view_strategies.py or interaction_strategies.py
- **Diagnostics**: Use `store_page_source()` and `driver.save_screenshot()` on errors
- **DRY**: Think extra to avoid repeating code
- **Comments**: Only if adding non-obvious context or explaining complexity

## Development Guidelines

- **Never kill emulators/servers directly**: Use `make claude-run` or `/shutdown` API
- **Always include sindarin_email**: Required in staff auth requests
- **No test files**: Unless explicitly requested
- **No backwards compatibility**: Unless asked
- **Git commits**: Provide one-line messages, but no git add/commit commands

## Project Structure

- **server/**: Flask REST API (server.py entrypoint)
- **views/**: App state management, UI interactions
- **handlers/**: Actions for app states
- **fixtures/**: XML dumps and views for testing

## Ansible Commands

- `ansible-playbook ansible/provision.yml -t vnc`: Setup VNC
- `ansible-playbook ansible/provision.yml -t android-x86`: Setup Android x86
- `ansible-playbook ansible/provision.yml -t server`: Setup server
- `ansible-playbook ansible/deploy.yml`: Deploy to prod
