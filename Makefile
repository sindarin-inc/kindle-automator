.PHONY: server profile-help register-avd

# Default email for testing - can be overridden with make test-books EMAIL=other@example.com
EMAIL ?= kindle@solreader.com

run: server

profile-help:
	@echo "Profile Management Commands:"
	@echo "  make profiles                         List all profiles"
	@echo "  make profile-create EMAIL=kindle@solreader.com      Create a new profile"
	@echo "  make profile-switch EMAIL=kindle@solreader.com      Switch to existing profile"
	@echo "  make profile-delete EMAIL=kindle@solreader.com      Delete a profile"
	@echo "  make auth EMAIL=kindle@solreader.com PASSWORD=pass  Authenticate with a profile"
	@echo "  make run-emulator                               Run emulator for current profile"
	@echo "  make run-emulator-choose                        Run emulator (choose which AVD)"
	@echo "  make dev                                        Start both emulator and server"
	@echo "  make register-avd                               Register an AVD created in Android Studio"
	@echo "  make android-studio-avd                         Full workflow for Android Studio AVDs"
	@echo ""
	@echo "Testing Commands (current default EMAIL: $(EMAIL)):"
	@echo "  make test-books                       Get list of books (defaults to $(EMAIL))"
	@echo "  make test-books EMAIL=other@example.com         Override default email"

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
	
# User account switching

load-user1:
	@echo "Loading user1 account..."
	@curl -X POST http://localhost:4098/switch-user \
		-H "Content-Type: application/json" \
		-d '{"email": "sam@solreader.com"}' \
		-v

load-user2:
	@echo "Loading user2 account..."
	@curl -X POST http://localhost:4098/switch-user \
		-H "Content-Type: application/json" \
		-d '{"email": "samuel@ofbrooklyn.com"}' \
		-v
		
# Troubleshooting backup/restore
check-backups:
	@echo "Checking backup files..."
	@echo "User 1:"
	@ls -la user_data/sam@solreader.com/ || echo "User1 directory not found"
	@echo "User 2:"
	@ls -la user_data/samuel@ofbrooklyn.com/ || echo "User2 directory not found"
	@echo "Current device:"
	@adb devices
	
test-backup:
	@echo "Testing direct backup of Kindle app data..."
	@mkdir -p user_data/test-backup
	@adb backup -f user_data/test-backup/kindle_test.ab -all -shared com.amazon.kindle
	@echo "Backup complete. Check size:"
	@ls -la user_data/test-backup/
	
test-backup-list:
	@echo "Listing Kindle app packages on device..."
	@adb shell pm list packages | grep -i kindle
	
test-app-data:
	@echo "Checking Kindle app data on device..."
	@echo "App data directories:"
	@adb shell ls -la /data/data/com.amazon.kindle/ || echo "Cannot access app data (permissions)"
	@echo "External storage:"
	@adb shell ls -la /sdcard/Android/data/com.amazon.kindle/ || echo "No external storage data"
	@echo "App storage space usage:"
	@adb shell dumpsys package com.amazon.kindle | grep -A 5 "Package \\["
	
reset-user-data:
	@echo "Resetting user data for testing..."
	@adb root
	@adb shell am force-stop com.amazon.kindle
	@adb shell pm clear com.amazon.kindle
	@rm -rf user_data/sam@solreader.com user_data/samuel@ofbrooklyn.com
	@rm -f user_data/users_index.json
	@mkdir -p user_data/sam@solreader.com/direct_backup user_data/samuel@ofbrooklyn.com/direct_backup
	@echo "User data reset complete"
	@echo "Now run 'make server' and login to create fresh account containers"
	
# Test the APK version checking functionality
test-apk-version:
	@echo "Testing APK version checking functionality..."
	@PYTHONPATH=$(shell pwd) python -m tests.test_apk_version
	
