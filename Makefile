.PHONY: run deps reinstall lint server test-init kill-server test-navigate test-screenshot test-open-book test-style test-2fa test-books

run:
	uv run automator.py

deps:
	uv pip install -r requirements.txt

reinstall:
	uv run automator.py --reinstall

lint:
	workon kindle-automator
	isort --profile black .
	black --line-length 110 .
	flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=venv
	
# Ansible

provision:
	ansible-playbook ansible/provision.yml -l kindle-automator-2
provision-android:
	ansible-playbook ansible/provision.yml -t android -l kindle-automator-2
deploy:
	ansible-playbook ansible/deploy.yml

# SSH

ssh: ssh-arm64
ssh-x86:
	ssh -i ansible/keys/kindle.key root@kindle01.sindarin.com
ssh-arm64:
	ssh -i ansible/keys/kindle.key root@kindle.sindarin.com
ssh-2:
	ssh -i ansible/keys/kindle.key root@94.130.229.244

# Start the Flask server
server:
	@echo "Starting Flask server..."
	@python -m server.server

# Test initialization endpoint
test-init:
	@echo "Testing initialization endpoint..."
	@curl -X POST http://localhost:4098/initialize \
		-H "Content-Type: application/json" \
		-d '{"email": "test@example.com", "password": "test123"}' \
		-v

# Optional helper target to kill existing processes
kill-server:
	@echo "Killing existing server processes..."
	@pkill -f "python -m server.server" || true
	@pkill -f "appium" || true

# Test navigation endpoint
test-navigate:
	@echo "Testing page navigation..."
	@curl -X POST http://localhost:4098/navigate \
		-H "Content-Type: application/json" \
		-d '{"action": "next_page"}' \
		-v

# Test screenshot endpoint
test-screenshot:
	@echo "Getting current screenshot..."
	@curl http://localhost:4098/screenshot \
		-H "Accept: application/json" \
		-v

# Test open book endpoint
test-open-book:
	@echo "Opening book..."
	@curl -X POST http://localhost:4098/open-book \
		-H "Content-Type: application/json" \
		-d '{"title": "Sample Book Title"}' \
		-v

# Test style endpoint
test-style:
	@echo "Updating style settings..."
	@curl -X POST http://localhost:4098/style \
		-H "Content-Type: application/json" \
		-d '{"settings": {"font_size": "large", "brightness": 80}}' \
		-v

# Test 2FA endpoint
test-2fa:
	@echo "Submitting 2FA code..."
	@curl -X POST http://localhost:4098/2fa \
		-H "Content-Type: application/json" \
		-d '{"code": "123456"}' \
		-v

# Test books endpoint
test-books:
	@echo "Getting list of books..."
	@curl http://localhost:4098/books \
		-H "Accept: application/json" \
		-v
