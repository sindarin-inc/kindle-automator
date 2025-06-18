# Emulator Unification Plan for Multi-User Support

## Overview
Extend EmulatorLauncher to support both macOS (local dev) and Linux (production), using minimal inline platform conditionals only where commands differ. Ensure all lifecycle operations work: launch, snapshot, shutdown, and recreate.

## Current State Analysis

### What We Discovered Today
1. **macOS VNC Limitations**:
   - QEMU VNC mode (`-qemu -vnc :1`) doesn't work with ARM64 Android images
   - Need to run emulator with window mode on macOS
   - Can use external VNC server (like macOS Screen Sharing) on the same ports as Linux

2. **Port Management**:
   - Linux: Xvfb on display :X, VNC on port 5900+X
   - macOS: Can use same VNC ports with Screen Sharing or third-party VNC servers
   - Keep same port allocation logic

3. **Current Infrastructure**:
   - **EmulatorLauncher** in `server/utils/emulator_launcher.py` contains the actual launch logic
   - **EmulatorShutdownManager** in `server/utils/emulator_shutdown_manager.py` handles shutdown
   - **AVDCreator** in `views/core/avd_creator.py` handles AVD creation/cloning
   - Already has platform detection checks: `if platform.system() != "Darwin"`
   - VNCInstanceManager manages instance allocation but doesn't launch emulators

## Lifecycle Operations Coverage

### 1. Launch ✅
**File**: `server/utils/emulator_launcher.py`
- `launch_emulator()` method - Already has platform conditionals
- Needs: Add `-no-window` for Linux only, wrap with xvfb-run on Linux

### 2. Snapshot ✅ 
**File**: `server/utils/emulator_launcher.py`
- `save_snapshot()` method (line 1735) - Uses ADB commands, platform-agnostic
- `has_snapshot()` method (line 1844) - Checks AVD directory, platform-agnostic
- `list_snapshots()` method (line 1877) - Lists snapshots, platform-agnostic
- No changes needed - snapshots work the same on both platforms

### 3. Shutdown ✅
**File**: `server/utils/emulator_shutdown_manager.py`
- `shutdown_emulator()` method (line 50) - Main shutdown logic
- `_stop_vnc_xvfb()` method (line 315) - Needs platform conditional to skip on macOS
- `_force_kill_emulator_process()` method (line 353) - Works on both platforms
- Needs: Add conditional to skip VNC/Xvfb cleanup on macOS

### 4. Recreate/Clone ✅
**File**: `views/core/avd_creator.py`
- `create_new_avd()` method (line 71) - Creates AVDs
- `copy_avd_from_seed_clone()` method (line 409) - Clones AVDs
- `create_seed_clone_avd()` method (line 385) - Creates seed AVD
- Uses avdmanager CLI tool - platform-agnostic
- No changes needed - AVD operations work the same on both platforms

## Implementation Plan

### Key Files and Current Platform Handling

1. **server/utils/emulator_launcher.py**:
   - `launch_emulator()` method (line ~719) - Main launch logic
   - `_ensure_vnc_running()` method (line ~471) - Already skips VNC on macOS
   - Platform-specific emulator commands based on `self.host_arch`

2. **server/utils/emulator_shutdown_manager.py**:
   - `_stop_vnc_xvfb()` method - Needs platform check

3. **Current Platform Conditionals**:
   ```python
   # EmulatorLauncher - Line 818: Set DISPLAY for VNC if on Linux
   if platform.system() != "Darwin":
       env["DISPLAY"] = f":{display_num}"
   
   # EmulatorLauncher - Line 997: Ensure VNC running only on Linux
   if platform.system() != "Darwin":
       self._ensure_vnc_running(display_num, email=email)
   
   # EmulatorLauncher - Line 482: Skip VNC setup on macOS
   if platform.system() == "Darwin":
       return True
   ```

### Minimal Changes Needed

1. **Launch - EmulatorLauncher** (lines 914-955):
   ```python
   # Add no-window flag only for Linux (around line 867)
   if platform.system() != "Darwin":
       common_args.append("-no-window")
   
   # Wrap with xvfb-run on Linux (around line 971)
   if platform.system() != "Darwin":
       emulator_cmd = [
           "xvfb-run", "-n", str(display_num),
           "-s", f"-screen 0 1080x1920x24",
           "--"
       ] + emulator_cmd
   ```

2. **Shutdown - EmulatorShutdownManager**:
   ```python
   # In _stop_vnc_xvfb method (line 315)
   def _stop_vnc_xvfb(display_num: int, summary: Dict[str, bool]):
       """Terminate x11vnc and Xvfb processes tied to display_num."""
       if platform.system() == "Darwin":
           return  # Skip VNC/Xvfb cleanup on macOS
       
       # ... existing code ...
   ```

3. **Snapshot** - No changes needed (uses ADB commands)

4. **Recreate/Clone** - No changes needed (uses avdmanager CLI)

### Configuration Updates

```python
# Update ANDROID_HOME default for macOS
DEFAULT_ANDROID_SDK = "/opt/android-sdk"
if platform.system() == "Darwin":
    DEFAULT_ANDROID_SDK = os.path.expanduser("~/Library/Android/sdk")
```

## Summary of Changes

1. **server/utils/emulator_launcher.py**:
   - Add `-no-window` to common_args for Linux only
   - Wrap emulator command with `xvfb-run` on Linux
   - Keep existing platform conditionals for DISPLAY and VNC
   - Update DEFAULT_ANDROID_SDK for macOS

2. **server/utils/emulator_shutdown_manager.py**:
   - Add platform check to skip VNC/Xvfb cleanup on macOS

3. **No changes needed to**:
   - Snapshot operations (platform-agnostic via ADB)
   - AVD creation/cloning (platform-agnostic via avdmanager)
   - VNCInstanceManager (already handles platform differences)
   - Port allocation logic

## Benefits

1. **All lifecycle operations supported** - Launch, snapshot, shutdown, recreate
2. **Minimal changes** - Just 4-5 inline conditionals
3. **Leverages existing logic** - Platform checks already in place
4. **Same port scheme** - No changes to port allocation
5. **Unified codebase** - Single implementation with inline differences

## Testing Strategy

1. **macOS Testing**:
   - Launch: Emulator launches with window
   - Snapshot: ADB snapshot commands work
   - Shutdown: Emulator stops, no VNC/Xvfb cleanup
   - Recreate: AVD cloning works with avdmanager

2. **Linux Testing**:
   - Launch: Emulator launches with xvfb-run
   - Snapshot: ADB snapshot commands work
   - Shutdown: Emulator, VNC, and Xvfb all cleaned up
   - Recreate: AVD cloning works with avdmanager

## Progress Tracking

- [x] Found EmulatorLauncher contains launch logic
- [x] Found EmulatorShutdownManager contains shutdown logic
- [x] Found AVDCreator contains recreate/clone logic
- [x] Verified snapshot operations are platform-agnostic
- [x] Identified existing platform conditionals
- [ ] Add `-no-window` conditional in EmulatorLauncher
- [ ] Add xvfb-run wrapping in EmulatorLauncher
- [ ] Add platform check in EmulatorShutdownManager
- [ ] Update DEFAULT_ANDROID_SDK for macOS
- [ ] Test all operations on macOS
- [ ] Verify all operations on Linux unchanged

## Notes

- All lifecycle operations (launch, snapshot, shutdown, recreate) are covered
- Snapshot and AVD operations are already platform-agnostic
- Only launch and shutdown need platform conditionals
- Most conditionals already exist, just need small additions