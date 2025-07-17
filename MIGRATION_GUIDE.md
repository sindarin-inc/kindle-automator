# Migration Guide: users.json to PostgreSQL

## Quick Start

1. **Install dependencies:**
   ```bash
   make deps
   ```

2. **Initialize database in sol_postgres:**
   ```bash
   make db-init
   ```

3. **Run migrations:**
   ```bash
   make db-migrate
   ```

4. **Import existing data:**
   ```bash
   make db-import
   ```

Or do all steps at once:
```bash
make db-setup
```

## What Changed

- `users.json` → PostgreSQL database with proper schema
- File-based storage → SQLAlchemy 2.0 ORM
- No more race conditions → Atomic database transactions
- Manual JSON updates → Automatic database operations

## Key Benefits

- **Atomic operations** - No more corrupted JSON from concurrent writes
- **Better performance** - Indexed queries, connection pooling
- **Data integrity** - Foreign keys, constraints, transactions
- **Scalability** - Multiple Flask processes can run safely

## Testing

Run tests to verify everything works:
```bash
# Unit tests
pytest tests/test_user_repository.py -v

# Concurrent access tests
python tests/test_concurrent_access.py
```

## Database Connection

The system connects to the existing `sol_postgres` container on port 5496. The connection details are in `.env`:
```
DATABASE_URL=postgresql://kindle_user:kindle_password@localhost:5496/kindle_db
```

## Database Management Commands

- `make db-connect` - Connect to database with psql
- `make db-status` - Show table counts
- `make db-activity` - Show recent user activity
- `make db-backup` - Backup the database
- `make db-restore FILE=backup.sql` - Restore from backup

## No Going Back

Once migrated, the system uses PostgreSQL exclusively. The old `users.json` is backed up to `users.json.backup` but is no longer used.