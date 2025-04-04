# VNC Display Streaming for Kindle Captcha Solving

This document explains how to use the VNC server to stream Android emulator display to mobile clients for captcha solving.

## Overview

The system uses:
1. Xvfb (X Virtual Frame Buffer) to create a virtual display
2. x11vnc to share that display over VNC protocol
3. Android emulator configured to use the virtual display

## Client Connection

Users can connect to solve captchas using any standard VNC client:

- **Connection details:**
  - Host: [server address]
  - Port: 5900
  - Password: [configured password]

## Mobile Apps Recommended

For iOS:
- VNC Viewer by RealVNC
- Jump Desktop

For Android:
- VNC Viewer by RealVNC
- bVNC Free

## Security Considerations

- VNC connection should be tunneled through SSH or a secure VPN
- Passwords should be rotated regularly
- Consider implementing one-time tokens for connection

## Troubleshooting

1. If the display appears blank:
   - Ensure the emulator is running
   - Check Xvfb and x11vnc logs (`journalctl -u xvfb` and `journalctl -u vnc`)

2. If unable to connect:
   - Verify the VNC port (5900) is open in the firewall
   - Check that the VNC service is running (`systemctl status vnc`)