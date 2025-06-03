.PHONY: server test

run: server

deps:
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

ssh:
	ssh -i ansible/keys/kindle.key root@65.108.97.170
ssh-staging:
	ssh -i ansible/keys/kindle.key root@65.108.197.86
staging-ssh: ssh-staging
