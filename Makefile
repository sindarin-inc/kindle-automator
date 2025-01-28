.PHONY: run deps reinstall lint

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
