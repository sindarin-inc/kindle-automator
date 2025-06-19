"""
Mullvad WireGuard VPN manager for Android emulators.
Handles configuration generation and VPN setup for each emulator.
"""

import json
import logging
import os
import random
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class MullvadWireGuardManager:
    """Manages WireGuard VPN configurations for Mullvad on Android emulators."""

    def __init__(self, android_home: str):
        self.android_home = android_home
        self.adb_path = os.path.join(android_home, "platform-tools", "adb")
        self.account_number = os.getenv("MULLVAD_ACCOUNT_NUMBER")

        # Mullvad API endpoints
        self.api_base = "https://api.mullvad.net"
        self.wireguard_keys_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "mullvad_wireguard_keys.json"
        )

        # Ensure config directory exists
        os.makedirs(os.path.dirname(self.wireguard_keys_file), exist_ok=True)

    def generate_wireguard_keypair(self) -> Tuple[str, str]:
        """Generate a WireGuard private/public key pair."""
        try:
            # Generate private key
            private_key_proc = subprocess.run(["wg", "genkey"], capture_output=True, text=True, check=True)
            private_key = private_key_proc.stdout.strip()

            # Generate public key from private key
            public_key_proc = subprocess.run(
                ["wg", "pubkey"], input=private_key, capture_output=True, text=True, check=True
            )
            public_key = public_key_proc.stdout.strip()

            return private_key, public_key

        except Exception as e:
            logger.error(f"Error generating WireGuard keypair: {e}")
            raise

    def add_wireguard_key_to_mullvad(self, public_key: str) -> bool:
        """Register a WireGuard public key with Mullvad."""
        if not self.account_number:
            logger.error("MULLVAD_ACCOUNT environment variable not set")
            return False

        try:
            response = requests.post(
                f"{self.api_base}/wg/",
                json={"account": self.account_number, "pubkey": public_key},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code == 201:
                logger.info(f"Successfully registered WireGuard key with Mullvad")
                return True
            else:
                logger.error(f"Failed to register key: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error registering WireGuard key: {e}")
            return False

    def get_wireguard_config(self, private_key: str, server_location: str = "us") -> str:
        """Generate a WireGuard configuration for a specific server location."""
        try:
            # Get relay list to find servers
            response = requests.get(f"{self.api_base}/relays/wireguard/v1/", timeout=30)
            relays = response.json()

            # Find servers in requested location
            available_servers = []
            for country in relays:
                if country["code"].lower() == server_location.lower():
                    for city in country["cities"]:
                        for relay in city["relays"]:
                            if relay["active"]:
                                available_servers.append(
                                    {
                                        "hostname": relay["hostname"],
                                        "ipv4": relay["ipv4_addr_in"],
                                        "public_key": relay["public_key"],
                                        "port": relay.get("port", 51820),
                                    }
                                )

            if not available_servers:
                logger.error(f"No available servers found in {server_location}")
                return None

            # Select a random server
            server = random.choice(available_servers)

            # Generate configuration
            config = f"""[Interface]
PrivateKey = {private_key}
Address = 10.{random.randint(64, 127)}.{random.randint(0, 255)}.{random.randint(2, 254)}/32
DNS = 193.138.218.74

[Peer]
PublicKey = {server['public_key']}
AllowedIPs = 0.0.0.0/0
Endpoint = {server['ipv4']}:{server['port']}
"""

            return config

        except Exception as e:
            logger.error(f"Error generating WireGuard config: {e}")
            return None

    def save_emulator_keys(self, emulator_id: str, private_key: str, public_key: str):
        """Save WireGuard keys for an emulator."""
        try:
            # Load existing keys
            keys = {}
            if os.path.exists(self.wireguard_keys_file):
                with open(self.wireguard_keys_file, "r") as f:
                    keys = json.load(f)

            # Add new keys
            keys[emulator_id] = {"private_key": private_key, "public_key": public_key, "created": time.time()}

            # Save back
            with open(self.wireguard_keys_file, "w") as f:
                json.dump(keys, f, indent=2)

        except Exception as e:
            logger.error(f"Error saving WireGuard keys: {e}")

    def get_emulator_keys(self, emulator_id: str) -> Optional[Dict[str, str]]:
        """Get saved WireGuard keys for an emulator."""
        try:
            if os.path.exists(self.wireguard_keys_file):
                with open(self.wireguard_keys_file, "r") as f:
                    keys = json.load(f)
                    return keys.get(emulator_id)
            return None
        except Exception as e:
            logger.error(f"Error loading WireGuard keys: {e}")
            return None

    def setup_wireguard_on_emulator(self, emulator_id: str, server_location: str = "us") -> bool:
        """Set up WireGuard VPN on an Android emulator."""
        try:
            logger.info(f"Setting up WireGuard on {emulator_id} for location {server_location}")

            # Check if we have a pre-configured WireGuard key
            wireguard_key = os.getenv("WIREGUARD_KEY")

            if wireguard_key:
                # Use the provided WireGuard private key
                logger.info("Using WireGuard key from environment")
                private_key = wireguard_key

                # Generate public key from private key
                public_key_proc = subprocess.run(
                    ["wg", "pubkey"], input=private_key, capture_output=True, text=True, check=True
                )
                public_key = public_key_proc.stdout.strip()
            else:
                # Check if we have existing keys for this emulator
                keys = self.get_emulator_keys(emulator_id)

                if not keys:
                    # Generate new keypair
                    logger.info("Generating new WireGuard keypair")
                    private_key, public_key = self.generate_wireguard_keypair()

                    # Register with Mullvad
                    if not self.add_wireguard_key_to_mullvad(public_key):
                        return False

                    # Save keys
                    self.save_emulator_keys(emulator_id, private_key, public_key)
                else:
                    private_key = keys["private_key"]
                    public_key = keys["public_key"]
                    logger.info("Using existing WireGuard keys")

            # Generate configuration
            config = self.get_wireguard_config(private_key, server_location)
            if not config:
                return False

            # Create temporary config file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
                f.write(config)
                temp_config = f.name

            try:
                # Push config to emulator
                config_path = "/sdcard/wg0.conf"
                push_result = subprocess.run(
                    [self.adb_path, "-s", emulator_id, "push", temp_config, config_path],
                    capture_output=True,
                    text=True,
                )

                if push_result.returncode != 0:
                    logger.error(f"Failed to push config: {push_result.stderr}")
                    return False

                # Install WireGuard app if not installed
                if not self._is_wireguard_installed(emulator_id):
                    logger.info("WireGuard app not installed, installing...")
                    if not self._install_wireguard_app(emulator_id):
                        return False

                # Import configuration using WireGuard app
                # This requires the WireGuard app to handle the config file
                import_result = subprocess.run(
                    [
                        self.adb_path,
                        "-s",
                        emulator_id,
                        "shell",
                        "am",
                        "start",
                        "-a",
                        "android.intent.action.VIEW",
                        "-d",
                        f"file://{config_path}",
                        "-t",
                        "application/x-wireguard-config",
                    ],
                    capture_output=True,
                    text=True,
                )

                if import_result.returncode == 0:
                    logger.info("WireGuard configuration imported successfully")
                    return True
                else:
                    logger.error(f"Failed to import config: {import_result.stderr}")
                    return False

            finally:
                # Clean up temp file
                os.unlink(temp_config)

        except Exception as e:
            logger.error(f"Error setting up WireGuard: {e}")
            return False

    def _is_wireguard_installed(self, emulator_id: str) -> bool:
        """Check if WireGuard app is installed."""
        try:
            result = subprocess.run(
                [
                    self.adb_path,
                    "-s",
                    emulator_id,
                    "shell",
                    "pm",
                    "list",
                    "packages",
                    "com.wireguard.android",
                ],
                capture_output=True,
                text=True,
            )
            return "com.wireguard.android" in result.stdout
        except Exception:
            return False

    def _install_wireguard_app(self, emulator_id: str) -> bool:
        """Install WireGuard app from APK."""
        # First, we need to download the WireGuard APK
        # You can get it from F-Droid or APKMirror
        # For now, assume it's in the apks directory
        apk_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "apks",
            "wireguard.apk",
        )

        if not os.path.exists(apk_path):
            logger.error(f"WireGuard APK not found at {apk_path}")
            logger.info(
                "Please download WireGuard APK from https://f-droid.org/en/packages/com.wireguard.android/"
            )
            return False

        try:
            result = subprocess.run(
                [self.adb_path, "-s", emulator_id, "install", "-r", apk_path], capture_output=True, text=True
            )

            if result.returncode == 0:
                logger.info("WireGuard app installed successfully")
                return True
            else:
                logger.error(f"Failed to install WireGuard: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error installing WireGuard: {e}")
            return False

    def connect_vpn(self, emulator_id: str) -> bool:
        """Connect to the VPN using the imported configuration."""
        try:
            # Use WireGuard app's intent to connect
            # This assumes the config is already imported
            connect_result = subprocess.run(
                [
                    self.adb_path,
                    "-s",
                    emulator_id,
                    "shell",
                    "am",
                    "broadcast",
                    "-a",
                    "com.wireguard.android.action.SET_TUNNEL_UP",
                    "-n",
                    "com.wireguard.android/.backend.TunnelService\$TunnelStateBroadcastReceiver",
                    "--es",
                    "tunnel",
                    "wg0",
                ],
                capture_output=True,
                text=True,
            )

            if connect_result.returncode == 0:
                logger.info("VPN connection initiated")
                return True
            else:
                logger.error(f"Failed to connect VPN: {connect_result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error connecting VPN: {e}")
            return False

    def disconnect_vpn(self, emulator_id: str) -> bool:
        """Disconnect from the VPN."""
        try:
            disconnect_result = subprocess.run(
                [
                    self.adb_path,
                    "-s",
                    emulator_id,
                    "shell",
                    "am",
                    "broadcast",
                    "-a",
                    "com.wireguard.android.action.SET_TUNNEL_DOWN",
                    "-n",
                    "com.wireguard.android/.backend.TunnelService\$TunnelStateBroadcastReceiver",
                    "--es",
                    "tunnel",
                    "wg0",
                ],
                capture_output=True,
                text=True,
            )

            if disconnect_result.returncode == 0:
                logger.info("VPN disconnected")
                return True
            else:
                logger.error(f"Failed to disconnect VPN: {disconnect_result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error disconnecting VPN: {e}")
            return False


# Global instance
_mullvad_manager = None


def get_mullvad_manager(android_home: str) -> MullvadWireGuardManager:
    """Get global Mullvad WireGuard manager instance."""
    global _mullvad_manager
    if _mullvad_manager is None:
        _mullvad_manager = MullvadWireGuardManager(android_home)
    return _mullvad_manager
