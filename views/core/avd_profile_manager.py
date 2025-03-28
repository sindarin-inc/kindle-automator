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
        self.emulator_map_file = os.path.join(self.profiles_dir, "emulator_device_map.json")
        self.android_home = os.environ.get("ANDROID_HOME", base_dir)
        
        # Detect host architecture
        self.host_arch = self._detect_host_architecture()
        logger.info(f"Detected host architecture: {self.host_arch}")
        
        # Ensure directories exist
        os.makedirs(self.profiles_dir, exist_ok=True)
        
        # Load profile index if it exists, otherwise create empty one
        self.profiles_index = self._load_profiles_index()
        self.current_profile = self._load_current_profile()
        self.emulator_map = self._load_emulator_map()
        
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
            
    def _load_emulator_map(self) -> Dict[str, str]:
        """
        Load the mapping between AVD names and emulator device IDs.
        
        Returns:
            Dict[str, str]: Dictionary mapping AVD names to emulator device IDs.
        """
        if os.path.exists(self.emulator_map_file):
            try:
                with open(self.emulator_map_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading emulator device map: {e}")
                return {}
        else:
            return {}
            
    def _save_current_profile(self, email: str, avd_name: str, emulator_id: Optional[str] = None) -> None:
        """
        Save current profile to JSON file.
        
        Args:
            email: Email address of the profile
            avd_name: Name of the AVD
            emulator_id: Optional emulator device ID (e.g., 'emulator-5554')
        """
        current = {
            "email": email,
            "avd_name": avd_name,
            "last_used": int(time.time())
        }
        
        # Add emulator ID if provided
        if emulator_id:
            current["emulator_id"] = emulator_id
            
            # Update emulator map
            self.emulator_map[avd_name] = emulator_id
            self._save_emulator_map()
            
        try:
            with open(self.current_profile_file, 'w') as f:
                json.dump(current, f, indent=2)
            self.current_profile = current
        except Exception as e:
            logger.error(f"Error saving current profile: {e}")
            
    def _save_emulator_map(self) -> None:
        """Save the emulator device map to JSON file."""
        try:
            with open(self.emulator_map_file, 'w') as f:
                json.dump(self.emulator_map, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving emulator device map: {e}")
    
    def get_avd_for_email(self, email: str) -> Optional[str]:
        """Get the AVD name for a given email address."""
        return self.profiles_index.get(email)
        
    def get_emulator_id_for_avd(self, avd_name: str) -> Optional[str]:
        """Get the emulator device ID for a given AVD name."""
        return self.emulator_map.get(avd_name)
        
    def get_emulator_id_for_email(self, email: str) -> Optional[str]:
        """Get the emulator device ID for a given email address."""
        avd_name = self.get_avd_for_email(email)
        if avd_name:
            return self.get_emulator_id_for_avd(avd_name)
        return None
        
    def map_running_emulators(self) -> Dict[str, str]:
        """
        Map running emulators to their device IDs.
        
        Returns:
            Dict[str, str]: Mapping of emulator names to device IDs
        """
        running_emulators = {}
        
        try:
            # Get list of running emulators with timeout
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.error(f"Error getting devices: {result.stderr}")
                return running_emulators
                
            # Parse output to get emulator IDs
            lines = result.stdout.strip().split('\n')
            for line in lines[1:]:  # Skip the first line which is the header
                if not line.strip():
                    continue
                    
                parts = line.split('\t')
                if len(parts) >= 2 and 'emulator' in parts[0]:
                    emulator_id = parts[0].strip()
                    
                    # Get the port number from the emulator ID
                    try:
                        port = int(emulator_id.split('-')[1])
                        
                        # Query emulator for AVD name with timeout
                        avd_name = self._get_avd_name_for_emulator(emulator_id)
                        if avd_name:
                            running_emulators[avd_name] = emulator_id
                        else:
                            # If we couldn't get the AVD name but we know an emulator is running,
                            # check if it matches our current profile's emulator
                            if self.current_profile and self.current_profile.get("avd_name"):
                                current_avd = self.current_profile.get("avd_name")
                                current_emu_id = self.current_profile.get("emulator_id")
                                
                                # If we have a matching emulator ID, use that mapping
                                if current_emu_id == emulator_id:
                                    logger.info(f"Using known mapping for current profile: {current_avd} -> {emulator_id}")
                                    running_emulators[current_avd] = emulator_id
                                
                    except Exception as e:
                        logger.error(f"Error parsing emulator ID {emulator_id}: {e}")
                        
            # Log emulator mapping results for debugging
            if running_emulators:
                logger.info(f"Found running emulators: {running_emulators}")
            else:
                logger.info("No running emulators found")
                
            return running_emulators
        except subprocess.TimeoutExpired:
            logger.warning("Timeout mapping running emulators")
            return running_emulators
        except Exception as e:
            logger.error(f"Error mapping running emulators: {e}")
            return running_emulators
            
    def _get_avd_name_for_emulator(self, emulator_id: str) -> Optional[str]:
        """
        Get the AVD name for a running emulator.
        
        Args:
            emulator_id: The emulator device ID (e.g., 'emulator-5554')
            
        Returns:
            Optional[str]: The AVD name or None if not found
        """
        try:
            # First check our existing emulator map to avoid ADB calls if possible
            for avd_name, mapped_id in self.emulator_map.items():
                if mapped_id == emulator_id:
                    logger.info(f"Found AVD {avd_name} in existing map for emulator {emulator_id}")
                    return avd_name
            
            # Use adb to get the AVD name via shell getprop with a short timeout
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "avd", "name"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2  # Very short timeout to avoid hanging
            )
            
            if result.returncode == 0 and result.stdout.strip():
                avd_name = result.stdout.strip()
                logger.info(f"Got AVD name {avd_name} directly from emulator {emulator_id}")
                return avd_name
                
            # Alternative approach - try to get product.device property with short timeout
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "shell", "getprop", "ro.build.product"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0 and result.stdout.strip():
                # This gives us the device name (e.g., 'pixel'), not the AVD name
                device_name = result.stdout.strip()
                logger.info(f"Got device name {device_name} for emulator {emulator_id}")
                
                # Look in our profiles index to find matches
                for email, avd_name in self.profiles_index.items():
                    if device_name.lower() in avd_name.lower():
                        logger.info(f"Matched AVD {avd_name} for device {device_name}")
                        return avd_name
                
                # If not found in profiles, try emulator map
                for avd_name in self.emulator_map:
                    if device_name.lower() in avd_name.lower():
                        logger.info(f"Matched AVD {avd_name} from emulator map for device {device_name}")
                        return avd_name
                        
                # If we still can't find it but there's only one profile, use that
                if len(self.profiles_index) == 1:
                    avd_name = next(iter(self.profiles_index.values()))
                    logger.info(f"Using only available AVD {avd_name} for emulator {emulator_id}")
                    return avd_name
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout getting AVD name for emulator {emulator_id}")
        except Exception as e:
            logger.error(f"Error getting AVD name for emulator {emulator_id}: {e}")
            
        return None
            
    def update_emulator_mappings(self) -> None:
        """Update mappings between AVD names and running emulator IDs."""
        running_emulators = self.map_running_emulators()
        
        # Update emulator map with running emulators
        if running_emulators:
            for avd_name, emulator_id in running_emulators.items():
                self.emulator_map[avd_name] = emulator_id
                
            self._save_emulator_map()
            logger.info(f"Updated emulator mappings: {running_emulators}")
        
    def list_profiles(self) -> List[Dict]:
        """List all available profiles with their details."""
        # First update emulator mappings to ensure they're current
        self.update_emulator_mappings()
        
        result = []
        for email, avd_name in self.profiles_index.items():
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            emulator_id = self.get_emulator_id_for_avd(avd_name)
            
            profile_info = {
                "email": email,
                "avd_name": avd_name,
                "exists": os.path.exists(avd_path),
                "current": self.current_profile and self.current_profile.get("email") == email,
                "emulator_id": emulator_id
            }
            
            result.append(profile_info)
        return result
        
    def get_current_profile(self) -> Optional[Dict]:
        """Get information about the currently active profile."""
        if self.current_profile:
            # Ensure emulator ID is up to date
            avd_name = self.current_profile.get("avd_name")
            if avd_name:
                emulator_id = self.get_emulator_id_for_avd(avd_name)
                if emulator_id and emulator_id != self.current_profile.get("emulator_id"):
                    # Update with current emulator ID
                    self.current_profile["emulator_id"] = emulator_id
                    
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
            # Execute with a shorter timeout
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5  # Add a timeout to prevent potential hang
            )
            
            # More precise check - look for "emulator-" followed by a port number
            if result.returncode == 0:
                return any(line.strip().startswith("emulator-") for line in result.stdout.splitlines())
            return False
        except subprocess.TimeoutExpired:
            logger.warning("Timeout expired while checking if emulator is running, assuming it's not running")
            return False
        except Exception as e:
            logger.error(f"Error checking if emulator is running: {e}")
            return False
            
    def is_emulator_ready(self) -> bool:
        """Check if an emulator is running and fully booted."""
        try:
            # First check if any device is connected with a short timeout
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # More precise check for emulator
            has_emulator = False
            for line in devices_result.stdout.splitlines():
                # Looking for "emulator-XXXX device"
                if line.strip().startswith("emulator-") and "device" in line and not "offline" in line:
                    has_emulator = True
                    break
                
            if not has_emulator:
                return False
                
            # Check if boot is completed with a timeout
            boot_completed = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "shell", "getprop", "sys.boot_completed"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            return boot_completed.stdout.strip() == "1"
        except subprocess.TimeoutExpired:
            logger.warning("Timeout expired while checking if emulator is ready, assuming it's not ready")
            return False 
        except Exception as e:
            logger.error(f"Error checking if emulator is ready: {e}")
            return False
            
    def stop_emulator(self) -> bool:
        """Stop the currently running emulator."""
        try:
            # First do a quick check if emulator is actually running
            if not self.is_emulator_running():
                logger.info("No emulator running, nothing to stop")
                return True
                
            # First try graceful shutdown with shorter timeout
            logger.info("Attempting graceful emulator shutdown")
            subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "emu", "kill"],
                check=False,
                timeout=5
            )
            
            # Wait for emulator to shut down with shorter timeout
            deadline = time.time() + 10  # Reduced from 30 to 10 seconds
            start_time = time.time()
            while time.time() < deadline:
                # Check more frequently
                time.sleep(0.5)
                if not self.is_emulator_running():
                    elapsed = time.time() - start_time
                    logger.info(f"Emulator shut down gracefully in {elapsed:.2f} seconds")
                    return True
                
            # Try killing specific emulator processes rather than all emulator processes
            logger.info("Graceful shutdown timed out, trying forceful termination")
            try:
                # Get list of running emulators to kill specifically
                result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                
                # Parse out emulator IDs and kill them specifically
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:  # Skip header
                    if not line.strip():
                        continue
                    parts = line.split('\t')
                    if len(parts) >= 2 and 'emulator' in parts[0]:
                        emulator_id = parts[0].strip()
                        logger.info(f"Killing specific emulator: {emulator_id}")
                        subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "kill"],
                            check=False,
                            timeout=3
                        )
            except Exception as inner_e:
                logger.warning(f"Error during specific emulator kill: {inner_e}")
                        
            # Force kill as last resort with pkill
            subprocess.run(
                ["pkill", "-f", "emulator"],
                check=False,
                timeout=3
            )
            
            # Final check
            time.sleep(1)
            if not self.is_emulator_running():
                logger.info("Emulator forcibly terminated")
                return True
            else:
                logger.warning("Failed to completely terminate emulator processes")
                return False
        except Exception as e:
            logger.error(f"Error stopping emulator: {e}")
            return False
            
    def _force_cleanup_emulators(self):
        """Force kill all emulator processes and reset adb."""
        logger.warning("Force cleaning up any running emulators")
        try:
            # Kill all emulator processes forcefully
            subprocess.run(["pkill", "-9", "-f", "emulator"], check=False, timeout=5)
            
            # Kill all qemu processes too
            subprocess.run(["pkill", "-9", "-f", "qemu"], check=False, timeout=5)
            
            # Force reset adb server
            subprocess.run([f"{self.android_home}/platform-tools/adb", "kill-server"], 
                        check=False, timeout=5)
            time.sleep(1)
            subprocess.run([f"{self.android_home}/platform-tools/adb", "start-server"], 
                        check=False, timeout=5)
            
            logger.info("Emulator cleanup completed")
            return True
        except Exception as e:
            logger.error(f"Error during emulator cleanup: {e}")
            return False
    
    def start_emulator(self, avd_name: str) -> bool:
        """
        Start the specified AVD in headless mode.
        
        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        try:
            # First check if an emulator is already running but do it efficiently
            if self.is_emulator_running():
                # Only stop if it's a different AVD than the one we want to start
                running_avds = self.map_running_emulators()
                if avd_name in running_avds:
                    logger.info(f"Emulator for requested AVD {avd_name} is already running, skipping stop/start")
                    # Double-check it's ready
                    if self.is_emulator_ready():
                        logger.info("Emulator is ready, using existing instance")
                        return True
                    logger.info("Emulator is running but not ready, will restart it")
                
                logger.warning("A different emulator is running, stopping it first")
                start_time = time.time()
                if not self.stop_emulator():
                    logger.error("Failed to stop existing emulator")
                    return False
                elapsed = time.time() - start_time
                logger.info(f"Emulator stop operation completed in {elapsed:.2f} seconds")
                    
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
            
            # Wait for emulator to boot with more frequent checks and shorter timeout
            logger.info("Waiting for emulator to boot...")
            deadline = time.time() + 60  # 60 seconds total timeout
            last_progress_time = time.time()
            device_found = False
            no_progress_timeout = 30  # 30 seconds with no progress triggers termination
            check_interval = 2  # Check every 2 seconds
            
            while time.time() < deadline:
                try:
                    # First check if the device is visible to adb
                    if not device_found:
                        devices_result = subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "devices"],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3
                        )
                        if "emulator" in devices_result.stdout:
                            logger.info("Emulator device detected by adb, waiting for boot to complete...")
                            device_found = True
                            last_progress_time = time.time()
                    
                    # Check if boot is completed
                    boot_completed = subprocess.run(
                        [f"{self.android_home}/platform-tools/adb", "shell", "getprop", "sys.boot_completed"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    
                    # If we get any response, even if not "1", update progress time
                    if boot_completed.stdout:
                        logger.debug(f"Boot progress: [{boot_completed.stdout.strip()}]")
                        last_progress_time = time.time()
                        
                    # Only consider boot complete when we get "1"
                    if boot_completed.stdout.strip() == "1":
                        logger.info("Emulator booted successfully")
                        
                        # Additional verification - check for package manager
                        try:
                            pm_check = subprocess.run(
                                [f"{self.android_home}/platform-tools/adb", "shell", "pm", "list", "packages", "|", "grep", "amazon.kindle"],
                                check=False,
                                capture_output=True,
                                text=True,
                                timeout=3
                            )
                            if "amazon.kindle" in pm_check.stdout:
                                logger.info("Kindle package confirmed to be installed")
                            else:
                                logger.warning("Emulator booted but Kindle package not found. Will proceed anyway.")
                        except Exception as e:
                            logger.warning(f"Error checking for Kindle package: {e}")
                            
                        # Allow a bit more time for system services to stabilize
                        logger.info("Waiting 2 seconds for system services to stabilize...")
                        time.sleep(2)
                        return True
                        
                except Exception as e:
                    # Log but continue polling
                    logger.debug(f"Exception during boot check: {e}")
                    
                # Check for no progress with the shorter timeout
                elapsed_since_progress = time.time() - last_progress_time
                if elapsed_since_progress > no_progress_timeout:
                    logger.warning(f"No progress detected for {elapsed_since_progress:.1f} seconds, cleaning up emulator")
                    
                    # Terminate the emulator process
                    try:
                        process.terminate()
                    except Exception as term_e:
                        logger.warning(f"Error terminating process: {term_e}")
                        
                    # Force cleanup all emulators
                    self._force_cleanup_emulators()
                    return False
                
                # Sleep for a shorter time between checks
                time.sleep(check_interval)
            
            # If we get here, we timed out without booting successfully
            logger.error("Emulator boot timed out after 60 seconds")
            
            # Terminate the emulator process
            try:
                process.terminate()
            except:
                pass
                
            # Force cleanup all emulators
            self._force_cleanup_emulators()
            return False
            
            # Check if process exited with architecture error
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
            
    def switch_profile(self, email: str, force_new_emulator: bool = False) -> Tuple[bool, str]:
        """
        Switch to the profile for the given email.
        If the profile doesn't exist, create a new one.
        
        Args:
            email: The email address to switch to
            force_new_emulator: If True, always stop any running emulator and start a new one
                               (used with recreate=1 flag)
        
        Returns:
            Tuple[bool, str]: (success, message)
        """
        logger.info(f"Switching to profile for email: {email} (force_new_emulator={force_new_emulator})")
        
        # If force_new_emulator is True, stop any running emulator first
        if force_new_emulator:
            logger.info("Force new emulator requested, stopping any running emulator")
            if self.is_emulator_running():
                if not self.stop_emulator():
                    logger.error("Failed to stop existing emulator")
                    # We'll try to continue anyway
        
        # Check if this is already the current profile
        if self.current_profile and self.current_profile.get("email") == email and not force_new_emulator:
            logger.info(f"Already using profile for {email}")
            
            # If an emulator is already running and ready, just use it
            if self.is_emulator_ready():
                logger.info(f"Emulator already running and ready for profile {email}")
                return True, f"Already using profile for {email} with running emulator"
            else:
                # Attempt to start the emulator for this profile
                avd_name = self.current_profile.get("avd_name")
                if avd_name:
                    logger.info(f"Emulator not ready for profile {email}, attempting to start it")
                    if self.start_emulator(avd_name):
                        logger.info(f"Successfully started emulator for profile {email}")
                        return True, f"Started emulator for profile {email}"
                
            # Otherwise continue with normal profile switch
            logger.info(f"Emulator not ready for profile {email}, proceeding with normal switch")
            
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
        
        # Check if emulator is already running and ready
        emulator_ready = self.is_emulator_ready()
        
        # For Mac M1/M2/M4 users where direct emulator launch might fail,
        # we'll just track the profile without trying to start the emulator
        if self.host_arch == 'arm64' and platform.system() == "Darwin":
            logger.info(f"Running on ARM Mac - skipping emulator start, just tracking profile change")
            # Update current profile
            self._save_current_profile(email, avd_name)
            
            if emulator_ready:
                logger.info(f"Found running emulator that appears ready, will use it for profile {email}")
                return True, f"Switched to profile {email} with existing running emulator"
                
            if not avd_exists:
                logger.warning(f"AVD {avd_name} doesn't exist at {avd_path}. If using Android Studio AVDs, "
                             f"please run 'make register-avd' to update the AVD name for this profile.")
            return True, f"Switched profile tracking to {email} (AVD: {avd_name})"
            
        # For other platforms, try normal start procedure
        # Stop the current emulator if running, but only if not already ready
        if not emulator_ready and self.is_emulator_running():
            logger.info("Stopping current emulator")
            if not self.stop_emulator():
                return False, "Failed to stop current emulator"
        
        # If emulator is already running and ready, check if we should use it
        if emulator_ready and not force_new_emulator:
            # We need to verify this emulator belongs to the correct AVD
            running_avds = self.map_running_emulators()
            if avd_name in running_avds:
                logger.info(f"Using already running emulator for profile {email} - confirmed to be correct AVD")
                self._save_current_profile(email, avd_name)
                return True, f"Switched to profile {email} with existing running emulator (verified)"
            else:
                logger.warning(f"Found running emulator but it doesn't match the expected AVD {avd_name}")
                logger.info(f"Stopping unrelated emulator to start the correct one")
                if not self.stop_emulator():
                    logger.error("Failed to stop unrelated emulator")
                    # We'll try to continue anyway
        
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
            # If we can't start the emulator, we should check if any are running and handle appropriately
            if self.is_emulator_running():
                if force_new_emulator:
                    # If we need a fresh emulator, forcibly kill any running ones
                    logger.warning(f"Failed to start new emulator for {avd_name} and force_new_emulator=True")
                    logger.warning("Forcibly terminating any running emulators")
                    
                    # Force kill all emulator processes
                    try:
                        # Kill all emulator processes forcefully
                        subprocess.run(["pkill", "-9", "-f", "emulator"], check=False, timeout=5)
                        
                        # Kill all qemu processes too
                        subprocess.run(["pkill", "-9", "-f", "qemu"], check=False, timeout=5)
                        
                        # Force reset adb server 
                        subprocess.run([f"{self.android_home}/platform-tools/adb", "kill-server"], 
                                    check=False, timeout=5)
                        time.sleep(1)
                        subprocess.run([f"{self.android_home}/platform-tools/adb", "start-server"], 
                                    check=False, timeout=5)
                        
                        logger.warning("Forcibly terminated all emulator processes")
                    except Exception as cleanup_e:
                        logger.error(f"Error during emergency cleanup: {cleanup_e}")
                    
                    # Cannot continue with force_new_emulator if we can't clean everything up
                    logger.warning(f"Emulator start failed, tracking profile {email} but fresh emulator required - manual intervention needed")
                    
                elif not force_new_emulator:
                    # Only in non-force mode, we might consider using an existing emulator
                    # Check if it's the correct AVD for this email
                    running_avds = self.map_running_emulators()
                    if avd_name in running_avds:
                        logger.warning(f"Failed to start new emulator but found correct running AVD {avd_name}. Will use it for {email}")
                        self._save_current_profile(email, avd_name)
                        # Try to verify the emulator is actually ready
                        if self.is_emulator_ready():
                            logger.info(f"Existing emulator is ready, using it for profile {email}")
                            return True, f"Switched to profile {email} with existing running emulator (verified)"
                    else:
                        logger.warning(f"Failed to start emulator for {avd_name} and found unrelated running emulator")
                        # For safety, we should not use an unrelated emulator's data
                        logger.info(f"Forcing emulator shutdown to prevent data mixing")
                        self.stop_emulator()
                        logger.warning(f"Emulator start failed, but still tracking profile {email} - manual intervention needed")
            
            # Update current profile even if emulator couldn't start
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