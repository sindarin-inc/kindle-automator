#!/bin/bash
set -e

echo "Generating new authentication tokens..."

# Generate new Django session
SESSION_ID=$(docker exec -t sol_web ./manage.py generate_dev_session 2>/dev/null | grep "Session ID:" | awk '{print $3}' | sed 's/\x1b\[[0-9;]*m//g' | tr -d '\r')

if [ -z "$SESSION_ID" ]; then
    echo "Failed to generate session ID. Make sure Docker containers are running."
    echo "Run: cd ../web-app && make fast"
    exit 1
fi

echo "Generated session ID: $SESSION_ID"

# Get staff token from cookie
curl -s -c /tmp/auth_cookies.txt -o /tmp/auth_response.txt \
    -H "Cookie: sessionid=$SESSION_ID" \
    "http://localhost:4096/kindle/staff-auth?auth=1"

STAFF_TOKEN=$(grep staff_token /tmp/auth_cookies.txt 2>/dev/null | awk '{print $7}')

if [ -z "$STAFF_TOKEN" ]; then
    echo "Failed to get staff token"
    cat /tmp/auth_response.txt
    exit 1
fi

echo "Generated staff token: $STAFF_TOKEN"

# Generate a proper Knox token using Django management command
KNOX_TOKEN=$(cd ../web-app && docker exec sol_web ./manage.py generate_dev_knox_token sam@solreader.com 2>/dev/null | grep "Knox token generated:" | awk '{print $4}')

if [ -z "$KNOX_TOKEN" ]; then
    echo "Failed to get Knox token"
    echo "Make sure the web-app Docker container is running"
    exit 1
fi

echo "Generated Knox token: $KNOX_TOKEN"

# Write to .env.auth file
cat > .env.auth << EOF
# Local authentication tokens for testing
# Generated automatically - run 'make refresh-auth' to regenerate

# Staff auth token for Kindle automator
export INTEGRATION_TEST_STAFF_AUTH_TOKEN="$STAFF_TOKEN"

# Knox token for web integration tests
export WEB_INTEGRATION_TEST_AUTH_TOKEN="$KNOX_TOKEN"

# Django session ID (optional, for direct proxy server requests)
export DEV_SESSION_ID="$SESSION_ID"
EOF

echo ""
echo "✅ Authentication tokens saved to .env.auth"
echo ""
echo "Tokens are automatically loaded when running:"
echo "  - make test"
echo "  - uv run pytest ..."
echo "  - Any make command that needs auth"

rm -f /tmp/auth_cookies.txt /tmp/auth_response.txt