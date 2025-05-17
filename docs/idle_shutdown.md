# Idle Emulator Shutdown

This feature automatically shuts down emulators that have been idle for a specified period of time, helping to conserve resources.

## How It Works

1. **Activity Tracking**: Every API request updates an activity timestamp for the associated email/emulator
2. **Idle Detection**: The `/idle-check` endpoint checks all running emulators and identifies those that haven't had activity within the timeout period
3. **Automatic Shutdown**: Idle emulators are automatically shut down, following the same parking procedure as manual shutdown (parks in Library view and saves a snapshot)

## Usage

### Manual Idle Check

You can manually trigger an idle check using either GET or POST:

```bash
# GET with default 30-minute timeout
curl http://kindle.sindarin.com:4098/idle-check

# POST with custom timeout
curl -X POST http://kindle.sindarin.com:4098/idle-check \
  -H "Content-Type: application/json" \
  -d '{"idle_timeout_minutes": 15}'
```

### Automated with Cron

#### Manual Setup
1. Edit your crontab:
   ```bash
   crontab -e
   ```

2. Add the following line:
   ```
   */15 * * * * /opt/kindle-automator/scripts/idle_check_cron.sh
   ```

3. Save and exit. The idle check will now run every 15 minutes.

#### Automatic Setup via Ansible
The cron job is automatically set up when deploying with Ansible:
```bash
ansible-playbook ansible/deploy.yml -i ansible/inventory.ini
```

## Response Format

The idle check endpoint returns a JSON response with the following structure:

```json
{
  "timestamp": "2024-01-15T10:30:00",
  "idle_timeout_minutes": 30,
  "total_checked": 3,
  "shut_down": 1,
  "active": 2,
  "failed": 0,
  "shutdown_details": [
    {
      "email": "user1@example.com",
      "idle_minutes": 45.5,
      "status": "shutdown"
    }
  ],
  "active_emulators": [
    {
      "email": "user2@example.com",
      "active_minutes": 5.2
    },
    {
      "email": "user3@example.com",
      "active_minutes": 12.7
    }
  ]
}
```

## Configuration

The default idle timeout is 30 minutes, but this can be customized:

1. **Per Request**: Pass `idle_timeout_minutes` in the POST body
2. **In Cron Script**: Edit the `IDLE_TIMEOUT_MINUTES` variable
3. **Server Default**: Modify `idle_timeout_minutes` in `IdleCheckResource.__init__`
4. **Ansible**: Configure per host using `idle_timeout_minutes` variable

## Log Management

Logs are stored in `/opt/kindle-automator/logs/idle-check.log`

When deployed with Ansible, logrotate is automatically configured to:
- Rotate logs daily
- Keep 14 days of logs
- Compress older logs
- Limit file size to 100MB

## Benefits

- **Resource Management**: Automatically frees up system resources from unused emulators
- **Cost Savings**: Reduces compute costs by shutting down idle instances
- **State Preservation**: Emulators are parked in Library view with snapshots for fast restart
- **Transparency**: Detailed logging shows which emulators were shut down and why

## Notes

- Activity is tracked per email/profile, not per emulator
- The shutdown process preserves state by creating a snapshot
- Emulators can be quickly restarted from their saved state when needed
- Failed shutdowns are logged but don't stop the check process from continuing