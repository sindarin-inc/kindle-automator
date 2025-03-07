# Android Root Role

This Ansible role is designed to root an Android emulator installation, install Magisk and EdXposed, and disable the secure flag to allow taking screenshots of protected apps using ADB.

## Features

- Installs Magisk for root access
- Installs EdXposed framework for modifying system behavior
- Disables the secure flag to allow screenshots of protected apps
- Configures the emulator for root access

## Requirements

- Android emulator must be installed and configured
- The `android_home` and `avd_name` variables must be defined

## Role Variables

| Variable                   | Description                                         | Default                         |
| -------------------------- | --------------------------------------------------- | ------------------------------- |
| `magisk_version`           | Version of Magisk to install                        | v26.1                           |
| `edxposed_version`         | Version of EdXposed framework to install            | v0.5.2.2                        |
| `edxposed_manager_version` | Version of EdXposed Manager to install              | 4.6.2                           |
| `root_tools_dir`           | Directory to store rooting tools                    | `{{ android_home }}/root_tools` |
| `boot_timeout`             | Timeout in seconds for waiting for emulator to boot | 120                             |

## Dependencies

- Requires the Android emulator to be installed (e.g., via the `android_x86` role)

## Example Playbook

```yaml
- hosts: servers
  roles:
    - role: android_x86
    - role: android-root
```

## Usage

After applying this role, the Android emulator will be rooted with Magisk, and EdXposed will be installed. The secure flag will be disabled, allowing screenshots of protected apps to be taken using ADB.

## License

MIT

## Author Information

Created for the Kindle Automator project.
