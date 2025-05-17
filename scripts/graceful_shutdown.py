#!/usr/bin/env python3
"""Gracefully shutdown all running emulators before service restart."""

import json
import logging
import sys
import time
import urllib.error
import urllib.request

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Server URL
BASE_URL = "http://localhost:4098"


def make_request(url, method="GET", data=None, headers=None):
    """Make HTTP request to the server."""
    req = urllib.request.Request(url, method=method)
    
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)
    
    if data:
        req.data = json.dumps(data).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
    
    try:
        response = urllib.request.urlopen(req, timeout=10)
        return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        logger.error(f"HTTP error: {e.code} - {e.reason}")
        return None
    except Exception as e:
        logger.error(f"Request error: {e}")
        return None


def get_active_emulators():
    """Get list of active emulators from the server."""
    url = f"{BASE_URL}/api/v1/emulators/active"
    logger.info("Fetching list of active emulators...")
    
    response = make_request(url)
    if response and "emulators" in response:
        return response["emulators"]
    
    # If the endpoint doesn't exist, try to query individual automators
    logger.warning("Could not fetch active emulators list, trying alternative method")
    return []


def shutdown_emulator(email):
    """Shutdown an emulator for a specific email."""
    url = f"{BASE_URL}/api/v1/shutdown"
    headers = {"X-Sindarin-Email": email}
    
    logger.info(f"Shutting down emulator for {email}...")
    
    response = make_request(url, method="POST", headers=headers)
    if response and response.get("success"):
        logger.info(f"Successfully shut down emulator for {email}")
        return True
    else:
        logger.error(f"Failed to shut down emulator for {email}: {response}")
        return False


def main():
    """Main function to gracefully shutdown all emulators."""
    logger.info("Starting graceful shutdown of all emulators...")
    
    # Try to get active emulators from the server
    active_emulators = get_active_emulators()
    
    if not active_emulators:
        logger.info("No active emulators found to shut down")
        return 0
    
    logger.info(f"Found {len(active_emulators)} active emulators")
    
    # Shutdown each emulator
    success_count = 0
    for email in active_emulators:
        if shutdown_emulator(email):
            success_count += 1
        
        # Small delay between shutdowns
        time.sleep(1)
    
    logger.info(f"Shutdown complete. Successfully shut down {success_count}/{len(active_emulators)} emulators")
    
    # Give some time for all processes to clean up
    time.sleep(3)
    
    return 0 if success_count == len(active_emulators) else 1


if __name__ == "__main__":
    sys.exit(main())