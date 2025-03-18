# Request/Response Logging Middleware

This middleware logs the request and response bodies for all API calls. It's useful for debugging and troubleshooting API interactions.

## Features

- Logs both request and response bodies for all HTTP requests
- Limits logged data to 500 bytes to prevent excessively long log entries
- Sanitizes sensitive information (passwords, tokens, etc.)
- Formats JSON data for readability
- Handles various content types (JSON, form data, binary data)
- Provides request method and path context for each log

## How It Works

The middleware hooks into Flask's request lifecycle:

1. **Before Request**: Captures and logs the incoming request body
2. **After Request**: Captures and logs the outgoing response body

## Usage

The middleware is already set up in the main server.py file. All requests and responses will be automatically logged.

### Example Log Output

```
INFO [2025-03-18 10:15:30] server.request_logger: REQUEST [POST /auth]: {"email": "[REDACTED]", "password": "[REDACTED]"}
INFO [2025-03-18 10:15:31] server.request_logger: RESPONSE [POST /auth]: {"status": "success", "message": "Authentication successful", "token": "[REDACTED]", "time_taken": 0.532}

# For large responses:
INFO [2025-03-18 10:15:31] server.request_logger: RESPONSE [POST /books]: {"books":[{"title":"Book 1","author":"Author 1"},{"title":"Book 2","author":"Author 2"},...]}... (truncated, total 2345 bytes)
```

## Testing

A test script is provided to verify the middleware functionality:

```
python test_middleware.py
```

Then use curl or a similar tool to make requests:

```
curl -X POST -H "Content-Type: application/json" -d '{"email":"test@example.com","password":"secret123"}' http://localhost:5000/test_auth
```

## Security Considerations

The middleware automatically redacts sensitive information like:
- Passwords
- Email addresses
- Authentication tokens
- API keys
- Other credentials

This ensures that sensitive data doesn't appear in log files.