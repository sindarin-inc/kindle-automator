"""
Utilities for generating randomized device identifiers for Android emulators.
This helps prevent auth token ejection when multiple emulators run from the same IP.
"""

import random
import string
import uuid


def generate_random_mac_address() -> str:
    """
    Generate a random MAC address.

    Returns:
        str: Random MAC address in format XX:XX:XX:XX:XX:XX
    """
    # First octet should have locally administered bit set (bit 1 = 1)
    # and unicast bit (bit 0 = 0)
    first_octet = random.randint(0, 255) | 0x02 & 0xFE
    mac = [first_octet] + [random.randint(0, 255) for _ in range(5)]
    return ":".join(f"{octet:02X}" for octet in mac)


def generate_random_serial_number() -> str:
    """
    Generate a random Android serial number.

    Returns:
        str: Random serial number (16 characters)
    """
    # Android serial numbers are typically 16 alphanumeric characters
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=16))


def generate_random_android_id() -> str:
    """
    Generate a random Android ID.

    Returns:
        str: Random Android ID (16 hex characters)
    """
    # Android IDs are 64-bit hex values
    return f"{random.randint(0, 2**64-1):016x}"


def generate_random_imei() -> str:
    """
    Generate a random IMEI number.
    Note: Emulators don't have real IMEI, but this can be used if needed.

    Returns:
        str: Random IMEI (15 digits)
    """
    # IMEI is 15 digits
    # Using TAC (Type Allocation Code) prefix that's commonly used for test devices
    tac = "35"  # Generic TAC prefix
    # Generate remaining 13 digits randomly
    remaining = "".join(str(random.randint(0, 9)) for _ in range(13))
    return tac + remaining


def generate_random_device_name() -> str:
    """
    Generate a random device name.

    Returns:
        str: Random device name
    """
    adjectives = ["Swift", "Bright", "Quick", "Smart", "Cool", "Fast", "Zen", "Nova", "Echo", "Pixel"]
    nouns = ["Fox", "Eagle", "Wolf", "Tiger", "Lion", "Hawk", "Bear", "Dragon", "Phoenix", "Falcon"]
    number = random.randint(100, 999)
    return f"{random.choice(adjectives)}{random.choice(nouns)}{number}"


def generate_random_build_id() -> str:
    """
    Generate a random build ID.

    Returns:
        str: Random build ID
    """
    # Android build IDs are typically 8 characters
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def randomize_avd_config_identifiers(config_path: str) -> dict:
    """
    Update AVD config.ini with randomized device identifiers.

    Args:
        config_path: Path to the AVD config.ini file

    Returns:
        dict: Dictionary of randomized identifiers that were set
    """
    import os

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Generate random identifiers
    identifiers = {
        "hw.wifi.mac": generate_random_mac_address(),
        "hw.ethernet.mac": generate_random_mac_address(),
        "ro.serialno": generate_random_serial_number(),
        "ro.build.id": generate_random_build_id(),
        "ro.product.name": generate_random_device_name(),
        "android_id": generate_random_android_id(),  # Store for post-boot randomization
    }

    # Read existing config
    with open(config_path, "r") as f:
        lines = f.readlines()

    # Update or add identifier settings
    new_lines = []
    found_keys = set()

    for line in lines:
        if "=" in line:
            key = line.split("=")[0].strip()
            if key in identifiers:
                new_lines.append(f"{key}={identifiers[key]}\n")
                found_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Add any missing identifiers
    for key, value in identifiers.items():
        if key not in found_keys:
            new_lines.append(f"{key}={value}\n")

    # Write back to file
    with open(config_path, "w") as f:
        f.writelines(new_lines)

    return identifiers


def get_emulator_prop_args(identifiers: dict) -> list:
    """
    Convert identifiers to emulator -prop arguments.

    Args:
        identifiers: Dictionary of identifiers

    Returns:
        list: List of -prop arguments for emulator command
    """
    prop_args = []

    # Map config keys to property names that can be set via -prop
    # Note: Only qemu.* properties can be set via -prop flag
    prop_mappings = {
        "ro.serialno": "qemu.serialno",
        "ro.build.id": "qemu.build.id",
        "ro.product.name": "qemu.product.name",
    }

    for config_key, prop_name in prop_mappings.items():
        if config_key in identifiers:
            prop_args.extend(["-prop", f"{prop_name}={identifiers[config_key]}"])

    return prop_args
