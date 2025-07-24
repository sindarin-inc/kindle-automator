# Database Migration Guide: users.json to PostgreSQL

This guide documents the migration from file-based JSON storage to PostgreSQL database for the Kindle Automator project.

## Overview

The AVD Profile Manager has been refactored to use PostgreSQL with SQLAlchemy 2.0 ORM instead of the `users.json` file. This provides:

- **Atomic operations** - No more race conditions from concurrent file access
- **Better performance** - Indexed queries and connection pooling
- **Data integrity** - ACID compliance and foreign key constraints
- **Scalability** - Supports multiple Flask processes
- **Backup/Recovery** - Standard PostgreSQL backup tools

## Architecture

### Database Schema

The `kindle_automator` schema contains the following tables:

- `users` - Main user profile table
- `emulator_settings` - Emulator configuration per user
- `device_identifiers` - Device-specific identifiers
- `library_settings` - Kindle library display preferences
- `reading_settings` - Reading experience preferences
- `user_preferences` - Generic key-value preferences

### Key Components

1. **`connection.py`** - Database connection management with connection pooling
2. **`models.py`** - SQLAlchemy ORM models using declarative mapping
3. **`repositories/user_repository.py`** - Repository pattern for data access
4. **`avd_profile_manager_db.py`** - Database-backed AVDProfileManager implementation

## Migration Steps

### 1. Install Dependencies

```bash
make deps
```

This installs:
- `sqlalchemy==2.0.36`
- `psycopg2-binary==2.9.10`
- `alembic==1.14.0`

### 2. Set Up PostgreSQL

#### Local Development
For local development, use the existing `sol_postgres` container on port 5496:

```sql
CREATE DATABASE kindle_db;
CREATE USER local WITH PASSWORD 'local';
GRANT ALL PRIVILEGES ON DATABASE kindle_db TO local;
```

#### Staging/Production
For staging and production environments, set up your remote PostgreSQL instance with appropriate credentials.

### 3. Configure Environment

Add to your environment files:

#### Local Development (`.env`)
```bash
DATABASE_URL=postgresql://local:local@localhost:5496/kindle_db
KINDLE_SCHEMA=kindle_automator
USE_DATABASE_PROFILE_MANAGER=false  # Set to true when ready to switch
```

#### Staging (`.env.staging`)
```bash
DATABASE_URL=postgresql://user:password@staging-host:5432/kindle_db
KINDLE_SCHEMA=kindle_automator
```

#### Production (`.env.prod`)
```bash
DATABASE_URL=postgresql://user:password@prod-host:5432/kindle_db
KINDLE_SCHEMA=kindle_automator
```

### 4. Run Database Migrations

```bash
cd /Users/sclay/projects/sindarin/kindle-automator

# Local development
alembic upgrade head

# Staging
DATABASE_URL=<staging-url> alembic upgrade head

# Production
DATABASE_URL=<prod-url> alembic upgrade head
```

This creates all tables in the `kindle_automator` schema.

### 5. Migrate Existing Data

Run the migration script to transfer data from `users.json`:

```bash
python scripts/migrate_json_to_db.py
```

This script:
- Loads all users from `users.json`
- Creates corresponding database records
- Preserves all nested data structures
- Creates a backup at `users.json.backup`

### 6. Test the Migration

Run the test suite:

```bash
# Unit tests
pytest tests/test_user_repository.py -v

# Concurrent access tests
python tests/test_concurrent_access.py
```

### 7. Enable Database Mode

When ready to switch to the database:

```bash
# In .env
USE_DATABASE_PROFILE_MANAGER=true
```

## Usage

The API remains the same. The AVDProfileManager will automatically use the database when enabled:

```python
from views.core.avd_profile_manager import AVDProfileManager

# Same API as before
manager = AVDProfileManager.get_instance()
profile = manager.get_profile_for_email("user@example.com")
manager.update_auth_state("user@example.com", True)
```

## Rollback Plan

If issues arise:

1. Set `USE_DATABASE_PROFILE_MANAGER=false` in `.env`
2. The system will revert to using `users.json`
3. Restore from `users.json.backup` if needed

## Monitoring

### Check Database Connections

```sql
SELECT count(*) FROM pg_stat_activity 
WHERE datname = 'kindle_db';
```

### View Active Queries

```sql
SELECT pid, usename, application_name, client_addr, query 
FROM pg_stat_activity 
WHERE datname = 'kindle_db' AND state = 'active';
```

### Table Statistics

```sql
SELECT 
    schemaname,
    tablename,
    n_tup_ins as inserts,
    n_tup_upd as updates,
    n_tup_del as deletes
FROM pg_stat_user_tables
WHERE schemaname = 'kindle_automator';
```

## Backup and Recovery

### Manual Backup

```bash
# Local
make db-backup

# Staging
make db-backup-staging

# Production
make db-backup-prod
```

### Restore from Backup

```bash
# Local
make db-restore FILE=backups/kindle_db_YYYYMMDD_HHMMSS.sql

# For staging/production, use psql directly with DATABASE_URL
psql $DATABASE_URL < kindle_backup.sql
```

### Automated Backups

Add to crontab for daily backups:

```bash
0 2 * * * pg_dump -U kindle_user -d kindle_db -n kindle_automator > /backup/kindle_$(date +\%Y\%m\%d).sql
```

## Troubleshooting

### Connection Issues

1. Check PostgreSQL is running: `sudo systemctl status postgresql`
2. Verify connection string in `.env`
3. Check PostgreSQL logs: `/var/log/postgresql/`

### Migration Errors

1. Check migration logs in console output
2. Verify all environment variables are set
3. Ensure PostgreSQL user has proper permissions

### Performance Issues

1. Check for missing indexes:
   ```sql
   SELECT * FROM pg_stat_user_indexes 
   WHERE schemaname = 'kindle_automator';
   ```

2. Analyze query performance:
   ```sql
   EXPLAIN ANALYZE <your_query>;
   ```

3. Update table statistics:
   ```sql
   ANALYZE kindle_automator.users;
   ```

## Next Steps

After migrating AVD Profile Manager, the VNC Instance Manager (`vnc_instance_map.json`) can be migrated using the same pattern:

1. Create VNC-related tables
2. Implement VNCRepository
3. Refactor VNCManager
4. Migrate data
5. Test and deploy