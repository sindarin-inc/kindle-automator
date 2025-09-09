#!/bin/bash

# Source the auth tokens
if [ -f .env.auth ]; then
    source .env.auth
else
    echo "❌ .env.auth file not found!"
    echo "Run: make refresh-auth"
    exit 1
fi

# Check if tokens are set
if [ -z "$INTEGRATION_TEST_STAFF_AUTH_TOKEN" ] || [ -z "$WEB_INTEGRATION_TEST_AUTH_TOKEN" ]; then
    echo "❌ Authentication tokens not found in .env.auth!"
    echo "Run: make refresh-auth"
    exit 1
fi

echo "Testing authentication tokens..."

# Test the tokens
RESPONSE=$(curl -s -o /tmp/auth_test_response.txt -w "%{http_code}" \
    -H "Authorization: Tolkien $WEB_INTEGRATION_TEST_AUTH_TOKEN" \
    -H "Cookie: staff_token=$INTEGRATION_TEST_STAFF_AUTH_TOKEN" \
    "http://localhost:4096/kindle/emulators/active?user_email=kindle@solreader.com")

if [ "$RESPONSE" = "200" ]; then
    echo "✅ Authentication tokens are working!"
    echo ""
    echo "INTEGRATION_TEST_STAFF_AUTH_TOKEN=$INTEGRATION_TEST_STAFF_AUTH_TOKEN"
    echo "WEB_INTEGRATION_TEST_AUTH_TOKEN=${WEB_INTEGRATION_TEST_AUTH_TOKEN:0:40}..."
    if [ -n "$DEV_SESSION_ID" ]; then
        echo "DEV_SESSION_ID=$DEV_SESSION_ID"
    fi
    rm -f /tmp/auth_test_response.txt
    exit 0
else
    echo "❌ Authentication failed (HTTP $RESPONSE)"
    echo "Response: $(cat /tmp/auth_test_response.txt 2>/dev/null | head -10)"
    echo ""
    echo "Try running: make refresh-auth"
    rm -f /tmp/auth_test_response.txt
    exit 1
fi