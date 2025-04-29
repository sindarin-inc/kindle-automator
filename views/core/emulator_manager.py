import logging
import os
import platform
import subprocess
import time

logger = logging.getLogger(__name__)


class EmulatorManager:
    """
    Manages the lifecycle of Android emulators.
    Handles starting, stopping, and monitoring emulator instances.
    """

    def __init__(self, android_home, avd_dir, host_arch, use_simplified_mode=False):
        self.android_home = android_home
        self.avd_dir = avd_dir
        self.host_arch = host_arch
        self.use_simplified_mode = use_simplified_mode

    def is_emulator_running(self) -> bool:
        """Check if an emulator is currently running."""
        try:
            # Execute with a shorter timeout
            result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,  # Add a timeout to prevent potential hang
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
                timeout=5,
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
                timeout=5,
            )

            return boot_completed.stdout.strip() == "1"
        except subprocess.TimeoutExpired:
            logger.warning("Timeout expired while checking if emulator is ready, assuming it's not ready")
            return False
        except Exception as e:
            logger.error(f"Error checking if emulator is ready: {e}")
            return False

    def _force_cleanup_emulators(self):
        """Force kill all emulator processes and reset adb."""
        logger.warning("Force cleaning up any running emulators")
        try:
            # Kill all emulator processes forcefully
            subprocess.run(["pkill", "-9", "-f", "emulator"], check=False, timeout=5)

            # Kill all qemu processes too
            subprocess.run(["pkill", "-9", "-f", "qemu"], check=False, timeout=5)

            # No longer force resetting adb server as it can cause issues
            logger.info("Skipping ADB server reset during cleanup")

            logger.info("Emulator cleanup completed")
            return True
        except Exception as e:
            logger.error(f"Error during emulator cleanup: {e}")
            return False

    def _check_running_emulators(self, target_avd_name: str = None) -> dict:
        """
        Check for running emulators and their status.

        Args:
            target_avd_name: Optional AVD name we're looking for

        Returns:
            dict: Status of running emulators, including matching and other emulators
        """
        result = {"any_emulator_running": False, "matching_emulator_id": None, "other_emulators": []}

        try:
            # Get list of running emulators from device discovery
            from views.core.device_discovery import DeviceDiscovery

            device_discovery = DeviceDiscovery(self.android_home, self.avd_dir)
            running_emulators = device_discovery.map_running_emulators()
            logger.info(f"Found running emulators: {running_emulators}")

            if running_emulators:
                result["any_emulator_running"] = True

                # Check if our target AVD is running
                if target_avd_name and target_avd_name in running_emulators:
                    result["matching_emulator_id"] = running_emulators[target_avd_name]

                # Identify other running emulators
                for avd_name, emulator_id in running_emulators.items():
                    if not target_avd_name or avd_name != target_avd_name:
                        result["other_emulators"].append(emulator_id)

            return result

        except Exception as e:
            logger.error(f"Error checking running emulators: {e}")
            return result

    def _is_specific_emulator_ready(self, emulator_id: str) -> bool:
        """
        Check if a specific emulator is ready.

        Args:
            emulator_id: The emulator ID to check (e.g. emulator-5554)

        Returns:
            bool: True if the emulator is ready, False otherwise
        """
        try:
            # First check if the device is connected
            devices_result = subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            device_connected = False
            for line in devices_result.stdout.strip().split("\n"):
                if emulator_id in line and "device" in line and not "offline" in line:
                    device_connected = True
                    break

            if not device_connected:
                logger.warning(f"Emulator {emulator_id} not found in connected devices")
                return False

            # Check boot completed with specific emulator ID
            boot_completed = subprocess.run(
                [
                    f"{self.android_home}/platform-tools/adb",
                    "-s",
                    emulator_id,
                    "shell",
                    "getprop",
                    "sys.boot_completed",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )

            logger.info(f"Boot check for {emulator_id}: [{boot_completed.stdout.strip()}]")
            return boot_completed.stdout.strip() == "1"

        except Exception as e:
            logger.error(f"Error checking if emulator {emulator_id} is ready: {e}")
            return False

    def stop_specific_emulator(self, emulator_id: str) -> bool:
        """
        Stop a specific emulator by ID. Public method for external use.

        Args:
            emulator_id: The emulator ID to stop (e.g. emulator-5554)

        Returns:
            bool: True if successful, False otherwise
        """
        return self._stop_specific_emulator(emulator_id)

    def _stop_specific_emulator(self, emulator_id: str) -> bool:
        """
        Stop a specific emulator by ID. Internal implementation.

        Args:
            emulator_id: The emulator ID to stop (e.g. emulator-5554)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Stopping specific emulator: {emulator_id}")

            # First try graceful shutdown
            subprocess.run(
                [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "kill"],
                check=False,
                timeout=5,
            )

            # Wait briefly for emulator to shut down
            for i in range(10):
                devices_result = subprocess.run(
                    [f"{self.android_home}/platform-tools/adb", "devices"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if emulator_id not in devices_result.stdout:
                    logger.info(f"Emulator {emulator_id} stopped successfully")
                    return True

                logger.info(f"Waiting for emulator {emulator_id} to stop... ({i+1}/10)")
                time.sleep(1)

            # If still running, force kill
            logger.warning(f"Emulator {emulator_id} didn't stop gracefully, forcing termination")
            return False

        except Exception as e:
            logger.error(f"Error stopping emulator {emulator_id}: {e}")
            return False

    def stop_emulator(self) -> bool:
        """Stop the currently running emulator."""
        # Always preserve emulators when server is stopping
        if self.use_simplified_mode:
            logger.info("Always preserving emulators in simplified mode for faster reconnection")
            return True

        try:
            # First do a quick check if emulator is actually running
            if not self.is_emulator_running():
                logger.info("No emulator running, nothing to stop")
                return True

            # First try graceful shutdown with shorter timeout
            logger.info("Attempting graceful emulator shutdown")
            subprocess.run([f"{self.android_home}/platform-tools/adb", "emu", "kill"], check=False, timeout=5)

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
                    timeout=3,
                )

                # Parse out emulator IDs and kill them specifically
                lines = result.stdout.strip().split("\n")
                for line in lines[1:]:  # Skip header
                    if not line.strip():
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2 and "emulator" in parts[0]:
                        emulator_id = parts[0].strip()
                        logger.info(f"Killing specific emulator: {emulator_id}")
                        subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "-s", emulator_id, "emu", "kill"],
                            check=False,
                            timeout=3,
                        )
            except Exception as inner_e:
                logger.warning(f"Error during specific emulator kill: {inner_e}")

            # Force kill as last resort with pkill
            subprocess.run(["pkill", "-f", "emulator"], check=False, timeout=3)

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

    def start_emulator(self, avd_name: str) -> bool:
        """
        Start the specified AVD in headless mode.

        Returns:
            bool: True if emulator started successfully, False otherwise
        """
        try:
            # First check if the AVD actually exists
            avd_path = os.path.join(self.avd_dir, f"{avd_name}.avd")
            if not os.path.exists(avd_path):
                logger.error(f"Cannot start emulator: AVD {avd_name} does not exist at {avd_path}")
                return False

            # First check if emulators are already running and log the status
            current_emulator_state = self._check_running_emulators(avd_name)

            # Check for matching running emulator
            if current_emulator_state["matching_emulator_id"]:
                logger.info(
                    f"Emulator for requested AVD {avd_name} is already running with ID: {current_emulator_state['matching_emulator_id']}"
                )

                # Double-check it's ready
                if self._is_specific_emulator_ready(current_emulator_state["matching_emulator_id"]):
                    logger.info(
                        f"Emulator {current_emulator_state['matching_emulator_id']} is ready, using existing instance"
                    )
                    return True

                logger.info(
                    f"Emulator {current_emulator_state['matching_emulator_id']} is running but not ready, will restart it"
                )

            # If we have other emulators running, stop them before continuing
            if current_emulator_state["other_emulators"]:
                logger.warning(
                    f"Found {len(current_emulator_state['other_emulators'])} other emulator(s) running, stopping them first"
                )
                for emu_id in current_emulator_state["other_emulators"]:
                    logger.info(f"Stopping unrelated emulator: {emu_id}")
                    self._stop_specific_emulator(emu_id)

            # If any emulators are still running, do a full stop
            if self.is_emulator_running():
                logger.warning("Still have running emulators, performing full emulator stop")
                start_time = time.time()
                if not self.stop_emulator():
                    logger.error("Failed to stop existing emulators")
                    return False
                elapsed = time.time() - start_time
                logger.info(f"Emulator stop operation completed in {elapsed:.2f} seconds")

            # Always force x86_64 architecture for all hosts
            config_path = os.path.join(self.avd_dir, f"{avd_name}.avd", "config.ini")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config_content = f.read()

                    # Force x86_64 for all hosts
                    if "arm64" in config_content:
                        logger.warning("Found arm64 architecture in AVD. Changing to x86_64...")
                        # Use AVD Creator to reconfigure
                        from views.core.avd_creator import AVDCreator

                        avd_creator = AVDCreator(self.android_home, self.avd_dir, self.host_arch)
                        avd_creator._configure_avd(avd_name)  # Force reconfiguration to x86_64
                except Exception as e:
                    logger.error(f"Error checking AVD compatibility: {e}")

            # Set environment variables
            env = os.environ.copy()
            env["ANDROID_SDK_ROOT"] = self.android_home
            env["ANDROID_AVD_HOME"] = self.avd_dir
            env["ANDROID_HOME"] = self.android_home

            # Set DISPLAY for VNC if we're on Linux
            if platform.system() != "Darwin":
                # Default to display :1
                display_num = 1
                
                # Try to get assigned display number for this profile if email is available
                if email:
                    try:
                        from server.utils.vnc_instance_manager import VNCInstanceManager
                        vnc_manager = VNCInstanceManager()
                        profile_display = vnc_manager.get_x_display(email)
                        if profile_display:
                            display_num = profile_display
                            logger.info(f"Using assigned display :{display_num} for profile {email}")
                    except ImportError:
                        logger.warning("VNCInstanceManager not available, will use default display :1")
                
                env["DISPLAY"] = f":{display_num}"
                logger.info(f"Setting DISPLAY={env['DISPLAY']} for VNC")

            # Check if we're on a headless server with VNC
            # First check for profile-specific VNC launcher script
            profile_vnc_launcher = None
            
            # Try to get email from AVD name using DeviceDiscovery
            from views.core.device_discovery import DeviceDiscovery
            device_discovery = DeviceDiscovery(self.android_home, self.avd_dir)
            email = device_discovery.extract_email_from_avd_name(avd_name)
            
            if email:
                # Import VNCInstanceManager to get profile-specific launcher
                try:
                    from server.utils.vnc_instance_manager import VNCInstanceManager
                    vnc_manager = VNCInstanceManager()
                    
                    # Try to get existing VNC instance for this profile
                    profile_vnc_launcher = vnc_manager.get_launcher_script(email)
                    
                    if profile_vnc_launcher:
                        logger.info(f"Using profile-specific VNC launcher for {email}: {profile_vnc_launcher}")
                except ImportError:
                    logger.warning("VNCInstanceManager not available, will use default VNC launcher")
                    
            # Fallback to default VNC launcher if no profile-specific launcher found
            default_vnc_launcher = "/usr/local/bin/vnc-emulator-launcher.sh"
            vnc_launcher = profile_vnc_launcher or default_vnc_launcher
            use_vnc = os.path.exists(vnc_launcher) and platform.system() != "Darwin"
            
            # Log which launcher we're using
            if profile_vnc_launcher:
                logger.info(f"Using profile-specific VNC launcher for {email}: {profile_vnc_launcher}")
            elif use_vnc:
                logger.info(f"Using default VNC launcher: {default_vnc_launcher}")

            # Build emulator command with architecture-specific options
            if use_vnc:
                # Use the VNC launcher script for headless server
                logger.info(f"Using VNC-enabled emulator launcher for AVD {avd_name}")
                emulator_cmd = [
                    vnc_launcher,  # VNC launcher script
                    "-avd",
                    avd_name,
                    "-no-audio",
                    "-writable-system",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-port",
                    "5554",
                ]
            elif self.host_arch == "arm64":
                # For ARM Macs, try to use a different approach
                # Use arch command to force x86_64 mode via Rosetta 2
                emulator_cmd = [
                    "arch",
                    "-x86_64",
                    f"{self.android_home}/emulator/emulator",
                    "-avd",
                    avd_name,
                    "-no-audio",
                    "-no-boot-anim",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-writable-system",
                    "-feature",
                    "-HVF",  # Disable Hardware Virtualization
                    "-accel",
                    "off",
                ]

                logger.info("Using arch -x86_64 to run the emulator through Rosetta 2 on ARM Mac")
            else:
                # For x86_64 hosts (Linux servers), use standard command
                emulator_cmd = [
                    f"{self.android_home}/emulator/emulator",
                    "-avd",
                    avd_name,
                    "-no-audio",
                    "-no-boot-anim",
                    "-no-metrics",
                    "-gpu",
                    "swiftshader_indirect",
                    "-no-snapshot",
                    "-no-snapshot-load",
                    "-no-snapshot-save",
                    "-writable-system",
                    "-accel",
                    "on",  # Use hardware acceleration if available
                    "-feature",
                    "HVF",  # Hardware Virtualization Features
                    "-feature",
                    "KVM",  # Enable KVM (Linux)
                ]

            # Force a specific port to avoid conflicts with multiple emulators
            emulator_cmd.extend(["-port", "5554"])

            # Start emulator in background
            logger.info(f"Starting emulator with AVD {avd_name}")
            logger.info(f"Using command: {' '.join(emulator_cmd)}")

            process = subprocess.Popen(emulator_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Wait for emulator to boot with more frequent checks
            logger.info("Waiting for emulator to boot...")
            deadline = time.time() + 120  # 120 seconds total timeout
            last_progress_time = time.time()
            device_found = False
            expected_emulator_id = "emulator-5554"  # We specified port 5554 above
            boot_check_attempts = 0
            no_progress_timeout = 60  # 60 seconds with no progress triggers termination (increased from 30)
            check_interval = 1  # Check every 1 second (more frequent checks)

            while time.time() < deadline:
                boot_check_attempts += 1
                logger.info(
                    f"Emulator boot check attempt #{boot_check_attempts}, elapsed: {int(time.time() - last_progress_time)}s"
                )

                try:
                    # First check if the device is visible to adb
                    if not device_found:
                        devices_result = subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "devices"],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        logger.info(f"ADB devices output: {devices_result.stdout.strip()}")

                        if expected_emulator_id in devices_result.stdout:
                            logger.info(
                                f"Emulator device {expected_emulator_id} detected by adb, waiting for boot to complete..."
                            )
                            device_found = True
                            last_progress_time = time.time()
                        elif "emulator" in devices_result.stdout:
                            logger.info(
                                f"Some emulator device detected, but not our expected {expected_emulator_id}"
                            )

                            # Parse the device list to get all emulator IDs
                            other_emulators = []
                            for line in devices_result.stdout.strip().split("\n"):
                                if "emulator-" in line and "device" in line:
                                    emulator_id = line.split("\t")[0].strip()
                                    other_emulators.append(emulator_id)

                            if other_emulators:
                                logger.warning(f"Found unexpected emulators: {other_emulators}")
                                device_found = True  # We'll try to use what we found
                                last_progress_time = time.time()
                                expected_emulator_id = other_emulators[0]  # Use the first one

                                # Update the mapping with what we found
                                logger.info(f"Will use existing emulator {expected_emulator_id}")
                                # No longer tracking emulator map

                    # Use the expected (or found) emulator ID for all further commands
                    if device_found:
                        # Check boot_completed with specific emulator ID
                        boot_completed = subprocess.run(
                            [
                                f"{self.android_home}/platform-tools/adb",
                                "-s",
                                expected_emulator_id,
                                "shell",
                                "getprop",
                                "sys.boot_completed",
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )

                        if boot_check_attempts % 10 == 0:
                            logger.info(
                                f"Boot progress for {expected_emulator_id} (sys.boot_completed): [{boot_completed.stdout.strip()}] [{boot_completed.stderr.strip()}]"
                            )

                        # If we get any response, even if not "1", update progress time
                        if boot_completed.stdout.strip():
                            last_progress_time = time.time()

                        # Check boot animation with specific emulator ID
                        boot_anim = subprocess.run(
                            [
                                f"{self.android_home}/platform-tools/adb",
                                "-s",
                                expected_emulator_id,
                                "shell",
                                "getprop",
                                "init.svc.bootanim",
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )

                        if boot_check_attempts % 10 == 0:
                            logger.info(
                                f"Boot animation for {expected_emulator_id}: [{boot_anim.stdout.strip()}] [{boot_anim.stderr.strip()}]"
                            )

                        if boot_anim.stdout.strip():
                            last_progress_time = time.time()

                            # 'stopped' means the boot animation has finished
                            if boot_anim.stdout.strip() == "stopped":
                                logger.info(
                                    f"Boot animation on {expected_emulator_id} has stopped, emulator is likely almost ready"
                                )

                        # Check if launcher is ready with specific emulator ID
                        try:
                            launcher_check = subprocess.run(
                                [
                                    f"{self.android_home}/platform-tools/adb",
                                    "-s",
                                    expected_emulator_id,
                                    "shell",
                                    "pidof",
                                    "com.android.launcher3",
                                ],
                                check=False,
                                capture_output=True,
                                text=True,
                                timeout=2,
                            )

                            if boot_check_attempts % 10 == 0:
                                logger.info(
                                    f"Launcher check for {expected_emulator_id}: [{launcher_check.stdout.strip()}] [{launcher_check.stderr.strip()}]"
                                )

                            if launcher_check.stdout.strip():
                                logger.info(f"Launcher is running on {expected_emulator_id}")
                                last_progress_time = time.time()
                        except Exception as launcher_e:
                            logger.warning(f"Launcher check failed: {launcher_e}")

                        # Only consider boot complete when we get "1" for sys.boot_completed
                        if boot_completed.stdout.strip() == "1":
                            logger.info(f"Emulator {expected_emulator_id} booted successfully")

                            # If we're using VNC, log the connection info
                            if use_vnc:
                                logger.info("VNC server is available for captcha solving")
                                logger.info(
                                    "Connect to the server's IP address on port 5900 using any VNC client"
                                )
                                logger.info("For web access: http://SERVER_IP:6080/vnc.html")
                                logger.info(
                                    "For mobile app integration: http://SERVER_IP:6080/kindle_captcha.html?password=PASSWORD&autoconnect=true"
                                )

                            # Additional verification - check for package manager
                            try:
                                pm_check = subprocess.run(
                                    [
                                        f"{self.android_home}/platform-tools/adb",
                                        "-s",
                                        expected_emulator_id,
                                        "shell",
                                        "pm",
                                        "list",
                                        "packages",
                                        "|",
                                        "grep",
                                        "amazon.kindle",
                                    ],
                                    check=False,
                                    capture_output=True,
                                    text=True,
                                    timeout=3,
                                )

                                logger.info(
                                    f"Package check for {expected_emulator_id}: [{pm_check.stdout.strip()}] [{pm_check.stderr.strip()}]"
                                )

                                if "amazon.kindle" in pm_check.stdout:
                                    logger.info(
                                        f"Kindle package confirmed to be installed on {expected_emulator_id}"
                                    )
                                else:
                                    logger.warning(
                                        f"Emulator {expected_emulator_id} booted but Kindle package not found. Will proceed anyway."
                                    )
                            except Exception as e:
                                logger.warning(f"Error checking for Kindle package: {e}")

                            # Allow a bit more time for system services to stabilize
                            logger.info("Waiting 2 seconds for system services to stabilize...")
                            time.sleep(2)
                            return True
                    else:
                        logger.warning("Emulator not booted yet, continuing to wait...")

                except Exception as e:
                    # Log but continue polling
                    logger.debug(f"Exception during boot check: {e}")

                # Check for no progress with the timeout
                elapsed_since_progress = time.time() - last_progress_time
                if elapsed_since_progress > no_progress_timeout:
                    logger.warning(
                        f"No progress detected for {elapsed_since_progress:.1f} seconds, collecting debug info before cleanup"
                    )

                    # Collect debug information before terminating
                    try:
                        # Check boot state again
                        boot_state = subprocess.run(
                            [
                                f"{self.android_home}/platform-tools/adb",
                                "shell",
                                "getprop",
                                "sys.boot_completed",
                            ],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        logger.warning(f"Final boot_completed state: [{boot_state.stdout.strip()}]")

                        # Get list of running services
                        services = subprocess.run(
                            [f"{self.android_home}/platform-tools/adb", "shell", "getprop | grep init.svc"],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        logger.warning(f"Running services: {services.stdout.strip()}")

                        # Check emulator process status
                        if process.poll() is not None:
                            logger.warning(
                                f"Emulator process already terminated with return code: {process.returncode}"
                            )
                            if process.stderr:
                                stderr_output = process.stderr.read().decode("utf-8", errors="replace")
                                logger.warning(f"Emulator stderr: {stderr_output}")
                    except Exception as debug_e:
                        logger.warning(f"Error collecting debug info: {debug_e}")

                    logger.warning("Cleaning up emulator after no progress detected")

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

        except Exception as e:
            logger.error(f"Error starting emulator: {e}")
            return False
