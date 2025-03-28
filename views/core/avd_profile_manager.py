import json
import logging
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

class AVDProfileManager:
    """
    Manages Android Virtual Device (AVD) profiles for different Kindle user accounts.
    
    This class provides functionality to:
    1. Store and track multiple AVDs mapped to email addresses
    2. Switch between AVDs when a new authentication request comes in
    3. Create new AVD profiles when needed
    4. Track the currently active AVD/email
    """
    
    def __init__(self, base_dir: str = "/opt/android-sdk"):
        self.base_dir = base_dir
        self.avd_dir = os.path.join(base_dir, "avd")
        self.profiles_dir = os.path.join(base_dir, "profiles")
        self.index_file = os.path.join(self.profiles_dir, "profiles_index.json")
        self.current_profile_file = os.path.join(self.profiles_dir, "current_profile.json")
        self.android_home = os.environ.get("ANDROID_HOME", base_dir)
        
        # Detect host architecture
        self.host_arch = self._detect_host_architecture()
        logger.info(f"Detected host architecture: {self.host_arch}")
        
        # Ensure directories exist
        os.makedirs(self.profiles_dir, exist_ok=True)
        
        # Load profile index if it exists, otherwise create empty one
        self.profiles_index = self._load_profiles_index()
        self.current_profile = self._load_current_profile()
        
    def _detect_host_architecture(self) -> str:
        """
        Detect the host machine's architecture.
        
        Returns:
            str: One of 'arm64', 'x86_64', or 'unknown'
        """
        machine = platform.machine().lower()
        
        if machine in ('arm64', 'aarch64'):
            return 'arm64'
        elif machine in ('x86_64', 'amd64', 'x64'):
            return 'x86_64'
        else:
            # Log the actual architecture for debugging
            logger.warning(f"Unknown architecture: {machine}, defaulting to x86_64")
            return 'unknown'
            
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
        
    def _load_profiles_index(self) -> Dict[str, str]:
        """Load profiles index from JSON file or create if it doesn't exist."""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading profiles index: {e}")
                return {}
        else:
            return {}
            
    def _save_profiles_index(self) -> None:
        """Save profiles index to JSON file."""
        try:
            with open(self.index_file, 'w') as f:
                json.dump(self.profiles_index, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving profiles index: {e}")
            
    def _load_current_profile(self) -> Optional[Dict]:
        """Load current profile from JSON file or return None if it doesn't exist."""
        if os.path.exists(self.current_profile_file):
            try:
                with open(self.current_profile_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading current profile: {e}")
                return None
        else:
            return None
            
    def _save_current_profile(self, email: str, avd_name: str) -> None:
        """Save current profile to JSON file."""
        current = {
            "email": email,
            "avd_name": avd_name,
            "last_used": int(time.time())
        }
        try:
            with open(self.current_profile_file, 'w') as f:
                json.dump(current, f, indent=2)
            self.current_profile = current
        except Exception as e:
            logger.error(f"Error saving current profile: {e}")
    
    def get_avd_for_email(self, email: str) -> Optional[str]:
        """Get the AVD name for a given email address."""
        return self.profiles_index.get(email)
        
    def list_profiles(self) -> List[Dict]:
        """List all available profiles with their details."""
        result = []
        for email, avd_name in self.profiles_index.items():
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            result.append({
                "email": email,
                "avd_name": avd_name,
                "exists": os.path.exists(avd_path),
                "current": self.current_profile and self.current_profile.get("email") == email
            })
        return result
        
    def get_current_profile(self) -> Optional[Dict]:
        """Get information about the currently active profile."""
        return self.current_profile
        
    def create_new_avd(self, email: str) -> Tuple[bool, str]:
        """
        Create a new AVD for the given email.
        
        Returns:
            Tuple[bool, str]: (success, avd_name)
        """
        # Generate a unique AVD name based on the email
        email_prefix = email.split('@')[0].replace('.', '_')
        avd_name = f"KindleAVD_{email_prefix}"
        
        # Check if an AVD with this name already exists
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        if os.path.exists(avd_path):
            logger.info(f"AVD {avd_name} already exists, reusing it")
            return True, avd_name
            
        try:
            # Get list of available system images
            logger.info("Getting list of available system images")
            try:
                list_cmd = [
                    f"{self.android_home}/cmdline-tools/latest/bin/sdkmanager",
                    "--list"
                ]
                
                env = os.environ.copy()
                env["ANDROID_SDK_ROOT"] = self.android_home
                
                result = subprocess.run(
                    list_cmd,
                    env=env,
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=30
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
                        "--install", sys_img
                    ]
                    
                    install_result = subprocess.run(
                        install_cmd,
                        env=env,
                        check=False,
                        text=True,
                        input="y\n",  # Auto-accept license
                        capture_output=True,
                        timeout=300  # 5 minutes timeout for installation
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
                "create", "avd",
                "-n", avd_name,
                "-k", sys_img,
                "--device", "pixel_5",
                "--force"
            ]
            
            logger.info(f"Creating AVD with command: {' '.join(create_cmd)}")
            
            # Execute AVD creation command
            process = subprocess.run(
                create_cmd,
                env=env,
                check=False,
                text=True,
                capture_output=True
            )
            
            if process.returncode != 0:
                logger.error(f"Failed to create AVD: {process.stderr}")
                return False, f"Failed to create AVD: {process.stderr}"
            
            # Configure AVD settings for better performance
            self._configure_avd(avd_name)
            
            # Verify that the AVD is compatible with the host architecture
            config_path = os.path.join(self.avd_dir, f"{avd_name}.avd", "config.ini")
            try:
                # Read the config file to double-check architecture settings
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config_content = f.read()
                        
                    # Check for architecture mismatch
                    if self.host_arch == 'arm64' and "x86" in config_content:
                        logger.warning(f"AVD {avd_name} may have x86 settings on an arm64 host. Forcing arm64 config...")
                        
                        # Use a more direct approach to fix the config
                        with open(config_path, 'w') as f:
                            fixed_content = config_content.replace("x86_64", "arm64-v8a")
                            fixed_content = fixed_content.replace("hw.cpu.arch=x86", "hw.cpu.arch=arm64-v8a")
                            
                            # Update system image path 
                            lines = fixed_content.split("\n")
                            updated_lines = []
                            for line in lines:
                                if line.startswith("image.sysdir.1=") and "x86" in line:
                                    updated_lines.append("image.sysdir.1=system-images/android-30/google_apis/arm64-v8a/")
                                else:
                                    updated_lines.append(line)
                                    
                            f.write("\n".join(updated_lines))
                        
                        logger.info("Forced arm64 configuration for AVD")
                else:
                    logger.warning(f"AVD config file not found at {config_path}")
            except Exception as e:
                logger.error(f"Error verifying AVD architecture compatibility: {e}")
            
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
            with open(config_path, 'r') as f:
                config_lines = f.readlines()
                
            # Always use x86_64 for all host types
            # Even on ARM Macs, we need to use x86_64 images with Rosetta 2 translation
            # as the Android emulator doesn't properly support ARM64 emulation yet
            cpu_arch = "x86_64"
            sysdir = "system-images/android-30/google_apis_playstore/x86_64/"
            
            logger.info(f"Using x86_64 architecture for all host types (even on ARM Macs)")
            
            # Special handling for cloud linux servers
            if self.host_arch == 'x86_64' and os.path.exists('/etc/os-release'):
                # This is likely a Linux server
                logger.info("Detected Linux x86_64 host - using standard x86_64 configuration")
                
            logger.info(f"Configuring AVD {avd_name} for {self.host_arch} host with {cpu_arch} CPU architecture")
                
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
                "skin.path.backup": "_no_skin"
            }
            
            # For arm64 hosts, make sure we're not trying to use x86_64
            if self.host_arch == 'arm64':
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
                    key = line.split('=')[0]
                    if key in settings:
                        new_config_lines.append(f"{key}={settings[key]}\n")
                        del settings[key]
                    else:
                        # Skip lines with x86 values on arm64 hosts
                        if self.host_arch == 'arm64' and "x86" in line:
                            continue
                        new_config_lines.append(line)
                else:
                    new_config_lines.append(line)
                    
            # Add any remaining settings
            for key, value in settings.items():
                new_config_lines.append(f"{key}={value}\n")
                
            # Write back to file
            with open(config_path, 'w') as f:
                f.writelines(new_config_lines)
                
            logger.info(f"Updated AVD configuration for {avd_name}")
            
        except Exception as e:
            logger.error(f"Error configuring AVD: {e}")
            
    def register_profile(self, email: str, avd_name: str) -> None:
        """Register a profile by associating an email with an AVD name."""
        self.profiles_index[email] = avd_name
        self._save_profiles_index()
        logger.info(f"Registered profile for {email} with AVD {avd_name}")
        
    def is_emulator_running(self) -> bool:
        """Check if an emulator is currently running."""
        try:
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True
            )
            return "emulator" in result.stdout
        except Exception as e:
            logger.error(f"Error checking if emulator is running: {e}")
            return False
            
    def stop_emulator(self) -> bool:
        """Stop the currently running emulator."""
        try:
            # First try graceful shutdown
            subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "emu", "kill"],
                check=False
            )
            
            # Wait for emulator to shut down
            deadline = time.time() + 30
            while time.time() < deadline:
                if not self.is_emulator_running():
                    logger.info("Emulator shut down gracefully")
                    return True
                time.sleep(1)
                
            # Force kill if graceful shutdown failed
            subprocess.run(
                ["pkill", "-f", "emulator"],
                check=False
            )
            
            logger.info("Emulator forcibly terminated")
            return True
        except Exception as e:
            logger.error(f"Error stopping emulator: {e}")
            return False
            
    def start_emulator(self, avd_name: str) -> bool:
        """
        Start the specified AVD in headless mode.
        
        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        try:
            # First check if an emulator is already running
            if self.is_emulator_running():
                logger.warning("An emulator is already running, stopping it first")
                if not self.stop_emulator():
                    logger.error("Failed to stop existing emulator")
                    return False
                    
            # Always force x86_64 architecture for all hosts
            config_path = os.path.join(self.avd_dir, f"{avd_name}.avd", "config.ini")
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        config_content = f.read()
                    
                    # Force x86_64 for all hosts
                    if "arm64" in config_content:
                        logger.warning("Found arm64 architecture in AVD. Changing to x86_64...")
                        self._configure_avd(avd_name)  # Force reconfiguration to x86_64
                except Exception as e:
                    logger.error(f"Error checking AVD compatibility: {e}")
            
            # Set environment variables
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir
            env["ANDROID_HOME"] = self.android_home
            
            # Build emulator command with architecture-specific options
            if self.host_arch == 'arm64':
                # For ARM Macs, try to use a different approach
                # Use arch command to force x86_64 mode via Rosetta 2
                emulator_cmd = [
                    "arch", "-x86_64",
                    f"{self.android_home}/emulator/emulator",
                    "-avd", avd_name,
                    "-no-window",
                    "-no-audio",
                    "-no-boot-anim",
                    "-no-metrics",
                    "-gpu", "swiftshader_indirect",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-writable-system",
                    "-feature", "-HVF", # Disable Hardware Virtualization
                    "-accel", "off"
                ]
                
                logger.info("Using arch -x86_64 to run the emulator through Rosetta 2 on ARM Mac")
            else:
                # For x86_64 hosts (Linux servers), use standard command
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-avd", avd_name,
                    "-no-window",
                    "-no-audio",
                    "-no-boot-anim",
                    "-no-metrics",
                    "-gpu", "swiftshader_indirect",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-writable-system",
                    "-accel", "on",  # Use hardware acceleration if available
                    "-feature", "HVF",  # Hardware Virtualization Features
                    "-feature", "KVM"  # Enable KVM (Linux)
                ]
            
            # Start emulator in background
            logger.info(f"Starting emulator with AVD {avd_name}")
            logger.info(f"Using command: {' '.join(emulator_cmd)}")
            
            process = subprocess.Popen(
                emulator_cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Wait for emulator to boot
            logger.info("Waiting for emulator to boot...")
            deadline = time.time() + 120  # 2 minutes timeout
            while time.time() < deadline:
                try:
                    boot_completed = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "shell", "getprop", "sys.boot_completed"],
                        check=False,
                        capture_output=True,
                        text=True
                    )
                    if boot_completed.stdout.strip() == "1":
                        logger.info("Emulator booted successfully")
                        return True
                except Exception:
                    # Ignore exceptions during boot polling
                    pass
                    
                # Check if process is still running
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    error_msg = stderr.decode() if stderr else 'No error message'
                    logger.error(f"Emulator process exited prematurely: {error_msg}")
                    
                    # If there's an architecture mismatch error, try to fix it and restart
                    if "Avd's CPU Architecture" in error_msg and "not supported" in error_msg:
                        logger.warning("Architecture mismatch detected. Attempting to fix AVD config...")
                        
                        # On ARM Macs, we need a different approach
                        if self.host_arch == 'arm64':
                            logger.warning("On ARM Mac, trying a different approach...")
                            try:
                                # Delete the AVD completely and recreate it with ARM image
                                logger.info(f"Deleting AVD {avd_name} to recreate with compatible settings")
                                avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
                                avd_ini = os.path.join(self.avd_dir, f"{avd_name}.ini")
                                
                                # Delete the AVD files if they exist
                                if os.path.exists(avd_path):
                                    shutil.rmtree(avd_path, ignore_errors=True)
                                if os.path.exists(avd_ini):
                                    os.remove(avd_ini)
                                    
                                # Try alternative approach - use arch x86_64 command
                                logger.info("Attempting to use ARM system image...")
                                
                                # Try with ARM image
                                env = os.environ.copy()
                                env["ANDROID_SDK_ROOT"] = self.android_home
                                env["ANDROID_AVD_HOME"] = self.avd_dir
                                
                                # Install ARM image if needed
                                arm_img = "system-images;android-30;google_apis;arm64-v8a"
                                logger.info(f"Installing {arm_img} for ARM-native emulation")
                                subprocess.run(
                                    [f"{self.android_home}/cmdline-tools/latest/bin/sdkmanager", 
                                     "--install", arm_img],
                                    env=env,
                                    input="y\n".encode(),
                                    check=False,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE
                                )
                                
                                # Create AVD with ARM image
                                create_cmd = [
                                    f"{self.android_home}/cmdline-tools/latest/bin/avdmanager",
                                    "create", "avd",
                                    "-n", avd_name,
                                    "-k", arm_img,
                                    "--device", "pixel_5",
                                    "--force"
                                ]
                                
                                logger.info(f"Creating ARM-native AVD with: {' '.join(create_cmd)}")
                                subprocess.run(
                                    create_cmd,
                                    env=env,
                                    check=False,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE
                                )
                                
                                # Configure AVD for ARM operation
                                if os.path.exists(config_path):
                                    with open(config_path, 'w') as f:
                                        f.write("hw.cpu.arch=arm64-v8a\n")
                                        f.write("image.sysdir.1=system-images/android-30/google_apis/arm64-v8a/\n")
                                        f.write("PlayStore.enabled=true\n")
                                        f.write("hw.ramSize=4096\n")
                                        f.write("showWindow=no\n")
                                        f.write("hw.keyboard=yes\n")
                                
                                # Try starting with ARM-native mode
                                logger.info("Retrying with ARM-native emulation...")
                                # Now try using qemu-system-aarch64 directly as a last resort
                                qemu_cmd = [
                                    f"{self.android_home}/emulator/qemu/darwin-aarch64/qemu-system-aarch64",
                                    "-avd", avd_name,
                                    "-no-window",
                                    "-no-audio",
                                    "-no-boot-anim"
                                ]
                                
                                logger.info(f"Testing QEMU direct command: {' '.join(qemu_cmd)}")
                                process = subprocess.Popen(
                                    qemu_cmd,
                                    env=env,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE
                                )
                                
                                # Wait a bit to see if it starts
                                time.sleep(10)
                                
                                # Check if process is still running
                                if process.poll() is None:
                                    logger.info("QEMU direct approach seems to be working...")
                                    # Wait for emulator to boot
                                    deadline = time.time() + 120
                                    while time.time() < deadline:
                                        try:
                                            boot_completed = subprocess.run(
                                                [f"{self.android_home}/platform-tools/adb", "shell", "getprop", "sys.boot_completed"],
                                                check=False,
                                                capture_output=True,
                                                text=True
                                            )
                                            if boot_completed.stdout.strip() == "1":
                                                logger.info("Emulator booted successfully using QEMU direct approach")
                                                return True
                                        except Exception:
                                            # Ignore exceptions during boot polling
                                            pass
                                        time.sleep(5)
                                else:
                                    stdout, stderr = process.communicate()
                                    logger.error(f"QEMU direct approach failed: {stderr.decode() if stderr else 'No error'}")
                            except Exception as e:
                                logger.error(f"Failed during ARM-native approach: {e}")
                        
                        # If we get here, try the standard x86_64 approach again
                        try:
                            # Create config.ini if it doesn't exist
                            if not os.path.exists(config_path):
                                # Create parent directory if needed
                                os.makedirs(os.path.dirname(config_path), exist_ok=True)
                                # Create basic config file with x86_64 architecture
                                with open(config_path, 'w') as f:
                                    f.write("hw.cpu.arch=x86_64\n")
                                    f.write("image.sysdir.1=system-images/android-30/google_apis_playstore/x86_64/\n")
                                    f.write("PlayStore.enabled=true\n")
                                    f.write("hw.ramSize=4096\n")
                                    f.write("showWindow=no\n")
                            
                            # Force x86_64 architecture for all hosts
                            self._configure_avd(avd_name)
                            
                            # Use a simplified command line as a last resort
                            if self.host_arch == 'arm64':
                                logger.info("Trying simplified command line as last resort")
                                alternate_cmd = ["arch", "-x86_64", "sh", "-c", 
                                               f"cd {self.android_home}/emulator && ./emulator @{avd_name} -no-window -gpu swiftshader"]
                                
                                logger.info(f"Running simplified command: {' '.join(alternate_cmd)}")
                                process = subprocess.Popen(
                                    alternate_cmd,
                                    env=env,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE
                                )
                                
                                # Wait for emulator boot
                                time.sleep(5)
                                
                                if process.poll() is None:
                                    # Process is still running, might be working
                                    logger.info("Simplified command approach seems to be working...")
                                    deadline = time.time() + 120
                                    while time.time() < deadline:
                                        try:
                                            boot_completed = subprocess.run(
                                                [f"{self.android_home}/platform-tools/adb", "shell", "getprop", "sys.boot_completed"],
                                                check=False,
                                                capture_output=True,
                                                text=True
                                            )
                                            if boot_completed.stdout.strip() == "1":
                                                logger.info("Emulator booted successfully using simplified command")
                                                return True
                                        except Exception:
                                            pass
                                        time.sleep(5)
                                else:
                                    stdout, stderr = process.communicate()
                                    logger.error(f"Simplified approach failed: {stderr.decode() if stderr else 'No error'}")
                                    
                            logger.info("Retrying emulator start with fixed x86_64 configuration...")
                            return self.start_emulator(avd_name)  # Recursive call
                        except Exception as e:
                            logger.error(f"Failed to fix AVD config: {e}")
                    
                    return False
                    
                time.sleep(5)
                
            logger.error("Emulator boot timed out")
            return False
            
        except Exception as e:
            logger.error(f"Error starting emulator: {e}")
            return False
            
    def switch_profile(self, email: str) -> Tuple[bool, str]:
        """
        Switch to the profile for the given email.
        If the profile doesn't exist, create a new one.
        
        Returns:
            Tuple[bool, str]: (success, message)
        """
        logger.info(f"Switching to profile for email: {email}")
        
        # Check if this is already the current profile
        if self.current_profile and self.current_profile.get("email") == email:
            logger.info(f"Already using profile for {email}")
            return True, f"Already using profile for {email}"
            
        # Get AVD name for this email
        avd_name = self.get_avd_for_email(email)
        
        # If no AVD exists for this email, create one
        if not avd_name:
            logger.info(f"No AVD found for {email}, creating new one")
            success, result = self.create_new_avd(email)
            if not success:
                return False, f"Failed to create AVD: {result}"
            avd_name = result
            self.register_profile(email, avd_name)
        
        # Check if this AVD actually exists - it might not if we're using
        # manually registered AVDs but the Android Studio AVD was renamed or deleted
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        avd_exists = os.path.exists(avd_path)
        
        # For Mac M1/M2/M4 users where direct emulator launch might fail,
        # we'll just track the profile without trying to start the emulator
        if self.host_arch == 'arm64' and platform.system() == "Darwin":
            logger.info(f"Running on ARM Mac - skipping emulator start, just tracking profile change")
            # Update current profile
            self._save_current_profile(email, avd_name)
            if not avd_exists:
                logger.warning(f"AVD {avd_name} doesn't exist at {avd_path}. If using Android Studio AVDs, "
                             f"please run 'make register-avd' to update the AVD name for this profile.")
            return True, f"Switched profile tracking to {email} (AVD: {avd_name})"
            
        # For other platforms, try normal start procedure
        # Stop the current emulator if running
        if self.is_emulator_running():
            logger.info("Stopping current emulator")
            if not self.stop_emulator():
                return False, "Failed to stop current emulator"
        
        # Check if AVD exists before trying to start it
        if not avd_exists:
            logger.warning(f"AVD {avd_name} doesn't exist at {avd_path}. "
                         f"If using Android Studio AVDs, please run 'make register-avd' to update the AVD name.")
            # Still update the current profile for tracking
            self._save_current_profile(email, avd_name)
            return True, f"Tracked profile for {email} but AVD {avd_name} doesn't exist. Try running 'make register-avd'."
                
        # Start the new emulator
        logger.info(f"Starting emulator with AVD {avd_name}")
        if not self.start_emulator(avd_name):
            # If we can't start the emulator, we'll still update the current profile
            # so we can track which profile is current even if the emulator isn't running
            logger.warning(f"Failed to start emulator, but still tracking profile {email}")
            self._save_current_profile(email, avd_name)
            return True, f"Tracked profile for {email} but emulator failed to start. Try running manually with 'make run-emulator'"
            
        # Update current profile
        self._save_current_profile(email, avd_name)
        
        return True, f"Successfully switched to profile for {email}"
        
    def create_profile(self, email: str) -> Tuple[bool, str]:
        """
        Create a new profile for the given email without switching to it.
        
        Returns:
            Tuple[bool, str]: (success, message)
        """
        # Check if profile already exists
        if email in self.profiles_index:
            return True, f"Profile for {email} already exists"
            
        # Create new AVD
        success, result = self.create_new_avd(email)
        if not success:
            return False, f"Failed to create AVD: {result}"
            
        # Register profile
        self.register_profile(email, result)
        
        return True, f"Successfully created profile for {email}"
        
    def delete_profile(self, email: str) -> Tuple[bool, str]:
        """
        Delete the profile for the given email.
        
        Returns:
            Tuple[bool, str]: (success, message)
        """
        # Check if profile exists
        if email not in self.profiles_index:
            return False, f"No profile found for {email}"
            
        # Get AVD name
        avd_name = self.profiles_index[email]
        
        # Check if this is the current profile
        if self.current_profile and self.current_profile.get("email") == email:
            # Stop the emulator
            if self.is_emulator_running():
                if not self.stop_emulator():
                    return False, "Failed to stop current emulator"
                    
            # Clear current profile
            self.current_profile = None
            if os.path.exists(self.current_profile_file):
                os.remove(self.current_profile_file)
                
        # Delete AVD files
        avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
        avd_ini = os.path.join(self.avd_dir, f"{avd_name}.ini")
        
        if os.path.exists(avd_path):
            try:
                shutil.rmtree(avd_path)
            except Exception as e:
                logger.error(f"Error deleting AVD directory: {e}")
                return False, f"Failed to delete AVD directory: {str(e)}"
                
        if os.path.exists(avd_ini):
            try:
                os.remove(avd_ini)
            except Exception as e:
                logger.error(f"Error deleting AVD ini file: {e}")
                
        # Remove from profiles index
        del self.profiles_index[email]
        self._save_profiles_index()
        
        return True, f"Successfully deleted profile for {email}"