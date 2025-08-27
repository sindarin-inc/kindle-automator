.PHONY: server test init

run: server

init:
	@echo "Setting up virtual environment with uv..."
	@uv venv
	@echo "Installing dependencies..."
	@uv pip install -r requirements.txt
	@echo "Setup complete! You can now run 'make server' or 'make claude-run'"

claude-run: 
	@echo "Starting Flask server in background..."
	@# Check if previous shutdown is still ongoing
	@if [ -f logs/server_output.log ] && grep -q "=== Beginning graceful shutdown sequence ===" logs/server_output.log 2>/dev/null && ! grep -q "=== Graceful shutdown complete ===" logs/server_output.log 2>/dev/null; then \
		echo "Waiting for previous shutdown to complete..."; \
		timeout=60; \
		elapsed=0; \
		while [ $$elapsed -lt $$timeout ]; do \
			if grep -q "=== Graceful shutdown complete ===" logs/server_output.log 2>/dev/null; then \
				break; \
			fi; \
			echo "  Still shutting down previous instance... ($$elapsed seconds)"; \
			sleep 2; \
			elapsed=$$((elapsed + 2)); \
		done; \
	fi
	@# Clear the log file before starting new server
	@> logs/server_output.log
	@# Start the server in background
	@bash -c '(NO_COLOR_CONSOLE=1 FLASK_ENV=development PYTHONPATH=$$(pwd) uv run python -m server.server > logs/server_output.log 2>&1 & echo $$! > logs/server.pid) &'
	@sleep 1
	@echo "Server started with PID $$(cat logs/server.pid)"
	@echo "Waiting for session restoration to complete..."
	@# Wait for session restoration to complete (with timeout of 120 seconds)
	@timeout=120; \
	elapsed=0; \
	while [ $$elapsed -lt $$timeout ]; do \
		if grep -q "Database connection failed" logs/server_output.log 2>/dev/null; then \
			echo ""; \
			echo "❌ ERROR: Database connection failed!"; \
			echo ""; \
			echo "The PostgreSQL database is not running or not accessible."; \
			echo ""; \
			echo "To fix this:"; \
			echo "  1. Check if Docker is running: docker ps"; \
			echo "  2. Start the database container: docker start sol_postgres"; \
			echo "  3. Or run the full stack: cd ../web-app && make fast"; \
			echo ""; \
			echo "Check logs/server_output.log for details"; \
			exit 1; \
		fi; \
		if grep -q "=== Session restoration complete ===" logs/server_output.log 2>/dev/null; then \
			echo ""; \
			echo "✓ Server is ready! Session restoration complete."; \
			echo ""; \
			echo "Monitor logs with: tail -f logs/server_output.log"; \
			echo "To stop the server and start a new server, run: make claude-run"; \
			exit 0; \
		fi; \
		echo "  Waiting for session restoration... ($$elapsed seconds elapsed)"; \
		sleep 3; \
		elapsed=$$((elapsed + 3)); \
	done; \
	echo "Timeout waiting for session restoration after $$timeout seconds"; \
	echo "Check logs/server_output.log for issues"; \
	exit 1

deps:
	uv pip install -r requirements.txt

lint:
	uv run isort --profile black .
	uv run black --line-length 110 .
	uv run flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=venv,.venv
	
# Start the Flask server
server:
	@echo "Starting Flask server..."
	@FLASK_ENV=development PYTHONPATH=$(shell pwd) uv run python -m server.server

# Start an interactive shell with the environment setup
shell:
	@echo "Starting interactive shell..."
	@PYTHONPATH=$(shell pwd) uv run python shell.py

