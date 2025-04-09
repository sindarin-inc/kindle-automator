import os
import platform

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

# Default Android SDK path
DEFAULT_ANDROID_SDK = "/opt/android-sdk"
# Alternative for macOS
if platform.system() == "Darwin":
    DEFAULT_ANDROID_SDK = os.path.expanduser("~/Library/Android/sdk")

# Get Android SDK path from environment variable or use default
ANDROID_SDK_PATH = os.environ.get("ANDROID_HOME", DEFAULT_ANDROID_SDK)


# Detect host architecture
def get_host_architecture():
    machine = platform.machine().lower()

    if machine in ("arm64", "aarch64"):
        return "arm64"
    elif machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    else:
        return "unknown"


HOST_ARCHITECTURE = get_host_architecture()

# Running Approaches
EMULATOR_APPROACHES = {
    # For ARM Macs (M1/M2/M4)
    "arm64": [
        # Approach 1: Use ARM-native system image
        {
            "name": "arm64-native",
            "description": "ARM64 native emulation",
            "system_image": "system-images;android-30;google_apis;arm64-v8a",
            "avd_arch": "arm64-v8a",
            "command_prefix": [],
            "command_options": ["-gpu", "swiftshader", "-verbose"],
            "environment": {},
        },
        # Approach 2: Use x86_64 with arch translation
        {
            "name": "x86_64-rosetta",
            "description": "x86_64 with Rosetta 2 translation",
            "system_image": "system-images;android-30;google_apis;x86_64",
            "avd_arch": "x86_64",
            "command_prefix": ["arch", "-x86_64"],
            "command_options": ["-gpu", "swiftshader", "-verbose"],
            "environment": {},
        },
        # Approach 3: Use x86_64 with shell script
        {
            "name": "x86_64-shell",
            "description": "Shell wrapper for x86_64",
            "system_image": "system-images;android-30;google_apis;x86_64",
            "avd_arch": "x86_64",
            "command_prefix": ["arch", "-x86_64", "sh", "-c"],
            "shell_command": True,
            "environment": {},
        },
    ],
    # For x86_64 machines (cloud servers, Intel Macs)
    "x86_64": [
        # Just one straightforward approach
        {
            "name": "x86_64-native",
            "description": "Native x86_64 emulation",
            "system_image": "system-images;android-30;google_apis_playstore;x86_64",
            "avd_arch": "x86_64",
            "command_options": [
                "-gpu",
                "swiftshader_indirect",
                "-accel",
                "on",
                "-feature",
                "KVM",  # Will be ignored on non-Linux
            ],
            "environment": {},
        }
    ],
}

# Determine available approaches based on host architecture
AVAILABLE_APPROACHES = EMULATOR_APPROACHES.get(HOST_ARCHITECTURE, EMULATOR_APPROACHES["x86_64"])
