"""
Certificate installer for Android emulators.
Installs custom CA certificates as trusted system certificates.
"""

import hashlib
import logging
import os
import subprocess
import tempfile
import time
from typing import Optional

logger = logging.getLogger(__name__)


class CertificateInstaller:
    """Handles installation of CA certificates on Android emulators."""

    def __init__(self, android_home: str):
        self.android_home = android_home
        self.adb_path = os.path.join(android_home, "platform-tools", "adb")

    def install_ca_certificate(self, emulator_id: str, cert_path: str) -> bool:
        """
        Install a CA certificate on the emulator as a trusted system certificate.

        Args:
            emulator_id: The emulator ID (e.g., 'emulator-5554')
            cert_path: Path to the certificate file

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not os.path.exists(cert_path):
                logger.error(f"Certificate file not found: {cert_path}")
                return False

            logger.info(f"Installing CA certificate from {cert_path} on {emulator_id}")

            # Get the certificate hash - Android expects specific filename format
            cert_hash = self._get_cert_hash(cert_path)
            if not cert_hash:
                return False

            cert_filename = f"{cert_hash}.0"

            # First, ensure we have root access
            root_cmd = [self.adb_path, "-s", emulator_id, "root"]
            result = subprocess.run(root_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to get root access: {result.stderr}")
                return False

            # Wait a moment for root to take effect
            time.sleep(1)

            # Remount system partition as writable
            remount_cmd = [self.adb_path, "-s", emulator_id, "remount"]
            result = subprocess.run(remount_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.warning(f"Remount warning (may be normal): {result.stderr}")

            # Push certificate to device
            temp_cert_path = f"/data/local/tmp/{cert_filename}"
            push_cmd = [self.adb_path, "-s", emulator_id, "push", cert_path, temp_cert_path]
            result = subprocess.run(push_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to push certificate: {result.stderr}")
                return False

            # Copy to system CA certificates directory
            target_path = f"/system/etc/security/cacerts/{cert_filename}"
            copy_cmd = [self.adb_path, "-s", emulator_id, "shell", f"cp {temp_cert_path} {target_path}"]
            result = subprocess.run(copy_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to copy certificate to system: {result.stderr}")
                return False

            # Set proper permissions (644)
            chmod_cmd = [self.adb_path, "-s", emulator_id, "shell", f"chmod 644 {target_path}"]
            result = subprocess.run(chmod_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to set certificate permissions: {result.stderr}")
                return False

            # Clean up temporary file
            rm_cmd = [self.adb_path, "-s", emulator_id, "shell", f"rm {temp_cert_path}"]
            subprocess.run(rm_cmd, capture_output=True, text=True)

            # Verify installation
            verify_cmd = [self.adb_path, "-s", emulator_id, "shell", f"ls -la {target_path}"]
            result = subprocess.run(verify_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Successfully installed CA certificate as {cert_filename}")
                logger.info(f"Certificate details: {result.stdout.strip()}")
                return True
            else:
                logger.error("Failed to verify certificate installation")
                return False

        except Exception as e:
            logger.error(f"Error installing CA certificate: {e}")
            return False

    def _get_cert_hash(self, cert_path: str) -> Optional[str]:
        """
        Get the subject hash of a certificate (as Android expects).
        This must match the format Android uses for system certificates.

        Args:
            cert_path: Path to certificate file

        Returns:
            Certificate hash string or None if failed
        """
        try:
            # Use openssl to get the subject hash (old format for Android compatibility)
            openssl_cmd = ["openssl", "x509", "-subject_hash_old", "-in", cert_path, "-noout"]
            result = subprocess.run(openssl_cmd, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"Failed to get certificate hash: {result.stderr}")
                # Try converting if it's not in PEM format
                logger.info("Attempting to convert certificate to PEM format")

                # Create temp file for PEM output
                with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as tmp:
                    convert_cmd = ["openssl", "x509", "-in", cert_path, "-out", tmp.name, "-outform", "PEM"]
                    convert_result = subprocess.run(convert_cmd, capture_output=True, text=True)

                    if convert_result.returncode == 0:
                        # Try again with converted certificate
                        result = subprocess.run(
                            ["openssl", "x509", "-subject_hash_old", "-in", tmp.name, "-noout"],
                            capture_output=True,
                            text=True,
                        )
                        os.unlink(tmp.name)
                    else:
                        os.unlink(tmp.name)
                        return None

            if result.returncode == 0:
                cert_hash = result.stdout.strip()
                logger.info(f"Certificate hash: {cert_hash}")
                return cert_hash
            else:
                return None

        except Exception as e:
            logger.error(f"Error getting certificate hash: {e}")
            return None

    def is_certificate_installed(self, emulator_id: str, cert_path: str) -> bool:
        """
        Check if a certificate is already installed.

        Args:
            emulator_id: The emulator ID
            cert_path: Path to certificate file

        Returns:
            bool: True if certificate is already installed
        """
        try:
            cert_hash = self._get_cert_hash(cert_path)
            if not cert_hash:
                return False

            cert_filename = f"{cert_hash}.0"
            target_path = f"/system/etc/security/cacerts/{cert_filename}"

            check_cmd = [self.adb_path, "-s", emulator_id, "shell", f"test -f {target_path} && echo 'exists'"]
            result = subprocess.run(check_cmd, capture_output=True, text=True)

            return result.returncode == 0 and "exists" in result.stdout

        except Exception as e:
            logger.error(f"Error checking certificate installation: {e}")
            return False
