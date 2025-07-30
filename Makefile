.PHONY: server test

run: server

claude-run: 
	@echo "Starting Flask server in background..."
	@bash -c '(FLASK_ENV=development PYTHONPATH=$$(pwd) uv run python -m server.server > logs/server_output.log 2>&1 & echo $$! > logs/server.pid) &'
	@sleep 1
	@echo "Server started with PID $$(cat logs/server.pid)"
	@echo "Monitor logs with: tail -f logs/server_output.log"
	@echo "To stop the server and start a new server, run: make claude-run"

deps:
	uv pip install -r requirements.txt

lint:
	uv run isort --profile black .
	uv run black --line-length 110 .
	uv run flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=venv
	
# Start the Flask server
server:
	@echo "Starting Flask server..."
	@FLASK_ENV=development PYTHONPATH=$(shell pwd) uv run python -m server.server

# Start an interactive shell with the environment setup
shell:
	@echo "Starting interactive shell..."
	@PYTHONPATH=$(shell pwd) uv run python shell.py

test:
	@echo "Running tests..."
	@PYTHONPATH=$(shell pwd) uv run pytest tests

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

# Export database to JSON format
db-export:
	@echo "Exporting users from database to JSON format..."
	@$(shell grep -E '^(DATABASE_URL|KINDLE_SCHEMA)=' .env | xargs) uv run python scripts/export_users_to_json.py

# Export from staging database
db-export-staging:
	@echo "Exporting users from staging database to JSON format..."
	@$(shell grep -E '^(DATABASE_URL|KINDLE_SCHEMA)=' .env.staging | xargs) uv run python scripts/export_users_to_json.py

# Export from production database
db-export-prod:
	@echo "Exporting users from production database to JSON format..."
	@$(shell grep -E '^(DATABASE_URL|KINDLE_SCHEMA)=' .env.prod | xargs) uv run python scripts/export_users_to_json.py
