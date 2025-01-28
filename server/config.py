import os

# Server settings
HOST = "0.0.0.0"
PORT = 4098

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")

# Create required directories
for directory in [LOGS_DIR, SCREENSHOTS_DIR]:
    os.makedirs(directory, exist_ok=True)

# Logging settings
LOG_FILE = os.path.join(LOGS_DIR, "server.log")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = "INFO"
