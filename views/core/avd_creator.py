import logging
import os
import shutil
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class AVDCreator:
    """
    Handles the creation and configuration of Android Virtual Devices (AVDs).
    """

    # Seed clone constants
    SEED_CLONE_EMAIL = "seed@clone.local"
    SEED_CLONE_SNAPSHOT = "pre_kindle_install"

    # System image to use for all AVDs
    # Must match `sdkmanager --list` format exactly
    SYSTEM_IMAGE = "system-images;android-30;google_apis;x86_64"
    ALT_SYSTEM_IMAGE = "system-images;android-36;google_apis;x86_64"

    # List of email addresses that should use ALT_SYSTEM_IMAGE for testing
    ALT_IMAGE_TEST_EMAILS = [
        "kindle@solreader.com",
        "sam@solreader.com",
        "samuel@ofbrooklyn.com",
        "craigcreative@me.com",
    ]

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
        Get the configured system image if available.

        Args:
            available_images: List of available system images

        Returns:
            Optional[str]: System image if available, None otherwise
        """
        # Check if our configured system image is available
        if self.SYSTEM_IMAGE in available_images:
            logger.info(f"Using configured system image: {self.SYSTEM_IMAGE}")
            return self.SYSTEM_IMAGE
        else:
            logger.error(f"Configured system image {self.SYSTEM_IMAGE} not found in available images")
            return None

    def _get_system_image_for_email(self, email: str, available_images: List[str]) -> Optional[str]:
        """
        Determine which system image to use based on the user's email.

        Users in ALT_IMAGE_TEST_EMAILS list will use Android 36, others use Android 30.

        Args:
            email: User's email address
            available_images: List of available system images

        Returns:
            Optional[str]: System image to use, or None if no compatible image found
        """
        # Check if this email is in the test list
        if email in self.ALT_IMAGE_TEST_EMAILS:
            logger.info(f"User {email} is in ALT_IMAGE_TEST_EMAILS, attempting to use Android 36")
            if self.ALT_SYSTEM_IMAGE in available_images:
                logger.info(f"Using Android 36 system image: {self.ALT_SYSTEM_IMAGE}")
                return self.ALT_SYSTEM_IMAGE
            else:
                logger.warning(
                    f"Android 36 image {self.ALT_SYSTEM_IMAGE} not available, falling back to Android 30"
                )
                # Fall back to Android 30
                if self.SYSTEM_IMAGE in available_images:
                    logger.info(f"Using fallback Android 30 system image: {self.SYSTEM_IMAGE}")
                    return self.SYSTEM_IMAGE
        else:
            # Regular users use Android 30
            logger.info(f"User {email} is a regular user, using Android 30")
            if self.SYSTEM_IMAGE in available_images:
                logger.info(f"Using Android 30 system image: {self.SYSTEM_IMAGE}")
                return self.SYSTEM_IMAGE

        # No compatible image found
        logger.error(f"No compatible system image found for {email}")
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

                # Determine which system image to use based on email
                sys_img = self._get_system_image_for_email(email, available_images)

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
                    logger.error(f"No compatible system image found for {email}")
                    return False, f"No compatible system image found in available images"

            except Exception as e:
                logger.error(f"Error getting available system images: {e}")
                return False, f"Error listing system images: {e}"

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
            self._configure_avd(avd_name, sys_img)

            # Update profile with system image information
            from views.core.avd_profile_manager import AVDProfileManager

            avd_manager = AVDProfileManager.get_instance()
            # Extract Android version from system image string
            # "system-images;android-36;google_apis;x86_64" -> "36"
            android_version = sys_img.split(";")[1].replace("android-", "")
            avd_manager.set_user_field(email, "android_version", android_version)
            avd_manager.set_user_field(email, "system_image", sys_img)
            logger.info(f"Updated profile for {email} with Android {android_version} ({sys_img})")

            return True, avd_name

        except Exception as e:
            logger.error(f"Error creating new AVD: {e}")
            return False, str(e)

    def _configure_avd(self, avd_name: str, system_image: str) -> None:
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

            # Derive sysdir from system_image parameter
            # Convert from sdkmanager format to path format
            # "system-images;android-30;google_apis;x86_64" -> "system-images/android-30/google_apis/x86_64/"
            sysdir = system_image.replace(";", "/") + "/"

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
                "hw.ramSize": "5120",
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
                "snapshot.present": "yes",
                "quickbootChoice": "2",
                "disk.dataPartition.size": "6G",
                "PlayStore.enabled": "true",
                "image.sysdir.1": sysdir,
                "tag.id": "google_apis_playstore" if "playstore" in sysdir else "google_apis",
                "tag.display": "Google Play" if "playstore" in sysdir else "Google APIs",
                "hw.cpu.arch": cpu_arch,
                "ro.kernel.qemu.gles": "1",
                "hw.gfxstream": "0",  # Disable gfxstream to maintain snapshot compatibility
                "skin.dynamic": "yes",
                "skin.name": "1080x1920",
                "skin.path": "_no_skin",
                "skin.path.backup": "_no_skin",
                # Keyboard settings - try multiple approaches to disable soft keyboard
                "qemu.keyboard_layout": "us",  # Set US keyboard layout
                "qemu.enable_keyboard_permission": "yes",  # Enable keyboard permission
                "qemu.hardware_keyboard_button_type": "power",  # Set hardware keyboard button type
                "qemu.settings.system.show_ime_with_hard_keyboard": "0",  # Disable IME with hardware keyboard
                # Stylus settings - disable stylus features (Android 36)
                "hw.stylus": "no",  # Disable stylus hardware
                "hw.pen": "no",  # Disable pen hardware
                "hw.stylus.button": "no",  # Disable stylus button
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

    def get_seed_clone_avd_name(self) -> str:
        """Get the AVD name for the seed clone."""
        return self.get_avd_name_from_email(self.SEED_CLONE_EMAIL)

    def has_seed_clone(self) -> bool:
        """Check if the seed clone AVD exists."""
        seed_clone_name = self.get_seed_clone_avd_name()
        avd_path = os.path.join(self.avd_dir, f"{seed_clone_name}.avd")
        return os.path.exists(avd_path)

    def has_seed_clone_snapshot(self) -> bool:
        """Check if the seed clone has a snapshot (now always checks for default_boot)."""
        if not self.has_seed_clone():
            return False

        seed_clone_name = self.get_seed_clone_avd_name()
        avd_path = os.path.join(self.avd_dir, f"{seed_clone_name}.avd")
        snapshots_dir = os.path.join(avd_path, "snapshots")
        # Now check for default_boot snapshot instead of named snapshot
        snapshot_path = os.path.join(snapshots_dir, "default_boot")

        return os.path.exists(snapshot_path)

    def delete_avd(self, email: str) -> Tuple[bool, str]:
        """
        Delete an AVD for the given email.

        Args:
            email: Email address of the AVD to delete

        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            avd_name = self.get_avd_name_from_email(email)
            logger.info(f"Deleting AVD: {avd_name}")

            # Use avdmanager to delete the AVD
            cmd = [
                os.path.join(self.android_home, "cmdline-tools", "latest", "bin", "avdmanager"),
                "delete",
                "avd",
                "-n",
                avd_name,
            ]

            # Set up environment for avdmanager
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir

            result = subprocess.run(cmd, capture_output=True, text=True, env=env)

            if result.returncode == 0:
                logger.info(f"Successfully deleted AVD: {avd_name}")

                # Also remove the AVD directory if it still exists
                avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
                if os.path.exists(avd_path):
                    shutil.rmtree(avd_path)
                    logger.info(f"Removed AVD directory: {avd_path}")

                return True, f"Successfully deleted AVD: {avd_name}"
            else:
                # Check if the error is because the AVD doesn't exist
                if "There is no Android Virtual Device named" in result.stderr:
                    logger.info(f"AVD {avd_name} does not exist, nothing to delete")
                    return True, f"AVD {avd_name} does not exist, nothing to delete"
                else:
                    logger.error(f"Failed to delete AVD: {result.stderr}")
                    return False, f"Failed to delete AVD: {result.stderr}"

        except Exception as e:
            logger.error(f"Error deleting AVD: {e}")
            return False, str(e)

    def create_seed_clone_avd(self) -> Tuple[bool, str]:
        """
        Create the seed clone AVD that will be used as a template for all new users.

        Returns:
            Tuple[bool, str]: (success, avd_name or error message)
        """
        logger.info("Creating seed clone AVD for fast user initialization")
        # Seed clone always uses main SYSTEM_IMAGE for compatibility with all users
        logger.info(f"Creating seed clone with main system image (Android 30)")
        success, avd_name = self.create_new_avd(self.SEED_CLONE_EMAIL)

        if success:
            # Mark seed clone for device identifier randomization on first boot
            try:
                from views.core.avd_profile_manager import AVDProfileManager

                avd_manager = AVDProfileManager.get_instance()
                avd_manager.set_user_field(self.SEED_CLONE_EMAIL, "needs_device_randomization", True)
                avd_manager.set_user_field(self.SEED_CLONE_EMAIL, "post_boot_randomized", False)
                logger.info("Marked seed clone AVD for device randomization on first boot")
            except Exception as e:
                logger.warning(f"Could not mark seed clone for randomization: {e}")

        return success, avd_name

    def copy_avd_from_seed_clone(self, email: str) -> Tuple[bool, str]:
        """
        Copy the seed clone AVD to create a new AVD for the given email.

        Note: The seed clone always uses the main SYSTEM_IMAGE (Android 30) for compatibility
        with all users. Users in ALT_IMAGE_TEST_EMAILS who need Android 36 will get it
        when their AVD is created directly (not from seed clone).

        Args:
            email: The user's email address

        Returns:
            Tuple[bool, str]: (success, avd_name or error message)
        """
        if not self.has_seed_clone():
            logger.error("Seed clone AVD does not exist")
            return False, "Seed clone AVD does not exist"

        try:
            # Get AVD names
            seed_clone_name = self.get_seed_clone_avd_name()
            new_avd_name = self.get_avd_name_from_email(email)

            # Source and destination paths
            seed_clone_path = os.path.join(self.avd_dir, f"{seed_clone_name}.avd")
            new_avd_path = os.path.join(self.avd_dir, f"{new_avd_name}.avd")
            new_avd_ini = os.path.join(self.avd_dir, f"{new_avd_name}.ini")

            # Check if destination already exists (both .avd directory and .ini file)
            if os.path.exists(new_avd_path) and os.path.exists(new_avd_ini):
                logger.info(f"AVD {new_avd_name} already exists, reusing it")
                return True, new_avd_name
            elif os.path.exists(new_avd_path) and not os.path.exists(new_avd_ini):
                logger.warning(
                    f"AVD directory {new_avd_path} exists but .ini file is missing, removing incomplete AVD"
                )
                shutil.rmtree(new_avd_path, ignore_errors=True)

            logger.info(f"Creating {new_avd_name} from seed clone using avdmanager move strategy")

            # Step 1: Create a backup of the seed clone
            temp_backup_name = f"{seed_clone_name}_backup_temp"
            temp_backup_path = os.path.join(self.avd_dir, f"{temp_backup_name}.avd")
            temp_backup_ini = os.path.join(self.avd_dir, f"{temp_backup_name}.ini")

            logger.info(f"Creating temporary backup of seed clone at {temp_backup_path}")
            shutil.copytree(seed_clone_path, temp_backup_path)

            # Copy the .ini file for the backup
            seed_clone_ini = os.path.join(self.avd_dir, f"{seed_clone_name}.ini")
            if os.path.exists(seed_clone_ini):
                shutil.copy2(seed_clone_ini, temp_backup_ini)

            # Step 2: Use avdmanager to move seed clone to the new user AVD
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir

            move_cmd = [
                os.path.join(self.android_home, "cmdline-tools", "latest", "bin", "avdmanager"),
                "move",
                "avd",
                "-n",
                seed_clone_name,
                "-r",
                new_avd_name,
            ]

            logger.info(f"Moving seed clone to {new_avd_name} using avdmanager")
            result = subprocess.run(move_cmd, capture_output=True, text=True, env=env)

            if result.returncode != 0:
                logger.error(f"Failed to move AVD: {result.stderr}")
                # Clean up backup before failing
                if os.path.exists(temp_backup_path):
                    shutil.rmtree(temp_backup_path)
                if os.path.exists(temp_backup_ini):
                    os.remove(temp_backup_ini)
                return False, f"Failed to move AVD: {result.stderr}"

            # Step 3: Restore the seed clone from backup
            logger.info("Restoring seed clone from backup")
            shutil.move(temp_backup_path, seed_clone_path)
            if os.path.exists(temp_backup_ini):
                shutil.move(temp_backup_ini, seed_clone_ini)

            # Step 4: Update snapshot references in the new AVD
            self._update_snapshot_references(seed_clone_name, new_avd_name)

            # Step 5: Configure the new AVD with proper settings (including RAM)
            logger.info(f"Configuring cloned AVD {new_avd_name} with proper settings")
            # Seed clone always uses the default SYSTEM_IMAGE (Android 30)
            self._configure_avd(new_avd_name, self.SYSTEM_IMAGE)

            # Step 6: Randomize device identifiers to prevent auth token ejection
            logger.info(f"Randomizing device identifiers for {new_avd_name}")
            randomized_identifiers = {}
            try:
                from server.utils.device_identifier_utils import (
                    randomize_avd_config_identifiers,
                )

                config_path = os.path.join(new_avd_path, "config.ini")
                randomized_identifiers = randomize_avd_config_identifiers(config_path)
                logger.info(f"Randomized identifiers for {new_avd_name}: {randomized_identifiers}")
            except Exception as e:
                logger.error(f"Failed to randomize device identifiers: {e}")
                # Continue anyway - better to have a working AVD with duplicate identifiers
                # than to fail the cloning process

            # Mark this AVD as created from seed clone in the user profile
            try:
                from views.core.avd_profile_manager import AVDProfileManager

                avd_manager = AVDProfileManager.get_instance()
                avd_manager.set_user_field(email, "created_from_seed_clone", True)
                # Store randomized identifiers in user profile for consistent use
                if randomized_identifiers:
                    avd_manager.set_user_field(email, "device_identifiers", randomized_identifiers)
                # Clear post_boot_randomized flag to ensure randomization happens on first boot
                avd_manager.set_user_field(email, "post_boot_randomized", False)
                # Set Android version - seed clone always uses main SYSTEM_IMAGE (Android 30)
                android_version = self.SYSTEM_IMAGE.split(";")[1].replace("android-", "")
                avd_manager.set_user_field(email, "android_version", android_version)
                avd_manager.set_user_field(email, "system_image", self.SYSTEM_IMAGE)
                logger.info(f"Marked {email} as created from seed clone with Android {android_version}")
            except Exception as e:
                logger.warning(f"Could not mark AVD as created from seed clone: {e}")

            logger.info(f"Successfully created {new_avd_name} from seed clone using avdmanager")
            return True, new_avd_name

        except Exception as e:
            logger.error(f"Error creating AVD from seed clone: {e}")
            # Clean up any temporary files
            if "temp_backup_path" in locals() and os.path.exists(temp_backup_path):
                shutil.rmtree(temp_backup_path, ignore_errors=True)
            if "temp_backup_ini" in locals() and os.path.exists(temp_backup_ini):
                try:
                    os.remove(temp_backup_ini)
                except:
                    pass
            return False, str(e)

    def _replace_avd_name_in_file(self, file_path: str, old_avd_name: str, new_avd_name: str) -> bool:
        """
        Replace AVD name references in a configuration file.

        Args:
            file_path: Path to the file to update
            old_avd_name: Old AVD name to replace
            new_avd_name: New AVD name

        Returns:
            bool: True if file was updated, False if file doesn't exist
        """
        if not os.path.exists(file_path):
            return False

        try:
            with open(file_path, "r") as f:
                content = f.read()

            # Replace references to old AVD name
            updated_content = content.replace(old_avd_name, new_avd_name)

            # Only write if content changed
            if content != updated_content:
                with open(file_path, "w") as f:
                    f.write(updated_content)

            return True
        except Exception as e:
            logger.error(f"Error updating file {file_path}: {e}")
            return False

    def _update_avd_config_for_new_name(self, old_avd_name: str, new_avd_name: str, email: str) -> None:
        """
        Update AVD configuration files to reference the new AVD name instead of the seed clone.

        Args:
            old_avd_name: The seed clone AVD name
            new_avd_name: The new AVD name
            email: The user's email address
        """
        try:
            # Update the .ini file
            ini_path = os.path.join(self.avd_dir, f"{new_avd_name}.ini")
            if self._replace_avd_name_in_file(ini_path, old_avd_name, new_avd_name):
                logger.info(f"Updated {new_avd_name}.ini file")

            # Update config.ini inside the AVD directory
            config_path = os.path.join(self.avd_dir, f"{new_avd_name}.avd", "config.ini")
            if self._replace_avd_name_in_file(config_path, old_avd_name, new_avd_name):
                logger.info(f"Updated config.ini for {new_avd_name}")

            # Update hardware-qemu.ini if it exists
            hw_qemu_path = os.path.join(self.avd_dir, f"{new_avd_name}.avd", "hardware-qemu.ini")
            if self._replace_avd_name_in_file(hw_qemu_path, old_avd_name, new_avd_name):
                logger.info(f"Updated hardware-qemu.ini for {new_avd_name}")

        except Exception as e:
            logger.error(f"Error updating AVD config files: {e}")

    def _update_snapshot_references(self, old_avd_name: str, new_avd_name: str) -> None:
        """
        Update snapshot files to reference the new AVD paths instead of the seed clone paths.
        This is necessary for snapshots to work correctly after copying an AVD.

        Args:
            old_avd_name: The seed clone AVD name
            new_avd_name: The new AVD name
        """
        try:
            snapshots_dir = os.path.join(self.avd_dir, f"{new_avd_name}.avd", "snapshots")
            if not os.path.exists(snapshots_dir):
                logger.debug(f"No snapshots directory found for {new_avd_name}")
                return

            # Process each snapshot
            for snapshot_name in os.listdir(snapshots_dir):
                snapshot_path = os.path.join(snapshots_dir, snapshot_name)
                if not os.path.isdir(snapshot_path):
                    continue

                logger.info(f"Updating snapshot '{snapshot_name}' references for {new_avd_name}")

                # Update hardware.ini
                hardware_ini_path = os.path.join(snapshot_path, "hardware.ini")
                if os.path.exists(hardware_ini_path):
                    self._replace_avd_name_in_file(hardware_ini_path, old_avd_name, new_avd_name)
                    logger.debug(f"Updated hardware.ini in snapshot '{snapshot_name}'")

                # Update snapshot.pb (binary protobuf file - requires binary replacement)
                snapshot_pb_path = os.path.join(snapshot_path, "snapshot.pb")
                if os.path.exists(snapshot_pb_path):
                    try:
                        with open(snapshot_pb_path, "rb") as f:
                            content = f.read()

                        # Replace old AVD name with new one in binary content
                        old_bytes = old_avd_name.encode("utf-8")
                        new_bytes = new_avd_name.encode("utf-8")
                        updated_content = content.replace(old_bytes, new_bytes)

                        # Only write if content changed
                        if content != updated_content:
                            with open(snapshot_pb_path, "wb") as f:
                                f.write(updated_content)
                            logger.debug(f"Updated snapshot.pb in snapshot '{snapshot_name}'")
                    except Exception as e:
                        logger.warning(f"Failed to update snapshot.pb: {e}")

        except Exception as e:
            logger.error(f"Error updating snapshot references: {e}")

    def is_seed_clone_ready(self) -> bool:
        """
        Check if the seed clone is ready to be used (has AVD).

        Returns:
            bool: True if seed clone is ready, False otherwise
        """
        return self.has_seed_clone()
