# Captcha Solving with VNC for Kindle Automator

This document explains how to use the VNC and Web-VNC interfaces for solving captchas when logging into Kindle accounts.

## Overview

The system allows users to view and interact with the Android emulator's screen to solve captchas:

1. When a login requires captcha verification, the user receives a notification
2. User accesses the emulator's screen using VNC or Web VNC
3. User solves the captcha on their mobile device
4. Authentication continues automatically

## Connection Options

### Option 1: Web Browser (Recommended)

Access through any web browser:
```
http://SERVER_IP:6080/vnc.html
```

This works on:
- iOS devices
- Android devices
- Desktop browsers

### Option 2: Mobile App Integration

For embedding in your mobile app, use a WebView with this URL:
```
http://SERVER_IP:6080/vnc_lite.html?autoconnect=true&resize=scale
```

The `vnc_lite.html` interface provides a lightweight, mobile-friendly viewer perfect for embedding in native applications.

### Option 3: Native VNC Client

Connect using any VNC client:
- Host: SERVER_IP
- Port: 5900
- Password: (server password)

## Implementation Details

The system uses:
1. **Xvfb** - Creates a virtual display (:1)
2. **x11vnc** - Shares the display to VNC clients
3. **noVNC** - Provides web-based access
4. **Websockify** - Bridges VNC to WebSockets for browser access

## Security Considerations

- For production, consider using HTTPS for the web interface
- Use a VPN or SSH tunnel for secure remote access
- Implement session-specific passwords for enhanced security

## Troubleshooting

If you encounter issues:
1. Check all services are running: `systemctl status xvfb vnc novnc`
2. Verify the emulator is using display :1
3. Test connectivity with `telnet SERVER_IP 5900` and `telnet SERVER_IP 6080`
4. Check logs with `journalctl -u novnc`