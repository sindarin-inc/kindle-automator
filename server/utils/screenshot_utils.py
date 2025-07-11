"""Screenshot utility functions for the Kindle Automator.

This module provides functions for taking screenshots through various methods,
including secure screenshots that bypass FLAG_SECURE restrictions.
"""

import logging
import os
import subprocess
import tempfile
import time
from typing import Optional

logger = logging.getLogger(__name__)


def take_adb_screenshot(device_id: str, output_path: str) -> Optional[str]:
    """Take a fast screenshot using ADB screencap.

    Args:
        device_id: The Android device/emulator ID
        output_path: Path to save the screenshot

    Returns:
        Path to the saved screenshot or None if failed
    """
    try:
        logger.info("Using fast ADB screenshot for non-secure screen")

        # Direct ADB screencap method - much faster
        cmd = f"adb -s {device_id} exec-out screencap -p > {output_path}"
        subprocess.run(cmd, shell=True, timeout=5, check=True)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            logger.info(f"Screenshot saved to {output_path} using fast ADB method")
            return output_path
        else:
            logger.warning("Fast ADB screenshot failed or produced empty file")
    except Exception as e:
        logger.error(f"Error with fast ADB screenshot: {e}", exc_info=True)

    return None


def take_secure_screenshot(
    device_id: str,
    output_path: str = None,
    screenshots_dir: str = "screenshots",
    force_secure: bool = False,
    current_state=None,
) -> Optional[str]:
    """Take screenshot directly with multiple methods for FLAG_SECURE screens.

    This method uses different approaches depending on the current state:
    1. For auth screens (FLAG_SECURE): scrcpy with video capture
    2. For library/reading: Use faster ADB screencap

    Args:
        device_id: The Android device/emulator ID
        output_path: Path to save the screenshot. If None,
                    a path in the screenshots directory is generated.
        screenshots_dir: Directory to save screenshots in
        force_secure: If True, always use scrcpy method even for
                    non-auth screens. Useful for captcha handling.
        current_state: Current app state to determine if secure method is needed

    Returns:
        str: Path to the saved screenshot or None if screenshot failed
    """
    try:
        if output_path is None:
            # Generate a filename if none provided
            filename = f"secure_screenshot_{int(time.time())}.png"
            output_path = os.path.join(screenshots_dir, filename)

        logger.info(f"Taking screenshot, saving to {output_path}")

        # Check if we're in a state that needs secure screenshot (FLAG_SECURE)
        # or if we can use the faster ADB method
        needs_secure = force_secure  # Honor force_secure parameter
        if not needs_secure and current_state is not None:
            # Import AppState locally to avoid circular imports
            from views.core.app_state import AppState

            auth_states = [
                AppState.SIGN_IN,
                AppState.CAPTCHA,
                AppState.TWO_FACTOR,
                AppState.PUZZLE,
                AppState.SIGN_IN_PASSWORD,
            ]
            needs_secure = current_state in auth_states

        if not needs_secure:
            # Fast path: Use direct ADB screenshot for non-FLAG_SECURE screens
            result = take_adb_screenshot(device_id, output_path)
            if result:
                return result
            # Fall through to secure methods if fast method fails

        # Slow path: Use scrcpy for FLAG_SECURE screens
        try:
            logger.info("Trying scrcpy video capture for FLAG_SECURE...")
            # First, set up a more compatible environment
            subprocess.run(
                f"adb -s {device_id} shell settings put global window_animation_scale 0.0",
                shell=True,
                check=False,
            )
            subprocess.run(
                f"adb -s {device_id} shell settings put global transition_animation_scale 0.0",
                shell=True,
                check=False,
            )
            subprocess.run(
                f"adb -s {device_id} shell settings put global animator_duration_scale 0.0",
                shell=True,
                check=False,
            )
            # Use temp video file for scrcpy capture
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
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
                # Check if scrcpy version supports --no-playback
                try:
                    has_no_playback = "--no-playback" in subprocess.check_output(
                        [scrcpy_path, "--help"], stderr=subprocess.STDOUT, text=True
                    )
                except Exception:
                    has_no_playback = False

                scrcpy_cmd = [
                    scrcpy_path,
                    "-s",
                    device_id,
                ]

                # Only add --no-playback if supported
                if has_no_playback:
                    scrcpy_cmd.append("--no-playback")  # For scrcpy 3.1+

                scrcpy_cmd.extend(
                    [
                        "--record",
                        video_path,  # Record as video
                        "--no-audio",  # No audio needed
                        "--turn-screen-off",  # Critical for FLAG_SECURE
                    ]
                )

                logger.info(f"Running scrcpy command: {' '.join(scrcpy_cmd)}")
                process = subprocess.Popen(
                    scrcpy_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
                )

                # Wait for scrcpy to capture the video
                time.sleep(5)
                process.terminate()

                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass

                # Capture and log output
                stdout, stderr = process.communicate()
                if stderr:
                    logger.info(f"scrcpy stderr: {stderr}")

                # Extract first frame from video if video was created
                if os.path.exists(video_path):
                    logger.info(
                        f"Checking video file: {video_path}, size: {os.path.getsize(video_path)} bytes"
                    )

                    if os.path.getsize(video_path) > 1000:
                        logger.info("Video captured, extracting first frame with ffmpeg...")
                        # Extract first frame as image using ffmpeg
                        try:
                            # Ensure we have enough time to read the video file
                            time.sleep(0.5)

                            # Get full paths to ensure correct execution
                            ffmpeg_path = subprocess.check_output(["which", "ffmpeg"], text=True).strip()
                            logger.info(f"Using ffmpeg at: {ffmpeg_path}")

                            # Extract the first frame
                            ffmpeg_cmd = [
                                ffmpeg_path,
                                "-i",
                                video_path,
                                "-frames:v",
                                "1",
                                "-y",  # Overwrite output file if it exists
                                output_path,
                            ]

                            # Run with more detailed output and the same environment
                            result = subprocess.run(
                                ffmpeg_cmd,
                                check=False,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                env=env,
                            )

                            # Check if image extraction succeeded
                            if os.path.exists(output_path):
                                logger.info(
                                    f"Output file created: {output_path}, size: {os.path.getsize(output_path)} bytes"
                                )
                                if os.path.getsize(output_path) > 1000:
                                    logger.info(
                                        f"Screenshot saved to {output_path} using scrcpy with ffmpeg extraction"
                                    )
                                    # Clean up temp file
                                    os.unlink(video_path)
                                    return output_path
                                else:
                                    logger.error(
                                        f"Output file too small: {os.path.getsize(output_path)} bytes",
                                        exc_info=True,
                                    )
                            else:
                                logger.error(f"Output file was not created: {output_path}")
                        except Exception as e:
                            logger.error(f"ffmpeg frame extraction failed: {e}", exc_info=True)
                    else:
                        logger.error(f"Video file too small: {os.path.getsize(video_path)} bytes")
                else:
                    logger.error(f"Video file not created: {video_path}")

                # Clean up temp file if it exists
                if os.path.exists(video_path):
                    os.unlink(video_path)
        except Exception as e:
            logger.error(f"scrcpy video method failed: {e}", exc_info=True)

        # Method 2: Alternative scrcpy parameters
        try:
            logger.info("Trying alternative scrcpy method...")
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
                alt_video_path = temp_file.name

            # Alternative simplified scrcpy parameters
            alt_cmd = [
                scrcpy_path,  # Use the path we already found
                "-s",
                device_id,
                "--no-playback",
                "--record",
                alt_video_path,
                "--legacy-paste",  # Alternative mode that might help
            ]

            logger.info(f"Running alternative scrcpy command: {' '.join(alt_cmd)}")
            alt_process = subprocess.Popen(
                alt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
            )
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
                    alt_ffmpeg_cmd = ["ffmpeg", "-i", alt_video_path, "-frames:v", "1", "-y", output_path]

                    alt_ffmpeg_result = subprocess.run(
                        alt_ffmpeg_cmd,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=env,
                    )

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
                    logger.error(f"Alternative ffmpeg extraction failed: {inner_e}", exc_info=True)

            # Clean up temp file if it exists
            if os.path.exists(alt_video_path):
                os.unlink(alt_video_path)
        except Exception as e:
            logger.error(f"Alternative scrcpy method failed: {e}", exc_info=True)

        # Method 3: Direct ADB exec-out method (fallback, likely won't work with FLAG_SECURE)
        try:
            logger.info("Trying direct adb exec-out method...")
            cmd = f"adb -s {device_id} exec-out screencap -p > {output_path}"
            subprocess.run(cmd, shell=True, timeout=5, check=False)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"Screenshot saved to {output_path} using adb exec-out")
                return output_path
        except Exception as e:
            logger.error(f"Direct ADB method failed: {e}", exc_info=True)

        # Method 4: ADB temp file method (fallback, likely won't work with FLAG_SECURE)
        try:
            logger.info("Trying adb temp file method...")
            device_temp = "/data/local/tmp/screenshot.png"
            subprocess.run(
                f"adb -s {device_id} shell screencap -p {device_temp}",
                shell=True,
                check=False,
                timeout=5,
            )
            subprocess.run(
                f"adb -s {device_id} pull {device_temp} {output_path}",
                shell=True,
                check=False,
                timeout=5,
            )

            if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"Screenshot saved to {output_path} using adb temp file")
                return output_path
        except Exception as e:
            logger.error(f"ADB temp file method failed: {e}", exc_info=True)

        logger.error("All screenshot methods failed")
        return None

    except Exception as e:
        logger.error(f"Error taking secure screenshot: {e}", exc_info=True)
        return None
