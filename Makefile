.PHONY: server profile-help register-avd

run: server

profile-help:
	@echo "Profile Management Commands:"
	@echo "  make profiles                         List all profiles"
	@echo "  make profile-create EMAIL=user@example.com      Create a new profile"
	@echo "  make profile-switch EMAIL=user@example.com      Switch to existing profile"
	@echo "  make profile-delete EMAIL=user@example.com      Delete a profile"
	@echo "  make auth EMAIL=user@example.com PASSWORD=pass  Authenticate with a profile"
	@echo "  make run-emulator                               Run emulator for current profile"
	@echo "  make run-emulator-choose                        Run emulator (choose which AVD)"
	@echo "  make dev                                        Start both emulator and server"
	@echo "  make register-avd                               Register an AVD created in Android Studio"
	@echo "  make android-studio-avd                         Full workflow for Android Studio AVDs"

# Register an AVD created in Android Studio with a profile
register-avd:
	@echo "Registering an AVD created in Android Studio..."
	@python3 tools/register_avd.py

# Complete workflow for using Android Studio AVDs
android-studio-avd:
	@echo "Android Studio AVD Setup Workflow:"
	@echo "This will register an AVD you've created in Android Studio with Kindle Automator"
	@echo ""
	@echo "1. Make sure your AVD is already created in Android Studio"
	@echo "2. Make sure your AVD is currently running in Android Studio"
	@echo ""
	@echo "Starting registration process..."
	@python3 tools/register_avd.py --current

run-emulator:
	@echo "Running Android emulator for current profile..."
	@python3 tools/run_emulator.py --current

run-emulator-choose:
	@echo "Running Android emulator (choose which AVD to start)..."
	@python3 tools/run_emulator.py
	
# Start both the emulator and server (for development)
dev:
	@echo "Starting both emulator and server for development..."
	@echo "Starting emulator for current profile..."
	@nohup python3 tools/run_emulator.py --current > logs/emulator.log 2>&1 &
	@echo "Starting server..."
	@make server
	@echo "  make install-android-images                     Install necessary Android system images"

install-android-images:
	@echo "Installing Android system images needed for Kindle Automator..."
	@echo "This may take a few minutes..."
	@echo "Detecting host architecture..."
	@ARCH=$$(uname -m); \
	if [ "$$ARCH" = "arm64" ] || [ "$$ARCH" = "aarch64" ]; then \
		echo "Detected ARM64 architecture (M1/M2/M4 Mac)"; \
		echo "Installing both ARM64 and x86_64 images (with ARM translation)"; \
		echo "y" | $(ANDROID_HOME)/cmdline-tools/latest/bin/sdkmanager --install "system-images;android-30;google_apis_playstore;x86_64"; \
		echo "y" | $(ANDROID_HOME)/cmdline-tools/latest/bin/sdkmanager --install "system-images;android-30;google_apis;x86_64"; \
		echo "y" | $(ANDROID_HOME)/cmdline-tools/latest/bin/sdkmanager --install "system-images;android-30;google_apis;arm64-v8a"; \
	else \
		echo "Detected x86_64 architecture"; \
		echo "Installing x86_64 images"; \
		echo "y" | $(ANDROID_HOME)/cmdline-tools/latest/bin/sdkmanager --install "system-images;android-30;google_apis_playstore;x86_64"; \
		echo "y" | $(ANDROID_HOME)/cmdline-tools/latest/bin/sdkmanager --install "system-images;android-30;google_apis;x86_64"; \
	fi
	@echo "Accepting licenses..."
	@yes | $(ANDROID_HOME)/cmdline-tools/latest/bin/sdkmanager --licenses
	@echo "Android system images installed successfully!"

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

ssh:
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

# Test secure screenshot (auth screen)
test-secure-screenshot:
	@echo "Testing secure screenshot on auth screen..."
	@curl http://localhost:4098/screenshot \
		-H "Accept: application/json" \
		-v

# Profile management commands
profiles:
	@echo "Listing all profiles..."
	@curl -s http://localhost:4098/profiles | jq

profile-create:
	@echo "Creating profile for email: $(EMAIL)"
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make profile-create EMAIL=user@example.com" && exit 1)
	@curl -X POST http://localhost:4098/profiles \
		-H "Content-Type: application/json" \
		-d '{"action": "create", "email": "$(EMAIL)"}' | jq

profile-switch:
	@echo "Switching to profile for email: $(EMAIL)"
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make profile-switch EMAIL=user@example.com" && exit 1)
	@curl -X POST http://localhost:4098/profiles \
		-H "Content-Type: application/json" \
		-d '{"action": "switch", "email": "$(EMAIL)"}' | jq

profile-delete:
	@echo "Deleting profile for email: $(EMAIL)"
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make profile-delete EMAIL=user@example.com" && exit 1)
	@curl -X POST http://localhost:4098/profiles \
		-H "Content-Type: application/json" \
		-d '{"action": "delete", "email": "$(EMAIL)"}' | jq

# Auth with profile
auth:
	@echo "Authenticating with email: $(EMAIL) and password: $(PASSWORD)"
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make auth EMAIL=user@example.com PASSWORD=yourpassword" && exit 1)
	@[ -n "$(PASSWORD)" ] || (echo "ERROR: PASSWORD parameter required. Usage: make auth EMAIL=user@example.com PASSWORD=yourpassword" && exit 1)
	@curl -X POST http://localhost:4098/auth \
		-H "Content-Type: application/json" \
		-d '{"email": "$(EMAIL)", "password": "$(PASSWORD)"}' | jq
