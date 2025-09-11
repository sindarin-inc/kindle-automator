# Kindle Automator Project Guide

## Important: Linting

Always run `make lint` after making Python code changes to ensure proper formatting (Black, isort, flake8).

## Docker Services (Redis & Postgres)

### Restarting After Docker Crash

When Docker Desktop crashes on macOS, follow these steps:

1. **Start Docker Desktop:**

   ```bash
   open -a Docker
   # Wait ~10 seconds for Docker to fully start
   ```

2. **Start Redis and Postgres containers:**

   ```bash
   cd ../web-app
   make fast  # Starts sol_redis (port 6479) and sol_postgres (port 5496)
   ```

3. **Verify services are running:**
   ```bash
   docker ps | grep -E "sol_postgres|sol_redis"
   ```

### Redis Access

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
  - Waits for session restoration to complete (no need to sleep after running)
  - **IMPORTANT**: Always run `make claude-run` after changing server code and before testing
- **`make deps`**: Install dependencies using uv
- **`make test-*`**: Run API endpoint tests (e.g. `make test-init`, `make test-books`)
- **`make ssh`**: SSH to prod/staging (see Makefile for non-interactive command prefix)
- **Running Python**: Use `uv run dotenv run` for scripts needing env vars, `uv run` for tools
- **Running tests**: Use `uv run pytest` directly (PYTHONPATH is automatically configured)

## Running the Server

```bash
# Start server (waits to auto-restart existing emulators)
make claude-run

# Now you can make requests. This is a quick one:
curl -s http://localhost:4096/kindle/emulators/active

# Monitor logs
tail -f logs/server_output.log       # Standard logs, clears every `make claude-run`
tail -f logs/server.log              # Same as server_output.log, but persists between runs
tail -f logs/debug_server.log        # DEBUG logs, also persists
```

## SQL Debug Logging

To control SQL query logging in the debug log:

- Edit `.env` and set `SQL_LOGGING=true` to enable or `SQL_LOGGING=false` to disable
- Restart the server with `make claude-run`
- When enabled, formatted SQL queries will appear in `logs/debug_server.log`

## Redis Debug Logging

To control Redis command logging in the debug log:

- Edit `.env` and set `REDIS_LOGGING=true` to enable or `REDIS_LOGGING=false` to disable
- Restart the server with `make claude-run`
- When enabled, all Redis commands will appear in cyan in `logs/debug_server.log`
- Shows command, arguments, results, and timing for each Redis operation

## Issue References

- **KINDLE-AUTOMATOR-XXX**: Use Sentry MCP tools to look up (never use Seer AI)
  - **Organization**: `sindarin` (not solreader)
  - **Region URL**: `https://us.sentry.io`
  - **Example**: `get_issue_details(organizationSlug='sindarin', issueId='KINDLE-AUTOMATOR-XXX', regionUrl='https://us.sentry.io')`
- **Finding similar bugs**: When fixing a bug, search Sentry for other instances
  - **Example**: `search_events(organizationSlug='sindarin', projectSlug='kindle-automator', naturalLanguageQuery='TypeError "Object of type datetime is not JSON serializable" last 7 days')`
  - This helps ensure all instances of a bug are fixed, not just the reported one
- **Debug user issues**:
  1. Find user email in Sentry ticket
  2. Fetch logs: `scp PROD:/opt/kindle-automator/logs/email_log/<user_email>.log .`
  3. PROD credentials are in Makefile's `make ssh` command

## Testing

- **Local email**: Always use `sam@solreader.com` or `kindle@solreader.com`

### Authentication Setup (Simple!)

Authentication tokens are now automatically managed:

```bash
# First time setup or refresh tokens:
make refresh-auth

# Verify tokens are working:
make test-auth

# That's it! Tokens are now automatically loaded for all commands
```

The tokens are stored in `.env.auth` and automatically loaded by:
- `make test` and all test commands
- `uv run pytest ...` (via Makefile include)
- For manual curl commands, source first: `source .env.auth`

### Running Tests