# List the APK files available
list-apks:
	@echo "Available Kindle APK files:"
	@find ansible/roles/android_*/files -name "*.apk" -type f | sed 's/.*\///'
	
# Ansible

provision:
	ansible-playbook ansible/provision.yml
provision-android:
	ansible-playbook ansible/provision.yml -t android
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

# Start the Flask server
server:
	@echo "Starting Flask server..."
	@FLASK_ENV=development PYTHONPATH=$(shell pwd) python -m server.server

# Start an interactive shell with the environment setup
shell:
	@echo "Starting interactive shell..."
	@PYTHONPATH=$(shell pwd) python shell.py

# Test initialization endpoint
test-init:
	@echo "Testing initialization endpoint..."
	@curl -X POST http://localhost:4098/initialize \
		-H "Content-Type: application/json" \
		-d '{"email": "test@example.com", "password": "test123"}' \
		-v

# Optional helper target to kill existing server processes (not the emulator)
kill-server:
	@echo "Killing existing server processes (preserving emulator)..."
	@-kill $$(lsof -t -i:4098) 2>/dev/null || true
	@pkill -f "appium" || true

# Test navigation endpoint
test-navigate:
	@echo "Testing page navigation..."
	@curl -X POST http://localhost:4098/navigate \
		-H "Content-Type: application/json" \
		-d '{"action": "next_page", "sindarin_email": "$(EMAIL)"}' \
		-v

# Test screenshot endpoint
test-screenshot:
	@echo "Getting current screenshot..."
	@curl http://localhost:4098/screenshot?sindarin_email=$(EMAIL) \
		-H "Accept: application/json" \
		-v

# Test open book endpoint
test-open-book:
# -d '{"title": "Poor Charlie\u2019s Almanack: The Essential Wit and Wisdom of Charles T. Munger"}' \
# -d '{"title": "Guns, Germs, and Steel: The Fates of Human Societies (20th Anniversary Edition)"}' \
	@echo "Opening book..."
	@curl -X POST http://localhost:4098/open-book \
		-H "Content-Type: application/json" \
		-d '{"title": "The Design of Everyday Things: Revised and Expanded Edition", "sindarin_email": "$(EMAIL)"}' \
		-v

test-next-page:
	@echo "Navigating to next page..."
	@curl -X POST http://localhost:4098/navigate \
		-H "Content-Type: application/json" \
		-d '{"action": "next_page", "sindarin_email": "$(EMAIL)"}' \
		-v

test-prev-page: test-previous-page
test-previous-page:
	@echo "Navigating to previous page..."
	@curl -X POST http://localhost:4098/navigate \
		-H "Content-Type: application/json" \
		-d '{"action": "previous_page", "sindarin_email": "$(EMAIL)"}' \
		-v

# Test style endpoint
test-style:
	@echo "Updating style settings..."
	@curl -X POST http://localhost:4098/style \
		-H "Content-Type: application/json" \
		-d '{"settings": {"font_size": "large", "brightness": 80}, "dark-mode": true, "sindarin_email": "$(EMAIL)"}' \
		-v

# Test style endpoint
test-style-light:
	@echo "Updating style settings to light mode..."
	@curl -X POST http://localhost:4098/style \
		-H "Content-Type: application/json" \
		-d '{"settings": {"font_size": "large", "brightness": 80}, "dark-mode": false, "sindarin_email": "$(EMAIL)"}' \
		-v

# Test 2FA endpoint
test-2fa:
	@echo "Submitting 2FA code..."
	@curl -X POST http://localhost:4098/2fa \
		-H "Content-Type: application/json" \
		-d '{"code": "123456", "sindarin_email": "$(EMAIL)"}' \
		-v

# Test Captcha endpoint
test-captcha:
	@echo "Posting captcha solution..."
	@curl -X POST http://localhost:4098/captcha \
		-H "Content-Type: application/json" \
		-d '{"solution": "4s6cwm", "sindarin_email": "$(EMAIL)"}' \
		-v

