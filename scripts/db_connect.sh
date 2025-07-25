#!/bin/bash
# Database connection utility for Makefile commands
# Detects if running locally with Docker or remotely with DATABASE_URL

set -e

# Default values
DEFAULT_ENV_FILE=".env"
DOCKER_CONTAINER="sol_postgres"
LOCAL_DB_PORT="5496"
LOCAL_DB_USER="local"
LOCAL_DB_NAME="sol_dev"
KINDLE_DB_NAME="kindle_db"
KINDLE_SCHEMA="kindle_automator"

# Parse command line arguments
COMMAND=""
SQL_FILE=""
ENV_FILE="$DEFAULT_ENV_FILE"
PSQL_ARGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --env)
            ENV_FILE="$2"
            shift 2
            ;;
        --command)
            COMMAND="$2"
            shift 2
            ;;
        --file)
            SQL_FILE="$2"
            shift 2
            ;;
        --args)
            PSQL_ARGS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Load environment file if it exists
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

# Function to check if Docker container is running
is_docker_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${DOCKER_CONTAINER}$"
}

# Function to execute psql command
execute_psql() {
    local psql_cmd="$1"
    local use_kindle_db="${2:-false}"
    
    if is_docker_running; then
        # Use Docker container
        local db_name="$LOCAL_DB_NAME"
        if [ "$use_kindle_db" = "true" ]; then
            db_name="$KINDLE_DB_NAME"
        fi
        
        if [ -n "$SQL_FILE" ] && [ -f "$SQL_FILE" ]; then
            docker exec -i "$DOCKER_CONTAINER" psql -p "$LOCAL_DB_PORT" -U "$LOCAL_DB_USER" -d "$db_name" < "$SQL_FILE"
        else
            docker exec -i "$DOCKER_CONTAINER" psql -p "$LOCAL_DB_PORT" -U "$LOCAL_DB_USER" -d "$db_name" -c "$psql_cmd"
        fi
    else
        # Use DATABASE_URL from environment
        if [ -z "$DATABASE_URL" ]; then
            echo "Error: DATABASE_URL not set and Docker container '$DOCKER_CONTAINER' not running"
            exit 1
        fi
        
        if [ -n "$SQL_FILE" ] && [ -f "$SQL_FILE" ]; then
            psql "$DATABASE_URL" < "$SQL_FILE"
        else
            psql "$DATABASE_URL" -c "$psql_cmd"
        fi
    fi
}

# Function for interactive psql session
interactive_psql() {
    if is_docker_running; then
        docker exec -it "$DOCKER_CONTAINER" psql -p "$LOCAL_DB_PORT" -U "$LOCAL_DB_USER" -d "$KINDLE_DB_NAME"
    else
        if [ -z "$DATABASE_URL" ]; then
            echo "Error: DATABASE_URL not set and Docker container '$DOCKER_CONTAINER' not running"
            exit 1
        fi
        psql "$DATABASE_URL"
    fi
}

# Function for pg_dump
execute_pg_dump() {
    local output_file="$1"
    
    if is_docker_running; then
        docker exec "$DOCKER_CONTAINER" pg_dump -p "$LOCAL_DB_PORT" -U "$LOCAL_DB_USER" -d "$KINDLE_DB_NAME" -n "$KINDLE_SCHEMA" > "$output_file"
    else
        if [ -z "$DATABASE_URL" ]; then
            echo "Error: DATABASE_URL not set and Docker container '$DOCKER_CONTAINER' not running"
            exit 1
        fi
        # Extract schema from DATABASE_URL if needed
        pg_dump "$DATABASE_URL" -n "$KINDLE_SCHEMA" > "$output_file"
    fi
}

# Main execution logic
case "$COMMAND" in
    "init")
        # Initialize database (use sol_dev for local, otherwise use DATABASE_URL)
        execute_psql "" false
        ;;
    "query")
        # Execute a query on kindle_db
        # PSQL_ARGS contains the full query
        execute_psql "$PSQL_ARGS" true
        ;;
    "interactive")
        # Interactive psql session
        interactive_psql
        ;;
    "dump")
        # Database dump
        execute_pg_dump "$PSQL_ARGS"
        ;;
    *)
        echo "Usage: $0 --command {init|query|interactive|dump} [--env ENV_FILE] [--file SQL_FILE] [--args PSQL_ARGS]"
        exit 1
        ;;
esac