"""
Test script for request/response logging middleware.
"""
import json
import logging

from flask import Flask, request, jsonify

from server.request_logger import setup_request_logger

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s [%(asctime)s] %(name)s: %(message)s',
)

logger = logging.getLogger(__name__)

# Create a simple Flask app
app = Flask(__name__)

# Set up request and response logging middleware
setup_request_logger(app)

@app.route('/test_get', methods=['GET'])
def test_get():
    """Test GET endpoint."""
    return jsonify({
        "status": "success",
        "method": "GET",
        "query_params": dict(request.args),
    })

@app.route('/test_post', methods=['POST'])
def test_post():
    """Test POST endpoint."""
    # Get the request body
    data = request.get_json()
    
    # Return a response
    return jsonify({
        "status": "success",
        "method": "POST",
        "received_data": data,
        "sensitive_field": "sensitive_info_in_response"
    })

@app.route('/test_auth', methods=['POST'])
def test_auth():
    """Test endpoint with authentication."""
    # Get the request body
    data = request.get_json()
    
    # Return a response
    if data.get('email') == 'test@example.com' and data.get('password') == 'password123':
        return jsonify({
            "status": "success",
            "auth": "successful",
            "token": "secret_token_123"
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Invalid credentials"
        }), 401

if __name__ == '__main__':
    logger.info("Starting test server...")
    app.run(host='0.0.0.0', port=5000)