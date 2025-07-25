-- This script initializes the Kindle Automator database
-- It assumes the database already exists (created with appropriate name for environment)
-- We use the default 'public' schema since each environment has its own database

-- For local development with Docker, grant privileges to the local user
-- For staging/production, the user from DATABASE_URL will already have appropriate permissions
DO $$
BEGIN
    -- Check if 'local' user exists (indicating local development)
    IF EXISTS (SELECT 1 FROM pg_user WHERE usename = 'local') THEN
        GRANT ALL ON SCHEMA public TO local;
        GRANT ALL ON ALL TABLES IN SCHEMA public TO local;
        GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO local;
        
        -- Set default privileges for future tables
        ALTER DEFAULT PRIVILEGES IN SCHEMA public 
        GRANT ALL ON TABLES TO local;
        
        ALTER DEFAULT PRIVILEGES IN SCHEMA public 
        GRANT ALL ON SEQUENCES TO local;
    END IF;
END $$;