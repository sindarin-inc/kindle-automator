import argparse
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback

from driver import Driver
from handlers.library_handler import LibraryHandler
from handlers.reader_handler import ReaderHandler
from views.state_machine import AppState, KindleStateMachine

logger = logging.getLogger(__name__)


class KindleAutomator:
    def __init__(self):
        self.email = None
        self.password = None
        self.captcha_solution = None
        self.driver = None
        self.state_machine = None
        self.device_id = None  # Will be set during initialization
        self.library_handler = None
        self.reader_handler = None
        self.screenshots_dir = "screenshots"
        # Ensure screenshots directory exists
        os.makedirs(self.screenshots_dir, exist_ok=True)

    def cleanup(self):
        """Cleanup resources."""
        if self.driver:
            Driver.reset()  # This will allow reinitialization
            self.driver = None
            self.device_id = None

    def initialize_driver(self):
        """Initialize the Appium driver and Kindle app."""
        # Create and initialize driver
        driver = Driver()
        # Set the automator reference in the driver
        driver.automator = self

        if not driver.initialize():
            return False

        self.driver = driver.get_driver()
        self.device_id = driver.get_device_id()

        # Initialize state machine without credentials or captcha
        self.state_machine = KindleStateMachine(self.driver)

        # Initialize handlers
        self.library_handler = LibraryHandler(self.driver)
        self.reader_handler = ReaderHandler(self.driver)

        return True

    def store_current_page_source(self):
        """Store the current page source as a screenshot"""
        # Get the current page source
        page_source = self.driver.page_source

        # Store the page source in a file named after the current state
        state_name = self.state_machine.current_state.name
        file_name = f"{state_name}.xml"
        file_path = os.path.join(self.screenshots_dir, file_name)
        with open(file_path, "w") as file:
            file.write(page_source)
        logger.info(f"Saved current page source ({state_name}) to {file_path}")

    def transition_to_library(self):
        """Handles the initial app setup and ensures we reach the library view"""
        return self.state_machine.transition_to_library()

    def ensure_driver_running(self):
        """Ensure the driver is healthy and running, reinitialize if needed."""
        try:
            if not self.driver:
                # Test if driver is still connected
                try:
                    self.driver.current_activity
                except Exception as e:
                    logger.info("Driver not connected - reinitializing")
                    self.cleanup()
                    return self.initialize_driver()
                else:
                    logger.info("Driver already initialized")

            # Basic health check - try to get current activity
            try:
                self.driver.current_activity
                logger.info("Driver is healthy")
                return True
            except Exception as e:
                logger.info(f"Driver is unhealthy ({e}), reinitializing...")
                self.cleanup()  # Clean up old driver
                return self.initialize_driver()

        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error ensuring driver is running: {e}")
            return False

    def update_captcha_solution(self, solution):
        """Update captcha solution across all components if different.

        Args:
            solution: The new captcha solution to set

        Returns:
            bool: True if solution was updated (was different), False otherwise
        """
        if solution != self.captcha_solution:
            logger.info("Updating captcha solution")
            self.captcha_solution = solution
            if self.state_machine:
                self.state_machine.auth_handler.captcha_solution = solution
            return True
        return False

    def update_credentials(self, email, password):
        """Update user credentials in the automator and state machine.

        Args:
            email: The Amazon account email
            password: The Amazon account password
        """
        logger.info(f"Updating credentials for email: {email}")
        self.email = email
        self.password = password
        if self.state_machine and self.state_machine.auth_handler:
            self.state_machine.auth_handler.email = email
            self.state_machine.auth_handler.password = password
            
    def take_secure_screenshot(self, output_path=None):
        """Take screenshot directly with multiple methods for FLAG_SECURE screens.
        
        This method uses scrcpy 3.1 parameters to capture Android 11 FLAG_SECURE windows:
        1. Video capture with ffmpeg extraction for FLAG_SECURE
        2. ADB screencap fallbacks (which likely won't work for FLAG_SECURE)
        
        Args:
            output_path (str, optional): Path to save the screenshot. If None,
                                        a path in the screenshots directory is generated.
        
        Returns:
            str: Path to the saved screenshot or None if screenshot failed
        """
        try:
            if output_path is None:
                # Generate a filename if none provided
                filename = f"secure_screenshot_{int(time.time())}.png"
                output_path = os.path.join(self.screenshots_dir, filename)
                
            logger.info(f"Taking secure screenshot, saving to {output_path}")
            
            # Method 1: scrcpy 3.1 video capture with screen-off for FLAG_SECURE
            try:
                logger.info("Trying scrcpy video capture for FLAG_SECURE...")
                # First, set up a more compatible environment
                subprocess.run(f"adb -s {self.device_id} shell settings put global window_animation_scale 0.0", 
                              shell=True, check=False)
                subprocess.run(f"adb -s {self.device_id} shell settings put global transition_animation_scale 0.0", 
                              shell=True, check=False)
                subprocess.run(f"adb -s {self.device_id} shell settings put global animator_duration_scale 0.0", 
                              shell=True, check=False)
                
                # Use temp video file for scrcpy capture
                with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
                    video_path = temp_file.name
                
                # Use simplified scrcpy 3.1 parameters for FLAG_SECURE
                # Get absolute path to scrcpy
                scrcpy_path = subprocess.check_output(["which", "scrcpy"], text=True).strip()
                logger.info(f"Using scrcpy at: {scrcpy_path}")
                
                # Set up environment to ensure proper execution
                env = os.environ.copy()
                # Add Homebrew paths if they're not already in PATH
                brew_path = "/opt/homebrew/bin"
                if brew_path not in env.get("PATH", ""):
                    env["PATH"] = f"{brew_path}:{env.get('PATH', '')}"
                logger.info(f"Using PATH: {env['PATH']}")
                
                # Define scrcpy command with minimal parameters
                scrcpy_cmd = [
                    scrcpy_path,
                    "-s", self.device_id,
                    "--no-playback",          # For scrcpy 3.1
                    "--record", video_path,   # Record as video
                    "--no-audio",             # No audio needed
                    "--turn-screen-off"       # Critical for FLAG_SECURE
                ]
                
                logger.info(f"Running scrcpy command: {' '.join(scrcpy_cmd)}")
                process = subprocess.Popen(scrcpy_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                
                # Wait for scrcpy to capture the video
                time.sleep(5)
                process.terminate()
                
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                
                # Capture and log output
                stdout, stderr = process.communicate()
                if stdout:
                    logger.info(f"scrcpy stdout: {stdout}")
                if stderr:
                    logger.info(f"scrcpy stderr: {stderr}")
                
                # Extract first frame from video if video was created
                if os.path.exists(video_path):
                    logger.info(f"Checking video file: {video_path}, size: {os.path.getsize(video_path)} bytes")
                    
                    if os.path.getsize(video_path) > 1000:
                        logger.info("Video captured, extracting first frame with ffmpeg...")
                        # Extract first frame as image using ffmpeg
                        try:
                            # Ensure we have enough time to read the video file
                            time.sleep(0.5)
                            
                            # Get full paths to ensure correct execution
                            ffmpeg_path = subprocess.check_output(["which", "ffmpeg"], 
                                                                text=True).strip()
                            logger.info(f"Using ffmpeg at: {ffmpeg_path}")
                            
                            # Extract the first frame
                            ffmpeg_cmd = [
                                ffmpeg_path, 
                                "-i", video_path, 
                                "-frames:v", "1", 
                                "-y",  # Overwrite output file if it exists
                                output_path
                            ]
                            
                            # Run with more detailed output and the same environment
                            result = subprocess.run(ffmpeg_cmd, check=False, 
                                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                 text=True, env=env)
                            
                            logger.info(f"ffmpeg stdout: {result.stdout}")
                            logger.info(f"ffmpeg stderr: {result.stderr}")
                            
                            # Check if image extraction succeeded
                            if os.path.exists(output_path):
                                logger.info(f"Output file created: {output_path}, size: {os.path.getsize(output_path)} bytes")
                                if os.path.getsize(output_path) > 1000:
                                    logger.info(f"Screenshot saved to {output_path} using scrcpy with ffmpeg extraction")
                                    # Clean up temp file
                                    os.unlink(video_path)
                                    return output_path
                                else:
                                    logger.error(f"Output file too small: {os.path.getsize(output_path)} bytes")
                            else:
                                logger.error(f"Output file was not created: {output_path}")
                        except Exception as e:
                            logger.error(f"ffmpeg frame extraction failed: {e}")
                    else:
                        logger.error(f"Video file too small: {os.path.getsize(video_path)} bytes")
                else:
                    logger.error(f"Video file not created: {video_path}")
                
                # Clean up temp file if it exists
                if os.path.exists(video_path):
                    os.unlink(video_path)
            except Exception as e:
                logger.error(f"scrcpy video method failed: {e}")
            
            # Method 2: Alternative scrcpy parameters
            try:
                logger.info("Trying alternative scrcpy method...")
                with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
                    alt_video_path = temp_file.name
                
                # Alternative simplified scrcpy parameters
                alt_cmd = [
                    scrcpy_path,  # Use the path we already found
                    "-s", self.device_id,
                    "--no-playback",
                    "--record", alt_video_path,
                    "--legacy-paste"         # Alternative mode that might help
                ]
                
                logger.info(f"Running alternative scrcpy command: {' '.join(alt_cmd)}")
                alt_process = subprocess.Popen(alt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                time.sleep(5)
                alt_process.terminate()
                
                try:
                    alt_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                
                # Capture and log output
                alt_stdout, alt_stderr = alt_process.communicate()
                if alt_stdout:
                    logger.info(f"Alternative scrcpy stdout: {alt_stdout}")
                if alt_stderr:
                    logger.info(f"Alternative scrcpy stderr: {alt_stderr}")
                
                # Extract frame if video was captured
                if os.path.exists(alt_video_path) and os.path.getsize(alt_video_path) > 1000:
                    try:
                        # Wait to ensure the file is accessible
                        time.sleep(0.5)
                        
                        # Extract the first frame
                        alt_ffmpeg_cmd = [
                            "ffmpeg", 
                            "-i", alt_video_path, 
                            "-frames:v", "1", 
                            "-y",
                            output_path
                        ]
                        
                        alt_ffmpeg_result = subprocess.run(alt_ffmpeg_cmd, check=False, 
                                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                 text=True, env=env)
                        
                        # Log ffmpeg output
                        if alt_ffmpeg_result.stdout:
                            logger.info(f"Alternative ffmpeg stdout: {alt_ffmpeg_result.stdout}")
                        if alt_ffmpeg_result.stderr:
                            logger.info(f"Alternative ffmpeg stderr: {alt_ffmpeg_result.stderr}")
                        
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                            logger.info(f"Screenshot saved to {output_path} using alternative scrcpy method")
                            os.unlink(alt_video_path)
                            return output_path
                    except Exception as inner_e:
                        logger.error(f"Alternative ffmpeg extraction failed: {inner_e}")
                    
                # Clean up temp file if it exists
                if os.path.exists(alt_video_path):
                    os.unlink(alt_video_path)
            except Exception as e:
                logger.error(f"Alternative scrcpy method failed: {e}")
            
            # Method 3: Direct ADB exec-out method (fallback, likely won't work with FLAG_SECURE)
            try:
                logger.info("Trying direct adb exec-out method...")
                cmd = f"adb -s {self.device_id} exec-out screencap -p > {output_path}"
                subprocess.run(cmd, shell=True, timeout=5, check=False)
                
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    logger.info(f"Screenshot saved to {output_path} using adb exec-out")
                    return output_path
            except Exception as e:
                logger.error(f"Direct ADB method failed: {e}")
            
            # Method 4: ADB temp file method (fallback, likely won't work with FLAG_SECURE)
            try:
                logger.info("Trying adb temp file method...")
                device_temp = "/data/local/tmp/screenshot.png"
                subprocess.run(f"adb -s {self.device_id} shell screencap -p {device_temp}", 
                             shell=True, check=False, timeout=5)
                subprocess.run(f"adb -s {self.device_id} pull {device_temp} {output_path}", 
                             shell=True, check=False, timeout=5)
                
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    logger.info(f"Screenshot saved to {output_path} using adb temp file")
                    return output_path
            except Exception as e:
                logger.error(f"ADB temp file method failed: {e}")
                
            logger.error("All screenshot methods failed")
            return None
                
        except Exception as e:
            logger.error(f"Error taking secure screenshot: {e}")
            return None