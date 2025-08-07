"""Redis connection management for request deduplication and cancellation."""

import logging
import os
from typing import Optional

import redis
from redis.exceptions import ConnectionError, RedisError

logger = logging.getLogger(__name__)


class RedisConnection:
    """Manages Redis connection with retry logic and connection pooling."""

    _instance: Optional["RedisConnection"] = None
    _client: Optional[redis.Redis] = None

    def __new__(cls) -> "RedisConnection":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is None:
            self._initialize_client()

    def _initialize_client(self):
        """Initialize Redis client with connection pool."""
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6479/1")
        logger.debug(f"Initializing Redis connection to {redis_url}")

        try:
            # For macOS, we need to use the direct connection method instead of from_url
            # due to socket options compatibility issues
            if "localhost:6479" in redis_url or "127.0.0.1:6479" in redis_url:
                # Use direct connection for the sol_redis container
                pool = redis.ConnectionPool(
                    host="localhost",
                    port=6479,
                    db=1,
                    max_connections=50,
                    decode_responses=False,
                )
            elif redis_url.startswith("rediss://"):
                # SSL/TLS connection (DigitalOcean Managed Redis uses this)
                # Use direct Redis.from_url for SSL connections
                self._client = redis.from_url(
                    redis_url,
                    max_connections=50,
                    decode_responses=False,
                    ssl_cert_reqs=None,  # Don't verify certificates for managed Redis
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                )
                # Skip the pool creation for SSL connections
                pool = None
            else:
                # Standard Redis connection without socket_keepalive_options on Linux
                # to avoid the "Invalid argument" error
                pool = redis.ConnectionPool.from_url(
                    redis_url,
                    max_connections=50,
                    decode_responses=False,  # We'll handle encoding/decoding ourselves for pickle support
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                )

            # Only create client from pool if we haven't already created it (SSL case)
            if pool is not None:
                self._client = redis.Redis(connection_pool=pool)

            # Test the connection
            if self._client:
                self._client.ping()
                logger.debug(f"Successfully connected to Redis at {redis_url}")

        except (ConnectionError, RedisError) as e:
            logger.error(f"Failed to connect to Redis at {redis_url}: {e}")
            self._client = None

    @property
    def client(self) -> Optional[redis.Redis]:
        """Get the Redis client, attempting to reconnect if necessary."""
        if self._client is None:
            self._initialize_client()

        if self._client:
            try:
                # Test the connection
                self._client.ping()
            except (ConnectionError, RedisError):
                logger.warning("Redis connection lost, attempting to reconnect...")
                self._initialize_client()

        return self._client

    def is_available(self) -> bool:
        """Check if Redis is available and connected."""
        return self.client is not None

    @classmethod
    def get_instance(cls) -> "RedisConnection":
        """Get the singleton instance of RedisConnection."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def get_redis_client() -> Optional[redis.Redis]:
    """Convenience function to get the Redis client."""
    connection = RedisConnection.get_instance()
    return connection.client
