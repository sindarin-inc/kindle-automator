# Storagebox Role

This role mounts a Hetzner Storage Box as a SAMBA/CIFS share at `/mnt/storage`.

## Configuration

The role uses the `SAMBA_PASSWORD` variable from `ansible/roles/provision/vars/main/ansible.env.yml`.

To run:

```bash
ansible-playbook ansible/provision.yml -t storagebox
```

## Mount Options

The mount is configured with the following options optimized for large files (AVDs):
- `cache=none`: Disables caching for large file handling
- `nobrl`: Disables byte range locking to avoid issues with large files
- `vers=3.0`: Uses SMB protocol version 3.0
- `_netdev`: Ensures network is available before mounting
- `nofail`: Boot continues even if mount fails

## Default Values

- Mount point: `/mnt/storage`
- Server: `u466521.your-storagebox.de`
- Username: `u466521`
- Share: `backup`