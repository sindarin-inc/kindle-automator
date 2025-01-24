.PHONY: run

run:
	python automator.py

lint:
	workon kindle-automator
	isort --profile black .
	black --line-length 110 .
	flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=venv
	
# Ansible

provision:
	ansible-playbook ansible/provision.yml
provision-android:
	ansible-playbook ansible/provision.yml -t android
deploy:
	ansible-playbook ansible/deploy.yml

# SSH

ssh: ssh-kindle
ssh-kindle:
	ssh -i ansible/keys/kindle.key root@kindle01.sindarin.com
