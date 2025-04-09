#!/usr/bin/env python3
"""
This script patches the AVDProfileManager to support VNC display streaming.
It modifies the start_emulator method to use the VNC display when available.
"""

import os
import re
import shutil
import sys
from datetime import datetime

# Default path to the AVD profile manager
DEFAULT_PATH = "/opt/kindle-automator/views/core/avd_profile_manager.py"


def patch_avd_profile_manager(file_path=DEFAULT_PATH):
    """Patch the AVD profile manager to use VNC display for streaming."""

    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = f"{file_path}.{timestamp}.bak"
    shutil.copy2(file_path, backup_path)
    print(f"Created backup at {backup_path}")

    with open(file_path, "r") as f:
        content = f.read()

    # Find the start_emulator method
    pattern = r"def start_emulator\(self, avd_name: str\) -> bool:.*?# Set environment variables.*?env = os\.environ\.copy\(\)"
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print("Could not find the start_emulator method in the file.")
        return False

    # Original environment variables section
    original_env_section = match.group(0)

    # Modified section with VNC support
    modified_env_section = (
        original_env_section
        + """
        env["ANDROID_SDK_ROOT"] = self.android_home
        env["ANDROID_AVD_HOME"] = self.avd_dir
        env["ANDROID_HOME"] = self.android_home
        # Set DISPLAY for VNC
        env["DISPLAY"] = ":1"

        # Check if we're on a headless server with VNC
        vnc_launcher = "/usr/local/bin/vnc-emulator-launcher.sh"
        use_vnc = os.path.exists(vnc_launcher) and not self.is_macos"""
    )

    # Replace the original section with the modified one
    content = content.replace(original_env_section, modified_env_section)

    # Find the emulator command section
    pattern = r'# Build emulator command with architecture-specific options.*?if self\.host_arch == "arm64":'
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print("Could not find the emulator command section.")
        return False

    # Original command section start
    original_cmd_section = match.group(0)

    # Modified command section with VNC support
    modified_cmd_section = """# Build emulator command with architecture-specific options
        if use_vnc:
            # Use the VNC launcher script
            logger.info(f"Using VNC-enabled emulator launcher for AVD {avd_name}")
            emulator_cmd = [
                vnc_launcher,
                "-avd",
                avd_name,
                "-no-audio",
                "-writable-system",
                "-no-snapshot",
                "-no-snapshot-load",
                "-no-snapshot-save",
                "-port",
                "5554"
            ]
        elif self.host_arch == "arm64":"""

    # Replace the original section with the modified one
    content = content.replace(original_cmd_section, modified_cmd_section)

    # Find the successful boot section to add VNC notification
    pattern = r'logger\.info\(f"Emulator {expected_emulator_id} booted successfully"\)'
    if pattern in content:
        original_boot_msg = f'logger.info(f"Emulator {{expected_emulator_id}} booted successfully")'
        modified_boot_msg = (
            original_boot_msg
            + """
                        
                        # If we're using VNC, log the connection info
                        if use_vnc:
                            logger.info("VNC server is available for captcha solving")
                            logger.info("Connect to the server's IP address on port 5900 using any VNC client")"""
        )

        content = content.replace(original_boot_msg, modified_boot_msg)

    # Write the modified content back to the file
    with open(file_path, "w") as f:
        f.write(content)

    print(f"Successfully patched {file_path} with VNC support")
    return True


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    if patch_avd_profile_manager(path):
        print("Patch applied successfully.")
    else:
        print("Failed to apply patch.")
