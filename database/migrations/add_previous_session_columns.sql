-- Migration to add columns for storing previous session data
-- This allows handling navigation requests with old session keys after book reopening

-- Add columns to store previous session data
ALTER TABLE book_sessions ADD COLUMN IF NOT EXISTS previous_session_key VARCHAR(255);
ALTER TABLE book_sessions ADD COLUMN IF NOT EXISTS previous_position INTEGER;

-- These columns are nullable since they're only populated when a book is reopened