-- This script initializes the Kindle Automator database schema
-- It assumes the database already exists (created with appropriate name for environment)

-- Create schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS kindle_automator;

-- For local development with Docker, grant privileges to the local user
-- For staging/production, the user from DATABASE_URL will already have appropriate permissions
DO $$
BEGIN
    -- Check if 'local' user exists (indicating local development)
    IF EXISTS (SELECT 1 FROM pg_user WHERE usename = 'local') THEN
        GRANT ALL ON SCHEMA kindle_automator TO local;
        GRANT ALL ON ALL TABLES IN SCHEMA kindle_automator TO local;
        GRANT ALL ON ALL SEQUENCES IN SCHEMA kindle_automator TO local;
        
        -- Set default privileges for future tables
        ALTER DEFAULT PRIVILEGES IN SCHEMA kindle_automator 
        GRANT ALL ON TABLES TO local;
        
        ALTER DEFAULT PRIVILEGES IN SCHEMA kindle_automator 
        GRANT ALL ON SEQUENCES TO local;
    END IF;
END $$;