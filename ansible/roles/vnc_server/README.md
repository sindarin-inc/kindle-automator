# VNC Server Role for Kindle Automator

This Ansible role sets up a VNC server on a headless Ubuntu 24.04 server to allow streaming Android emulator display to mobile clients.

## Features

- Sets up Xvfb virtual framebuffer as display :1
- Configures x11vnc to share the virtual display
- Includes a helper script for launching Android emulator with VNC display support
- Allows users to solve captchas on their mobile devices

## Implementation

1. **Xvfb** creates a virtual X display without physical hardware
2. **x11vnc** shares this display over VNC protocol
3. **Android emulator** is configured to use the virtual display
4. The VNC server allows viewing the emulator screen remotely

## Integration with Kindle Automator

The `avd_profile_manager.py` needs to be updated to use the VNC launcher script when available. A patch file is provided at:
`/Users/sclay/projects/sindarin/kindle-automator/views/core/avd_profile_manager_vnc_patch.py`

## Configuration

The following variables can be configured:

- `vnc_resolution`: Resolution for the virtual display (default: "1280x800x24")
- `vnc_port`: Port for VNC server (default: 5900)
- `vnc_password`: Password for VNC authentication (default: "changeme")
- `android_home`: Path to Android SDK (default: "/opt/android-sdk")

## How Users Connect

Users can connect using any VNC client:
- iOS: VNC Viewer, Jump Desktop
- Android: VNC Viewer, bVNC Free

## Security Considerations

- VNC connection should be tunneled through SSH or a secure VPN
- Consider implementing session-specific passwords for connection