# Test Auth endpoint
test-auth:
	@echo "Testing authentication..."
	@curl -X POST http://localhost:4098/auth \
		-H "Content-Type: application/json" \
		-d '{"email": "$(EMAIL)", "password": "$(PASSWORD)"}' \
		-v
		
# Test Auth with recreate
test-auth-recreate:
	@echo "Testing authentication with profile recreation..."
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make test-auth-recreate EMAIL=kindle@solreader.com PASSWORD=yourpassword" && exit 1)
	@[ -n "$(PASSWORD)" ] || (echo "ERROR: PASSWORD parameter required. Usage: make test-auth-recreate EMAIL=kindle@solreader.com PASSWORD=yourpassword" && exit 1)
	@curl -X POST http://localhost:4098/auth \
		-H "Content-Type: application/json" \
		-d '{"email": "$(EMAIL)", "password": "$(PASSWORD)", "recreate": true}' \
		-v

# Test auth endpoint without auth credentials (for manual VNC authentication)
test-no-auth:
	@echo "Authenticating (no auth credentials, manual VNC auth)..."
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make test-no-auth EMAIL=kindle@solreader.com" && exit 1)
	@curl http://localhost:4098/books?sindarin_email=$(EMAIL) \
		-H "Accept: application/json" \
		-v

# Test books endpoint
test-books:
	@echo "Getting list of books..."
	@curl http://localhost:4098/books?sindarin_email=$(EMAIL) \
		-H "Accept: application/json" \
		-v

# Test fixtures endpoint to capture page source for major views
test-fixtures:
	@echo "Creating fixtures for major views..."
	@mkdir -p fixtures/views
	@curl -X POST http://localhost:4098/fixtures \
		-H "Content-Type: application/json" \
		-d '{"sindarin_email": "$(EMAIL)"}' \
		-v

# Test secure screenshot (auth screen)
test-secure-screenshot:
	@echo "Testing secure screenshot on auth screen..."
	@curl http://localhost:4098/screenshot?sindarin_email=$(EMAIL) \
		-H "Accept: application/json" \
		-v

# Profile management commands
profiles:
	@echo "Listing all profiles..."
	@curl -s http://localhost:4098/profiles | jq

profile-create:
	@echo "Creating profile for email: $(EMAIL)"
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make profile-create EMAIL=kindle@solreader.com" && exit 1)
	@curl -X POST http://localhost:4098/profiles \
		-H "Content-Type: application/json" \
		-d '{"action": "create", "email": "$(EMAIL)"}' | jq

profile-switch:
	@echo "Switching to profile for email: $(EMAIL)"
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make profile-switch EMAIL=kindle@solreader.com" && exit 1)
	@curl -X POST http://localhost:4098/profiles \
		-H "Content-Type: application/json" \
		-d '{"action": "switch", "email": "$(EMAIL)"}' | jq

profile-delete:
	@echo "Deleting profile for email: $(EMAIL)"
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make profile-delete EMAIL=kindle@solreader.com" && exit 1)
	@curl -X POST http://localhost:4098/profiles \
		-H "Content-Type: application/json" \
		-d '{"action": "delete", "email": "$(EMAIL)"}' | jq

# Auth with profile
auth:
	@echo "Authenticating with email: $(EMAIL) and password: $(PASSWORD)"
	@[ -n "$(EMAIL)" ] || (echo "ERROR: EMAIL parameter required. Usage: make auth EMAIL=kindle@solreader.com PASSWORD=yourpassword" && exit 1)
	@[ -n "$(PASSWORD)" ] || (echo "ERROR: PASSWORD parameter required. Usage: make auth EMAIL=kindle@solreader.com PASSWORD=yourpassword" && exit 1)
	@curl -X POST http://localhost:4098/auth \
		-H "Content-Type: application/json" \
		-d '{"email": "$(EMAIL)", "password": "$(PASSWORD)"}' | jq
