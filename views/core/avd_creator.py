import logging
import os
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class AVDCreator:
    """
    Handles the creation and configuration of Android Virtual Devices (AVDs).
    """

    def __init__(self, android_home, avd_dir, host_arch):
        self.android_home = android_home
        self.avd_dir = avd_dir
        self.host_arch = host_arch

    def normalize_email_for_avd(self, email: str) -> str:
        """
        Normalize an email address to be used in an AVD name.

        Args:
            email: Email address to normalize

        Returns:
            str: Normalized email suitable for AVD name
        """
        return email.replace("@", "_").replace(".", "_")

    def get_avd_name_from_email(self, email: str) -> str:
        """
        Generate a standardized AVD name from an email address.

        Args:
            email: Email address

        Returns:
            str: Complete AVD name
        """
        email_formatted = self.normalize_email_for_avd(email)
        return f"KindleAVD_{email_formatted}"

    def get_compatible_system_image(self, available_images: List[str]) -> Optional[str]:
        """
        Get the most compatible system image based on host architecture.

        Args:
            available_images: List of available system images

        Returns:
            Optional[str]: Most compatible system image or None if not found
        """
        # Important: Even on ARM Macs (M1/M2/M4), we need to use x86_64 images
        # because the ARM64 emulation in Android emulator is not fully supported yet.
        # The emulator will use Rosetta 2 to translate x86_64 to ARM.

        # First choice: Android 30 with Google Play Store (x86_64)
        for img in available_images:
            if "system-images;android-30;google_apis_playstore;x86_64" in img:
                return img

        # Second choice: Android 30 with Google APIs (x86_64)
        for img in available_images:
            if "system-images;android-30;google_apis;x86_64" in img:
                return img

        # Third choice: Any Android 30 x86_64 image
        for img in available_images:
            if "system-images;android-30;" in img and "x86_64" in img:
                return img

        # Fourth choice: Any modern Android x86_64 image
        for img in available_images:
            if "x86_64" in img:
                return img

        # Fallback to any image
        if available_images:
            return available_images[0]

        return None

    def create_new_avd(self, email: str) -> Tuple[bool, str]:
        """
        Create a new AVD for the given email.

        Returns:
            Tuple[bool, str]: (success, avd_name)
        """
        # Generate a unique AVD name based on the email using our utility method
        avd_name = self.get_avd_name_from_email(email)

        # Check if an AVD with this name already exists
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        if os.path.exists(avd_path):
            logger.info(f"AVD {avd_name} already exists, reusing it")
            return True, avd_name

        try:
            # Get list of available system images
            logger.info("Getting list of available system images")
            try:
                list_cmd = [f"{self.android_home}/cmdline-tools/latest/bin/sdkmanager", "--list"]

                env = os.environ.copy()
                env["ANDROID_SDK_ROOT"] = self.android_home

                result = subprocess.run(
                    list_cmd, env=env, check=False, text=True, capture_output=True, timeout=30
                )

                # Parse available system images
                available_images = []
                output_lines = result.stdout.split("\n")
                for line in output_lines:
                    if "system-images;" in line:
                        # Extract the system image path
                        parts = line.strip().split("|")
                        if len(parts) > 0:
                            img_path = parts[0].strip()
                            available_images.append(img_path)

                # Get a compatible system image based on host architecture
                sys_img = self.get_compatible_system_image(available_images)

                if not sys_img:
                    # Always use x86_64 images for all platforms
                    sys_img = "system-images;android-30;google_apis_playstore;x86_64"
                    logger.info(f"No compatible system image found, will install {sys_img} for all hosts")

                # Try to install the system image if we have one selected
                if sys_img:
                    # Try to install the system image
                    logger.info(f"Installing system image: {sys_img}")
                    install_cmd = [
                        f"{self.android_home}/cmdline-tools/latest/bin/sdkmanager",
                        "--install",
                        sys_img,
                    ]

                    install_result = subprocess.run(
                        install_cmd,
                        env=env,
                        check=False,
                        text=True,
                        input="y\n",  # Auto-accept license
                        capture_output=True,
                        timeout=300,  # 5 minutes timeout for installation
                    )

                    if install_result.returncode != 0:
                        logger.error(f"Failed to install system image: {install_result.stderr}")
                        return False, f"Failed to install system image: {install_result.stderr}"
                else:
                    logger.error("No compatible system image found and failed to select a fallback")
                    return False, "No compatible system image found for your architecture"

            except Exception as e:
                logger.error(f"Error getting available system images: {e}")
                # Fallback to x86_64 for all platforms
                sys_img = "system-images;android-30;google_apis;x86_64"
                logger.info("Using fallback x86_64 system image")

            logger.info(f"Using system image: {sys_img}")

            # Create new AVD
            logger.info(f"Creating new AVD named {avd_name} for email {email}")

            # Set environment variables
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir

            # Build AVD creation command
            create_cmd = [
                f"{self.android_home}/cmdline-tools/latest/bin/avdmanager",
                "create",
                "avd",
                "-n",
                avd_name,
                "-k",
                sys_img,
                "--device",
                "pixel_5",
                "--force",
            ]

            logger.info(f"Creating AVD with command: {' '.join(create_cmd)}")

            # Execute AVD creation command
            process = subprocess.run(create_cmd, env=env, check=False, text=True, capture_output=True)

            if process.returncode != 0:
                logger.error(f"Failed to create AVD: {process.stderr}")
                return False, f"Failed to create AVD: {process.stderr}"

            # Configure AVD settings for better performance
            self._configure_avd(avd_name)

            return True, avd_name

        except Exception as e:
            logger.error(f"Error creating new AVD: {e}")
            return False, str(e)

    def _configure_avd(self, avd_name: str) -> None:
        """Configure AVD settings for better performance."""
        config_path = os.path.join(self.avd_dir, f"{avd_name}.avd", "config.ini")
        if not os.path.exists(config_path):
            logger.error(f"AVD config file not found at {config_path}")
            return

        try:
            # Read existing config
            with open(config_path, "r") as f:
                config_lines = f.readlines()

            # Always use x86_64 for all host types
            # Even on ARM Macs, we need to use x86_64 images with Rosetta 2 translation
            # as the Android emulator doesn't properly support ARM64 emulation yet
            cpu_arch = "x86_64"
            sysdir = "system-images/android-30/google_apis_playstore/x86_64/"

            logger.info(f"Using x86_64 architecture for all host types (even on ARM Macs)")

            # Special handling for cloud linux servers
            if self.host_arch == "x86_64" and os.path.exists("/etc/os-release"):
                # This is likely a Linux server
                logger.info("Detected Linux x86_64 host - using standard x86_64 configuration")

            logger.info(
                f"Configuring AVD {avd_name} for {self.host_arch} host with {cpu_arch} CPU architecture"
            )

            # Define settings to update
            settings = {
                "hw.ramSize": "4096",
                "hw.cpu.ncore": "4",
                "hw.gpu.enabled": "yes",
                "hw.gpu.mode": "swiftshader",
                "hw.audioInput": "no",
                "hw.audioOutput": "no",
                "hw.gps": "no",
                "hw.camera.back": "none",
                "hw.keyboard": "yes",
                "hw.keyboard.lid": "yes",  # Disable soft keyboard, force hardware keyboard
                "hw.keyboard.charmap": "qwerty2",  # Set keyboard layout
                "hw.mainKeys": "yes",  # Enable hardware keys
                "hw.statusBar": "no",  # Disable the status bar
                "hw.navButtons": "no",  # Disable the navigation buttons
                "hw.fastboot": "no",
                "hw.arc": "false",
                "hw.useext4": "yes",
                "kvm.enabled": "no",
                "showWindow": "no",
                "hw.arc.autologin": "no",
                "snapshot.present": "no",
                "disk.dataPartition.size": "6G",
                "PlayStore.enabled": "true",
                "image.sysdir.1": sysdir,
                "tag.id": "google_apis_playstore" if "playstore" in sysdir else "google_apis",
                "tag.display": "Google Play" if "playstore" in sysdir else "Google APIs",
                "hw.cpu.arch": cpu_arch,
                "ro.kernel.qemu.gles": "1",
                "skin.dynamic": "yes",
                "skin.name": "1080x1920",
                "skin.path": "_no_skin",
                "skin.path.backup": "_no_skin",
            }

            # For arm64 hosts, make sure we're not trying to use x86_64
            if self.host_arch == "arm64":
                # Remove any x86 settings
                keys_to_remove = []
                for line in config_lines:
                    if "=" in line:
                        key, value = line.split("=", 1)
                        if "x86" in value and key not in keys_to_remove:
                            keys_to_remove.append(key)

                # Log what we're removing
                if keys_to_remove:
                    logger.info(f"Removing incompatible x86 settings: {', '.join(keys_to_remove)}")

            # Update config file
            new_config_lines = []
            for line in config_lines:
                if "=" in line:
                    key = line.split("=")[0]
                    if key in settings:
                        new_config_lines.append(f"{key}={settings[key]}\n")
                        del settings[key]
                    else:
                        # Skip lines with x86 values on arm64 hosts
                        if self.host_arch == "arm64" and "x86" in line:
                            continue
                        new_config_lines.append(line)
                else:
                    new_config_lines.append(line)

            # Add any remaining settings
            for key, value in settings.items():
                new_config_lines.append(f"{key}={value}\n")

            # Write back to file
            with open(config_path, "w") as f:
                f.writelines(new_config_lines)

            logger.info(f"Updated AVD configuration for {avd_name}")

        except Exception as e:
            logger.error(f"Error configuring AVD: {e}")
