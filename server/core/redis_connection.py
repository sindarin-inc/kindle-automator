"""Redis connection management for request deduplication and cancellation."""

import logging
import os
import threading
import time
from typing import Optional

import redis
from redis.exceptions import ConnectionError, RedisError

logger = logging.getLogger(__name__)


class RedisConnection:
    """Manages Redis connection with retry logic and connection pooling."""

    _instance: Optional["RedisConnection"] = None
    _client: Optional[redis.Redis] = None
    _initialized: bool = False
    _connection_attempts: int = 0
    _last_connection_attempt: float = 0

    def __new__(cls) -> "RedisConnection":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once for the singleton
        if not RedisConnection._initialized:
            logger.info(
                f"[REDIS INIT] First initialization - PID: {os.getpid()}, Thread: {threading.current_thread().name}"
            )
            RedisConnection._initialized = True
            self._initialize_client()
        else:
            logger.debug(
                f"[REDIS INIT] Singleton already initialized - PID: {os.getpid()}, Thread: {threading.current_thread().name}"
            )

    def _initialize_client(self):
        """Initialize Redis client with connection pool."""
        # Circuit breaker: prevent rapid reconnection attempts
        now = time.time()
        if self._last_connection_attempt and (now - self._last_connection_attempt) < 1.0:
            logger.warning(f"[REDIS CONNECT] Skipping connection attempt - too soon since last attempt")
            return

        self._last_connection_attempt = now
        self._connection_attempts += 1

        if self._connection_attempts > 10:
            logger.error(
                f"[REDIS CONNECT] Too many connection attempts ({self._connection_attempts}), giving up"
            )
            return

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6479/1")
        start_time = time.time()
        logger.info(
            f"[REDIS CONNECT] Starting connection attempt #{self._connection_attempts} to {redis_url} at {time.strftime('%Y-%m-%d %H:%M:%S')} - PID: {os.getpid()}"
        )

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
                logger.info(f"[REDIS CONNECT] Using SSL/TLS connection for DigitalOcean Redis")
                # Use direct Redis.from_url for SSL connections
                self._client = redis.from_url(
                    redis_url,
                    max_connections=50,
                    decode_responses=False,
                    ssl_cert_reqs=None,  # Don't verify certificates for managed Redis
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                    # Don't use socket_keepalive_options - causes Error 22 on Linux
                )
                logger.info(f"[REDIS CONNECT] Redis client created, testing connection...")
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
                ping_start = time.time()
                self._client.ping()
                ping_time = time.time() - ping_start
                total_time = time.time() - start_time
                logger.info(
                    f"[REDIS CONNECT] SUCCESS - Connected to Redis at {redis_url} - Ping: {ping_time:.3f}s, Total: {total_time:.3f}s"
                )

                # Test a simple set/get operation
                test_key = f"test:connection:{os.getpid()}:{time.time()}"
                test_value = "test_connection"
                self._client.set(test_key, test_value, ex=10)  # Expire in 10 seconds
                retrieved = self._client.get(test_key)
                if retrieved != test_value.encode():
                    logger.error(
                        f"[REDIS CONNECT] Data integrity check failed! Set: {test_value}, Got: {retrieved}"
                    )
                else:
                    logger.info(f"[REDIS CONNECT] Data integrity check passed")
                    # Reset connection attempts on successful connection
                    self._connection_attempts = 0

        except (ConnectionError, RedisError) as e:
            total_time = time.time() - start_time
            logger.error(
                f"[REDIS CONNECT] FAILED after {total_time:.3f}s - {redis_url}: {type(e).__name__}: {e}"
            )
            self._client = None
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(
                f"[REDIS CONNECT] UNEXPECTED ERROR after {total_time:.3f}s - {type(e).__name__}: {e}",
                exc_info=True,
            )
            self._client = None

    @property
    def client(self) -> Optional[redis.Redis]:
        """Get the Redis client, attempting to reconnect if necessary."""
        if self._client is None:
            logger.warning(f"[REDIS CLIENT] No client exists, initializing... PID: {os.getpid()}")
            self._initialize_client()

        if self._client:
            try:
                # Test the connection
                ping_start = time.time()
                self._client.ping()
                ping_time = time.time() - ping_start
                if ping_time > 1.0:
                    logger.warning(f"[REDIS CLIENT] Slow ping response: {ping_time:.3f}s")
            except (ConnectionError, RedisError) as e:
                logger.error(
                    f"[REDIS CLIENT] Connection lost ({type(e).__name__}: {e}), attempting to reconnect..."
                )
                self._initialize_client()
            except Exception as e:
                logger.error(
                    f"[REDIS CLIENT] Unexpected error during ping: {type(e).__name__}: {e}", exc_info=True
                )
                self._client = None

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
    caller_frame = None
    try:
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_frame = f"{frame.f_back.f_code.co_filename}:{frame.f_back.f_lineno}"
    except:
        pass

    logger.debug(f"[REDIS GET] get_redis_client called from {caller_frame or 'unknown'} - PID: {os.getpid()}")
    connection = RedisConnection.get_instance()
    return connection.client
