"""
WebSocket Proxy Manager for VNC connections.

This module handles the creation, management, and cleanup of RFB proxy processes
that convert VNC connections to WebSocket connections for browser-based VNC clients.

It uses the rfbproxy library from Replit (https://github.com/replit/rfbproxy) to
provide a WebSocket interface to the VNC server, allowing connections from noVNC clients.
"""

import logging
import os
import platform
import signal
import subprocess
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Singleton instance
_instance = None

# Base port for WebSocket connections (offset from VNC port)
WS_PORT_OFFSET = 1000  # e.g., VNC on 5901 -> WebSocket on 6901


class WebSocketProxyManager:
    """
    Manages WebSocket proxy processes for VNC connections.
    Implements the singleton pattern to ensure only one instance exists.
    """

    @classmethod
    def get_instance(cls) -> "WebSocketProxyManager":
        """
        Get the singleton instance of WebSocketProxyManager.

        Returns:
            WebSocketProxyManager: The singleton instance
        """
        global _instance
        if _instance is None:
            _instance = cls()
        return _instance

    def __init__(self):
        """
        Initialize the WebSocket proxy manager.
        Note: You should use get_instance() instead of creating instances directly.
        """
        # Check if this is being called directly or through get_instance()
        if _instance is not None and _instance is not self:
            logger.warning("WebSocketProxyManager initialized directly. Use get_instance() instead.")

        # Dictionary to track running proxies by email
        # {email: {"process": subprocess.Popen, "ws_port": int, "vnc_port": int}}
        self.active_proxies = {}

        # Determine platform to handle process management appropriately
        self.is_macos = platform.system() == "Darwin"
        logger.info(f"WebSocketProxyManager initialized on {'macOS' if self.is_macos else 'Linux'}")

    def start_proxy(self, email: str, vnc_port: int) -> Optional[int]:
        """
        Start a WebSocket proxy for the given email and VNC port.

        Args:
            email: The user's email address
            vnc_port: The VNC port to proxy

        Returns:
            Optional[int]: The WebSocket port if successful, None otherwise
        """
        try:
            # Check if proxy is already running for this email
            if email in self.active_proxies:
                logger.info(f"WebSocket proxy already running for {email}")
                return self.active_proxies[email]["ws_port"]

            # Calculate WebSocket port (VNC port + offset)
            ws_port = vnc_port + WS_PORT_OFFSET

            # The command for launching rfbproxy
            # rfbproxy args: --address=0.0.0.0:WS_PORT --rfb-server=127.0.0.1:VNC_PORT
            cmd = ["rfbproxy", f"--address=0.0.0.0:{ws_port}", f"--rfb-server=127.0.0.1:{vnc_port}"]

            logger.info(f"Starting WebSocket proxy for {email}: {' '.join(cmd)}")

            # Create log files for this proxy instance
            # Use the project's logs directory
            from pathlib import Path

            from server.utils.cover_utils import slugify

            project_root = Path(__file__).resolve().parent.parent.parent
            log_dir = project_root / "logs" / "rfbproxy"
            log_dir.mkdir(parents=True, exist_ok=True)

            # Use the same slugify function used elsewhere for consistency
            email_slug = slugify(email)
            timestamp = int(time.time())
            stdout_log = log_dir / f"rfbproxy_{email_slug}_{timestamp}.stdout.log"
            stderr_log = log_dir / f"rfbproxy_{email_slug}_{timestamp}.stderr.log"

            # Launch process with appropriate settings
            # Set RUST_LOG=debug for verbose logging
            env = os.environ.copy()
            env["RUST_LOG"] = "debug"

            with open(str(stdout_log), "w") as stdout_file, open(str(stderr_log), "w") as stderr_file:
                process = subprocess.Popen(
                    cmd,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    start_new_session=True,  # Allows the process to run independently
                    env=env,
                )
                logger.info(f"rfbproxy logs: stdout={stdout_log}, stderr={stderr_log}")

            # Give it a moment to start and check if it's still running
            time.sleep(0.5)
            if process.poll() is not None:
                # Process terminated immediately - read error from log files
                stderr_content = ""
                try:
                    with open(str(stderr_log), "r") as f:
                        stderr_content = f.read().strip() or "No error output captured"
                except Exception:
                    stderr_content = "Could not read error log"

                # Check if rfbproxy is installed
                import shutil

                if not shutil.which("rfbproxy"):
                    stderr_content = (
                        "rfbproxy command not found. Please install rfbproxy to enable WebSocket support."
                    )

                logger.error(f"WebSocket proxy failed to start: {stderr_content}", exc_info=True)
                return None

            # Store the active proxy
            self.active_proxies[email] = {
                "process": process,
                "ws_port": ws_port,
                "vnc_port": vnc_port,
                "start_time": time.time(),
            }

            logger.info(f"WebSocket proxy started for {email} on port {ws_port} (VNC port {vnc_port})")
            return ws_port

        except Exception as e:
            logger.error(f"Error starting WebSocket proxy for {email}: {e}", exc_info=True)
            return None

    def stop_proxy(self, email: str) -> bool:
        """
        Stop the WebSocket proxy for the given email.

        Args:
            email: The user's email address

        Returns:
            bool: True if stopped successfully, False otherwise
        """
        if email not in self.active_proxies:
            logger.warning(f"No WebSocket proxy running for {email}")
            return False

        try:
            proxy_info = self.active_proxies[email]
            process = proxy_info["process"]

            # Gracefully terminate the process
            if process.poll() is None:  # Process is still running
                if self.is_macos:
                    # macOS: Send SIGTERM
                    process.terminate()
                else:
                    # Linux: Send SIGTERM to the process group
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)

                # Wait briefly for the process to terminate
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't terminate
                    if self.is_macos:
                        process.kill()
                    else:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)

            # Remove from tracking dictionary
            del self.active_proxies[email]
            logger.info(f"WebSocket proxy for {email} stopped")
            return True

        except Exception as e:
            logger.error(f"Error stopping WebSocket proxy for {email}: {e}", exc_info=True)
            return False

    def get_ws_port(self, email: str) -> Optional[int]:
        """
        Get the WebSocket port for the given email.

        Args:
            email: The user's email address

        Returns:
            Optional[int]: The WebSocket port if running, None otherwise
        """
        if email in self.active_proxies:
            return self.active_proxies[email]["ws_port"]
        return None

    def is_proxy_running(self, email: str) -> bool:
        """
        Check if a WebSocket proxy is running for the given email.

        Args:
            email: The user's email address

        Returns:
            bool: True if running, False otherwise
        """
        if email in self.active_proxies:
            process = self.active_proxies[email]["process"]
            # Check if the process is still running
            is_running = process.poll() is None
            if not is_running:
                # Clean up if the process has terminated
                logger.warning(f"WebSocket proxy for {email} has terminated unexpectedly")
                del self.active_proxies[email]
            return is_running
        return False

    def restart_proxy(self, email: str) -> Optional[int]:
        """
        Restart the WebSocket proxy for the given email.

        Args:
            email: The user's email address

        Returns:
            Optional[int]: The new WebSocket port if successful, None otherwise
        """
        if email in self.active_proxies:
            vnc_port = self.active_proxies[email]["vnc_port"]
            self.stop_proxy(email)
            return self.start_proxy(email, vnc_port)
        else:
            logger.warning(f"No WebSocket proxy running for {email} to restart")
            return None

    def cleanup(self) -> None:
        """
        Stop all running WebSocket proxies.
        """
        logger.info(f"Cleaning up {len(self.active_proxies)} WebSocket proxies")
        for email in list(self.active_proxies.keys()):
            self.stop_proxy(email)
        logger.info("All WebSocket proxies stopped")