test:
	@echo "========================================="
	@echo "Running ALL tests grouped by integration"
	@echo "========================================="
	@echo ""
	@echo "===== UNIT TESTS (all groups) ====="
	@PYTHONPATH=$(shell pwd) uv run pytest tests/test_01_concurrent_access_unit.py tests/test_02_deduplication_unit.py tests/test_03_user_repository_unit.py -v --tb=short
	@echo ""
	@echo "===== GROUP 1 (kindle@solreader.com) ====="
	@echo "Test 01 - API integration (non-expensive)"
	@PYTHONPATH=$(shell pwd) uv run pytest tests/test_01_api_integration.py -v --tb=short -m "not expensive"
	@echo ""
	@echo "Test 03 - Absolute navigation"
	@PYTHONPATH=$(shell pwd) uv run pytest tests/test_03_absolute_navigation.py -v --tb=short
	@echo ""
	@echo "Test 05 - Multi-user integration"
	@PYTHONPATH=$(shell pwd) uv run pytest tests/test_05_multi_user_integration.py -v --tb=short
	@echo ""
	@echo "===== GROUP 2 (sam@solreader.com) ====="
	@echo "Test 02 - Request deduplication (non-expensive)"
	@CI=true PYTHONPATH=$(shell pwd) uv run pytest tests/test_02_request_deduplication_integration.py -v --tb=short -m "not expensive"
	@echo ""
	@echo "Test 02 - Request deduplication (expensive - may fail)"
	@CI=true PYTHONPATH=$(shell pwd) uv run pytest tests/test_02_request_deduplication_integration.py -v --tb=short -m "expensive" || true
	@echo ""
	@echo "Test 04 - Concurrent requests"
	@PYTHONPATH=$(shell pwd) uv run python tests/test_04_concurrent_requests_integration.py
	@echo ""
	@echo "===== GROUP 3 (recreate@solreader.com) ====="
	@echo "Test 01 - API integration (expensive - recreate AVD)"
	@RECREATE_USER_EMAIL=recreate@solreader.com PYTHONPATH=$(shell pwd) uv run pytest tests/test_01_api_integration.py -v --tb=short -m "expensive"
	@echo ""
	@echo "========================================="
	@echo "All test groups completed!"
	@echo "========================================="

test-all: test

test-fast:
	@echo "Running tests with fail-fast (stops on first failure)..."
	@PYTHONPATH=$(shell pwd) uv run pytest tests -x -v

test-unit:
	@echo "Running all unit tests (no server required)..."
	@PYTHONPATH=$(shell pwd) uv run python -m pytest tests/test_01_concurrent_access_unit.py tests/test_02_deduplication_unit.py tests/test_03_user_repository_unit.py -v
	@echo "All unit tests passed!"

test-api:
	@echo "Running integration tests..."
	@PYTHONPATH=$(shell pwd) uv run python -m pytest tests/test_01_api_integration.py -v

test-dedupe:
	@echo "Running deduplication integration tests..."
	@PYTHONPATH=$(shell pwd) uv run python -m pytest tests/test_02_request_deduplication_integration.py -v

test-page:
	@echo "Running page navigation tests..."
	@PYTHONPATH=$(shell pwd) uv run python -m pytest tests/test_03_absolute_navigation.py -v

test-concurrent:
	@echo "Running concurrent HTTP requests tests..."
	@PYTHONPATH=$(shell pwd) uv run python tests/test_04_concurrent_requests_integration.py

test-user:
	@echo "Running multi-user integration tests..."
	@PYTHONPATH=$(shell pwd) uv run python -m pytest tests/test_05_multi_user_integration.py

# Test groups matching GitHub Actions integration groups
test-group1:
	@echo "===== GROUP 1 Tests (kindle@solreader.com) ====="
	@echo ""
	@echo "Running unit tests..."
	@PYTHONPATH=$(shell pwd) uv run pytest tests/test_01_concurrent_access_unit.py tests/test_02_deduplication_unit.py tests/test_03_user_repository_unit.py -v --tb=short
	@echo ""
	@echo "Running Test 01 - API integration (non-expensive)..."
	@TEST_USER_EMAIL=kindle@solreader.com PYTHONPATH=$(shell pwd) uv run pytest tests/test_01_api_integration.py -v --tb=short -m "not expensive"
	@echo ""
	@echo "Running Test 03 - Absolute navigation..."
	@TEST_USER_EMAIL=kindle@solreader.com PYTHONPATH=$(shell pwd) uv run pytest tests/test_03_absolute_navigation.py -v --tb=short
	@echo ""
	@echo ""
	@echo "===== GROUP 1 Tests Complete ====="

test-group2:
	@echo "===== GROUP 2 Tests (sam@solreader.com) ====="
	@echo ""
	@echo "Running Test 02 - Request deduplication (non-expensive)..."
	@CI=true TEST_USER_EMAIL=sam@solreader.com PYTHONPATH=$(shell pwd) uv run pytest tests/test_02_request_deduplication_integration.py -v --tb=short -m "not expensive"
	@echo ""
	@echo "Running Test 02 - Request deduplication (expensive - allowed to fail)..."
	@CI=true TEST_USER_EMAIL=sam@solreader.com PYTHONPATH=$(shell pwd) uv run pytest tests/test_02_request_deduplication_integration.py -v --tb=short -m "expensive" || true
	@echo ""
	@echo ""
	@echo "===== GROUP 2 Tests Complete ====="

test-group3:
	@echo "===== GROUP 3 Tests (recreate@solreader.com) ====="
	@echo ""
	@echo "Running Test 01 - API integration (expensive - recreate AVD)..."
	@TEST_USER_EMAIL=recreate@solreader.com RECREATE_USER_EMAIL=recreate@solreader.com PYTHONPATH=$(shell pwd) uv run pytest tests/test_01_api_integration.py -v --tb=short -m "expensive"
	@echo ""
	@echo "===== GROUP 3 Tests Complete ====="

