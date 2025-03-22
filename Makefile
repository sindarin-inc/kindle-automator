.PHONY: server

run: server

deps:
	uv pip install -r requirements.txt

reinstall:
	uv run automator.py --reinstall

lint:
# workon kindle-automator
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

ssh-x86:
	ssh -i ansible/keys/kindle.key root@143.110.225.212
ssh-x86-2:
	ssh -i ansible/keys/kindle.key root@164.92.64.106
ssh-x86-3:
	ssh -i ansible/keys/kindle.key root@157.180.38.126
ssh-x86-4:
	ssh -i ansible/keys/kindle.key root@65.108.97.170
	
# Start the Flask server
server:
	@echo "Starting Flask server..."
	@FLASK_ENV=development PYTHONPATH=$(shell pwd) python -m server.server

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
	@-kill $$(lsof -t -i:4098) 2>/dev/null || true
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
# -d '{"title": "Poor Charlie\u2019s Almanack: The Essential Wit and Wisdom of Charles T. Munger"}' \
# -d '{"title": "Guns, Germs, and Steel: The Fates of Human Societies (20th Anniversary Edition)"}' \
	@echo "Opening book..."
	@curl -X POST http://localhost:4098/open-book \
		-H "Content-Type: application/json" \
		-d '{"title": "The Design of Everyday Things: Revised and Expanded Edition"}' \
		-v

test-next-page:
	@echo "Navigating to next page..."
	@curl -X POST http://localhost:4098/navigate \
		-H "Content-Type: application/json" \
		-d '{"action": "next_page"}' \
		-v

test-prev-page: test-previous-page
test-previous-page:
	@echo "Navigating to previous page..."
	@curl -X POST http://localhost:4098/navigate \
		-H "Content-Type: application/json" \
		-d '{"action": "previous_page"}' \
		-v

# Test style endpoint
test-style:
	@echo "Updating style settings..."
	@curl -X POST http://localhost:4098/style \
		-H "Content-Type: application/json" \
		-d '{"settings": {"font_size": "large", "brightness": 80}, "dark-mode": true}' \
		-v

# Test style endpoint
test-style-light:
	@echo "Updating style settings to light mode..."
	@curl -X POST http://localhost:4098/style \
		-H "Content-Type: application/json" \
		-d '{"settings": {"font_size": "large", "brightness": 80}, "dark-mode": false}' \
		-v

# Test 2FA endpoint
test-2fa:
	@echo "Submitting 2FA code..."
	@curl -X POST http://localhost:4098/2fa \
		-H "Content-Type: application/json" \
		-d '{"code": "123456"}' \
		-v

# Test Captcha endpoint
test-captcha:
	@echo "Posting captcha solution..."
	@curl -X POST http://localhost:4098/captcha \
		-H "Content-Type: application/json" \
		-d '{"solution": "4s6cwm"}' \
		-v

# Test Auth endpoint
test-auth:
	@echo "Testing authentication..."
	@curl -X POST http://localhost:4098/auth \
		-H "Content-Type: application/json" \
		-d '{"email": "sam@solreader.com", "password": "JFK0epr!nwb5kjg1ekz"}' \
		-v

# Test books endpoint
test-books:
	@echo "Getting list of books..."
	@curl http://localhost:4098/books \
		-H "Accept: application/json" \
		-v

# Test fixtures endpoint to capture page source for major views
test-fixtures:
	@echo "Creating fixtures for major views..."
	@mkdir -p fixtures/views
	@curl -X POST http://localhost:4098/fixtures \
		-H "Content-Type: application/json" \
		-v
