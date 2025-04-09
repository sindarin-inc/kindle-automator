# VNC Patch for Kindle Automator

This document describes how to apply the VNC patch to the Kindle Automator codebase.

## Steps to Apply the Patch

1. After deploying the Ansible VNC role, you need to modify the AVD profile manager to use the VNC display:

```bash
# Backup the original file
cp /path/to/kindle-automator/views/core/avd_profile_manager.py /path/to/kindle-automator/views/core/avd_profile_manager.py.bak

# Replace the start_emulator method
# Use the avd_profile_manager_vnc_patch.py file as a reference to update the start_emulator method
```

2. Key changes in the patch:
   - Detecting the VNC launcher script at `/usr/local/bin/vnc-emulator-launcher.sh`
   - Setting `DISPLAY=:1` for the virtual display
   - Using the launcher script for headless servers
   - Keeping the original launcher for macOS development

## Testing the VNC Setup

1. Deploy the Ansible VNC role:
   ```
   ansible-playbook ansible/provision.yml -t vnc
   ```

2. Apply the patch to AVD profile manager

3. Test VNC connectivity from a mobile device
   - Connect to server IP on port 5900
   - Use the configured password

4. Test captcha solving:
   - Log into a Kindle account that requires a captcha
   - Verify the captcha appears in the VNC stream
   - Solve it from the mobile device

## Troubleshooting

If VNC is not working properly:

1. Check service status:
   ```
   systemctl status xvfb.service
   systemctl status vnc.service
   ```

2. Check logs:
   ```
   journalctl -u xvfb
   journalctl -u vnc
   cat /var/log/x11vnc.log
   ```

3. Verify the emulator is using the correct display:
   ```
   ps aux | grep emulator
   ```
   Look for the DISPLAY=:1 environment variable

4. Restart services if needed:
   ```
   systemctl restart xvfb
   systemctl restart vnc
   ```