-- First connect to sol_dev to create kindle_db if needed
\c sol_dev

-- Create kindle_db database if it doesn't exist
SELECT 'CREATE DATABASE kindle_db'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'kindle_db')\gexec

-- Now connect to kindle_db
\c kindle_db

-- Create schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS kindle_automator;

-- Grant schema privileges to local user (the existing user)
GRANT ALL ON SCHEMA kindle_automator TO local;
GRANT ALL ON ALL TABLES IN SCHEMA kindle_automator TO local;
GRANT ALL ON ALL SEQUENCES IN SCHEMA kindle_automator TO local;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA kindle_automator 
GRANT ALL ON TABLES TO local;

ALTER DEFAULT PRIVILEGES IN SCHEMA kindle_automator 
GRANT ALL ON SEQUENCES TO local;