```bash
# Run tests - auth tokens are automatically loaded
uv run pytest tests/test_api_integration.py::TestKindleAPIIntegration::test_specific_endpoint -v

# Or use make commands - auth is automatic
make test-api
make test-group1
```

### Manual API Requests

For manual curl requests, source the tokens first:

```bash
# Source the auth tokens
source .env.auth

# Now make authenticated requests
curl -H "Authorization: Tolkien $WEB_INTEGRATION_TEST_AUTH_TOKEN" \
     -H "Cookie: staff_token=$INTEGRATION_TEST_STAFF_AUTH_TOKEN" \
     "http://localhost:4096/kindle/emulators/active?user_email=kindle@solreader.com"
```

### Troubleshooting Auth

If authentication fails:
1. Make sure Docker containers are running: `cd ../web-app && make fast`
2. Regenerate tokens: `make refresh-auth`
3. Verify tokens work: `make test-auth`

- **After working on features**: Look through `tests/test_api_integration.py` and run the most appropriate specific test for the endpoint you modified:

  ```bash
  # Auth tokens are automatically loaded from .env.auth
  uv run pytest tests/test_api_integration.py::TestKindleAPIIntegration::test_specific_endpoint -v
  ```

- Never skip tests, they are all there for a reason

## Database Migrations

- **Idempotency**: Database migrations must be idempotent for multi-server deployments. Always check if schema changes already exist before applying them (e.g., check if a column exists before adding it). This prevents failures when deploying to multiple servers where some may have already applied manual changes or previous partial deployments.

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
- **Always include user_email**: Required in all requests (localhost:4096/kindle/screenshot?user_email=kindle@solreader.com)
- **Ensure auth**: `GET localhost:4096/staff-auth?auth=1` to set an auth cookie
- **No test files**: Unless explicitly requested
- **No backwards compatibility**: Unless asked
- **Git commits**: Do NOT commit or push anything to Git. If you want to commit, simply print out the one-liner Git commit message you would use and leave it at that. Always run `make lint` before suggesting a commit.
- **Screenshots and XML**: To retrieve screenshots and xml, use the proxy server with authentication:
  ```bash
  # For XML: http://localhost:4096/kindle/screenshot?user_email=kindle@solreader.com&xml=1
  # For image: http://localhost:4096/kindle/screenshot?user_email=kindle@solreader.com&xml=0
  # MUST include authentication cookies (see Testing section)
  ```
- **NO DEPLOYMENTS**: Never deploy anything with Ansible unless explicitly asked by the user. Only make configuration changes and fixes to the codebase.

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

## Proxy Server

**CRITICAL: All `/kindle/*` endpoints go through the proxy server (port 4096), NEVER directly to the Flask server (port 4098).**

- **NEVER access the Flask server directly on port 4098** - it will not work and is not the correct approach
- The proxy server (port 4096) is the ONLY way to access Kindle functionality
- The proxy server maintains book caches and additional functionality
- `/kindle/open-random-book` only exists on the proxy server (uses cached book list)
- **If the proxy server returns an error**: Debug the proxy authentication (see Testing section), DO NOT try the Flask server
- **Authentication is REQUIRED**: All proxy requests need authentication - use BOTH tokens:
  ```bash
  # Source the auth tokens first
  source .env.auth
  
  # For API endpoints - use both Authorization header AND staff_token cookie:
  curl -H "Authorization: Tolkien $WEB_INTEGRATION_TEST_AUTH_TOKEN" \
       -H "Cookie: staff_token=$INTEGRATION_TEST_STAFF_AUTH_TOKEN" \
       "http://localhost:4096/kindle/endpoint"
  
  # For admin interface (/kindle/admin/*) - same authentication:
  curl -H "Authorization: Tolkien $WEB_INTEGRATION_TEST_AUTH_TOKEN" \
       -H "Cookie: staff_token=$INTEGRATION_TEST_STAFF_AUTH_TOKEN" \
       "http://localhost:4096/kindle/admin/"
  ```
