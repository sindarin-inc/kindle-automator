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
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6479/0")
        logger.info(f"Initializing Redis connection to {redis_url}")

        try:
            # For macOS, we need to use the direct connection method instead of from_url
            # due to socket options compatibility issues
            if "localhost:6479" in redis_url or "127.0.0.1:6479" in redis_url:
                # Use direct connection for the sol_redis container
                pool = redis.ConnectionPool(
                    host="localhost",
                    port=6479,
                    db=0,
                    max_connections=50,
                    decode_responses=False,
                )
            else:
                pool = redis.ConnectionPool.from_url(
                    redis_url,
                    max_connections=50,
                    socket_keepalive=True,
                    socket_keepalive_options={
                        1: 1,  # TCP_KEEPIDLE
                        2: 3,  # TCP_KEEPINTVL
                        3: 5,  # TCP_KEEPCNT
                    },
                    decode_responses=False,  # We'll handle encoding/decoding ourselves for pickle support
                )

            self._client = redis.Redis(connection_pool=pool)

            # Test the connection
            self._client.ping()
            logger.info(f"Successfully connected to Redis at {redis_url}")

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