test-group4:
	@echo "===== GROUP 4 Tests (Multi-user: kindle@ and sam@) ====="
	@echo "NOTE: Run AFTER groups 1 and 2 complete to avoid conflicts"
	@echo "Configured users: CONCURRENT_USER_A=kindle@solreader.com, CONCURRENT_USER_B=sam@solreader.com"
	@echo ""
	@echo "Running Test 04 - Concurrent requests (uses both users)..."
	@CONCURRENT_USER_A=kindle@solreader.com CONCURRENT_USER_B=sam@solreader.com PYTHONPATH=$(shell pwd) uv run python tests/test_04_concurrent_requests_integration.py
	@echo ""
	@echo "Running Test 05 - Multi-user integration (uses both users)..."
	@CONCURRENT_USER_A=kindle@solreader.com CONCURRENT_USER_B=sam@solreader.com PYTHONPATH=$(shell pwd) uv run pytest tests/test_05_multi_user_integration.py -v --tb=short
	@echo ""
	@echo "===== GROUP 4 Tests Complete ====="

# Generate staff authentication token for testing
test-staff-auth:
	@echo "Generating staff authentication token..."
	@TOKEN=$$(curl -s http://localhost:4098/staff-auth?auth=true -c - | grep staff_token | awk '{print $$7}'); \
	if [ -n "$$TOKEN" ]; then \
		echo "Staff token generated: $$TOKEN"; \
		echo "Add to .env: INTEGRATION_TEST_STAFF_AUTH_TOKEN=$$TOKEN"; \
	else \
		echo "Failed to generate staff token"; \
		echo "Make sure the Flask server is running: make server"; \
		exit 1; \
	fi

# Generate web authentication token for testing  
test-web-auth:
	@echo "Generating Knox authentication token for samuel@ofbrooklyn.com..."
	@cd ../web-app && TOKEN=$$(docker exec sol_web ./manage.py generate_dev_knox_token samuel@ofbrooklyn.com | grep "Knox token generated:" | awk '{print $$4}'); \
	if [ -n "$$TOKEN" ]; then \
		echo "Knox token generated: $$TOKEN"; \
		echo "Add to .env: WEB_INTEGRATION_TEST_AUTH_TOKEN=$$TOKEN"; \
	else \
		echo "Failed to generate Knox token"; \
		echo "Make sure the web-app Docker container is running"; \
		exit 1; \
	fi

# Ansible

provision:
	ansible-playbook ansible/provision.yml
deploy:
	ansible-playbook ansible/deploy.yml
staging:
	ansible-playbook ansible/deploy.yml -l staging
env:
	ansible-playbook ansible/provision.yml -t env

# SSH

ssh: ssh-3

ssh-1:
	ssh -i ansible/keys/kindle.key root@157.180.51.112
ssh1: ssh-1
ssh-3:
	ssh -i ansible/keys/kindle.key root@157.180.14.166
ssh3: ssh-3
ssh-staging:
	ssh -i ansible/keys/kindle.key root@65.108.197.86
staging-ssh: ssh-staging
ssh-db:
	ssh -i ansible/keys/kindle.key root@46.62.136.6

# Firewall management
firewall:
	@echo "Updating firewall rules on all servers..."
	cd ansible && ansible-playbook -i inventory.ini provision.yml -t firewall
	@echo "Firewall rules updated successfully!"

# Include database commands
include Makefile.database

# Auto-detect environment file
ENV_FILE := $(shell if [ -f .env ]; then echo .env; elif [ -f .env.staging ]; then echo .env.staging; elif [ -f .env.prod ]; then echo .env.prod; else echo .env; fi)

# Display VNC instances table (auto-detects environment)
db-vnc:
	@uv run dotenv -f $(ENV_FILE) run python scripts/show_vnc_table.py

# Audit VNC instances and clean up stale emulator IDs (only affects THIS server)
db-audit:
	@echo "Running VNC instance audit (will clean stale entries on THIS server)..."
	@uv run dotenv -f $(ENV_FILE) run python scripts/audit_vnc.py

# Dry run audit - shows what would be cleaned without making changes
db-audit-dry:
	@echo "Running VNC instance audit in dry run mode (no changes will be made)..."
	@uv run dotenv -f $(ENV_FILE) run python scripts/audit_vnc.py --dry

# Export database to JSON format (auto-detects environment)
db-export:
	@echo "Exporting users from database to JSON format..."
	@uv run dotenv -f $(ENV_FILE) run python scripts/export_users_to_json.py

# db-stats and db-data are defined in Makefile.database
