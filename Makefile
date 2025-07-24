.PHONY: server test

run: server

claude-run: 
	@echo "Starting Flask server in background..."
	@bash -c 'source ~/.virtualenvs/kindle-automator/bin/activate && (FLASK_ENV=development PYTHONPATH=$$(pwd) python -m server.server > logs/server_output.log 2>&1 & echo $$! > logs/server.pid) &'
	@sleep 1
	@echo "Server started with PID $$(cat logs/server.pid)"
	@echo "Monitor logs with: tail -f logs/server_output.log"

deps:
	@if [ -z "$$VIRTUAL_ENV" ]; then \
		echo "ERROR: You must be in a virtualenv to run 'make deps'"; \
		echo "Run: source ~/.virtualenvs/kindle-automator/bin/activate"; \
		exit 1; \
	fi
	uv pip install -r requirements.txt

lint:
    # workon kindle-automator
	isort --profile black .
	black --line-length 110 .
	flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=venv
	
# Start the Flask server
server:
	@echo "Starting Flask server..."
	@FLASK_ENV=development PYTHONPATH=$(shell pwd) python -m server.server

# Start an interactive shell with the environment setup
shell:
	@echo "Starting interactive shell..."
	@PYTHONPATH=$(shell pwd) python shell.py

test:
	# workon kindle-automator
	@echo "Running tests..."
	@PYTHONPATH=$(shell pwd) pytest tests

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

# Include database commands
include Makefile.database

# Export database to JSON format
db-export:
	@echo "Exporting users from database to JSON format..."
	@source ~/.virtualenvs/kindle-automator/bin/activate && \
		$(shell grep -E '^(DATABASE_URL|KINDLE_SCHEMA)=' .env | xargs) python scripts/export_users_to_json.py

# Export from staging database
db-export-staging:
	@echo "Exporting users from staging database to JSON format..."
	@source ~/.virtualenvs/kindle-automator/bin/activate && \
		$(shell grep -E '^(DATABASE_URL|KINDLE_SCHEMA)=' .env.staging | xargs) python scripts/export_users_to_json.py

# Export from production database
db-export-prod:
	@echo "Exporting users from production database to JSON format..."
	@source ~/.virtualenvs/kindle-automator/bin/activate && \
		$(shell grep -E '^(DATABASE_URL|KINDLE_SCHEMA)=' .env.prod | xargs) python scripts/export_users_to_json.py
