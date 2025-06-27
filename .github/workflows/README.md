# GitHub Actions Workflows

This directory contains GitHub Actions workflows for the Kindle Automator project.

## Workflows

### ci.yml
- **Trigger**: Push to main/develop branches, PRs to main
- **Purpose**: Continuous Integration - runs linting (isort, black, flake8) and tests
- **Uses**: uv for fast Python package management

### deploy.yml
- **Trigger**: Push to main branch or manual workflow dispatch
- **Purpose**: Deploy the application using Ansible
- **Environments**: Production (65.108.97.170) and Staging (65.108.197.86)
- **Requires**: `DEPLOY_SSH_KEY` secret

### api-tests.yml
- **Trigger**: Manual workflow dispatch
- **Purpose**: Run API endpoint tests against deployed instances
- **Test Types**: init, auth, books, navigate, style, fixtures
- **Requires**: `TEST_EMAIL`, `TEST_PASSWORD`, and optionally `SERVER_URL` secrets

### ansible-check.yml
- **Trigger**: Changes to ansible/ directory
- **Purpose**: Validate Ansible playbooks syntax and run ansible-lint
- **Checks**: provision.yml and deploy.yml playbooks

### dependency-check.yml
- **Trigger**: Weekly (Mondays at 9 AM UTC) or manual
- **Purpose**: Check for outdated packages and security vulnerabilities
- **Tools**: uv pip list, pip-audit

### claude.yml
- **Trigger**: GitHub comments/issues mentioning @claude
- **Purpose**: Integrate with Claude AI for code assistance
- **Requires**: `ANTHROPIC_API_KEY` secret

## Required Secrets

Configure these in your repository settings under Secrets and variables > Actions:

- `DEPLOY_SSH_KEY`: SSH private key for deployment (contents of ansible/keys/kindle.key)
- `TEST_EMAIL`: Email for API testing (e.g., kindle@solreader.com)
- `TEST_PASSWORD`: Password for API testing
- `SERVER_URL`: (Optional) Override default server URL for API tests
- `ANTHROPIC_API_KEY`: API key for Claude AI integration