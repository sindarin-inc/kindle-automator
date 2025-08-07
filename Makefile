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
	@bash -c '(NO_COLOR_CONSOLE=1 FLASK_ENV=development PYTHONPATH=$$(pwd) uv run dotenv run python -m server.server > logs/server_output.log 2>&1 & echo $$! > logs/server.pid) &'
	@sleep 1
	@echo "Server started with PID $$(cat logs/server.pid)"
	@echo "Waiting for session restoration to complete..."
	@# Wait for session restoration to complete (with timeout of 120 seconds)
	@timeout=120; \
	elapsed=0; \
	while [ $$elapsed -lt $$timeout ]; do \
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
	@FLASK_ENV=development PYTHONPATH=$(shell pwd) uv run dotenv run python -m server.server

# Start an interactive shell with the environment setup
shell:
	@echo "Starting interactive shell..."
	@PYTHONPATH=$(shell pwd) uv run dotenv run python shell.py

test:
	@echo "Running tests..."
	@PYTHONPATH=$(shell pwd) uv run dotenv run pytest tests

test-all: test

test-dedup:
	@echo "Running deduplication tests..."
	@PYTHONPATH=$(shell pwd) uv run python -m pytest tests/test_request_deduplication.py -v

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

# Export database to JSON format (auto-detects environment)
db-export:
	@echo "Exporting users from database to JSON format..."
	@uv run dotenv -f $(ENV_FILE) run python scripts/export_users_to_json.py

# db-stats and db-data are defined in Makefile.database

# Test multi-user operations
test-multi-user:
	@echo "Running multi-user test..."
	@echo "Make sure the server is running with 'make claude-run' first!"
	@echo ""
	uv run dotenv run python tests/test_multi_user.py
