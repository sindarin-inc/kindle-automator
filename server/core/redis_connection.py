"""Redis connection management for request deduplication and cancellation."""

import logging
import os
import threading
import time
from typing import Any, Optional

import redis
from redis.exceptions import ConnectionError, RedisError

from server.utils.ansi_colors import CYAN, DIM_GRAY, RESET

logger = logging.getLogger(__name__)
# Dedicated logger for Redis commands that only goes to debug log, not email logs
redis_logger = logging.getLogger("redis_commands")


class LoggingRedisClient:
    """Wrapper around Redis client that logs all commands to debug log."""

    def __init__(self, redis_client: redis.Redis):
        self._client = redis_client
        self._redis_logging_enabled = None
        self._check_logging_config()

    def _check_logging_config(self):
        """Check if Redis logging is enabled from environment variable."""
        redis_logging = os.getenv("REDIS_LOGGING", "true").lower()
        self._redis_logging_enabled = redis_logging not in ["false", "0", "no", "off"]

        if self._redis_logging_enabled:
            redis_logger.debug(
                f"{DIM_GRAY}Redis command logging enabled (set REDIS_LOGGING=false to disable){RESET}"
            )

    def _format_value(self, value: Any, max_length: int = 100) -> str:
        """Format a Redis value for logging, truncating if needed."""
        if value is None:
            return "None"

        if isinstance(value, bytes):
            try:
                # Try to decode as string
                str_value = value.decode("utf-8")
                if len(str_value) > max_length:
                    return f"'{str_value[:max_length]}...' ({len(str_value)} chars)"
                return f"'{str_value}'"
            except:
                # If can't decode, show as bytes
                if len(value) > max_length:
                    return f"<bytes: {len(value)} bytes>"
                return f"<bytes: {value[:20]!r}...>"

        if isinstance(value, str):
            if len(value) > max_length:
                return f"'{value[:max_length]}...' ({len(value)} chars)"
            return f"'{value}'"

        if isinstance(value, (list, tuple)):
            if len(value) > 5:
                items = [self._format_value(v, 20) for v in value[:5]]
                return f"[{', '.join(items)}, ... ({len(value)} items)]"
            items = [self._format_value(v, 50) for v in value]
            return f"[{', '.join(items)}]"

        if isinstance(value, dict):
            if len(value) > 3:
                items = []
                for i, (k, v) in enumerate(value.items()):
                    if i >= 3:
                        items.append(f"... ({len(value)} keys)")
                        break
                    items.append(f"{k}: {self._format_value(v, 20)}")
                return f"{{{', '.join(items)}}}"
            items = [f"{k}: {self._format_value(v, 30)}" for k, v in value.items()]
            return f"{{{', '.join(items)}}}"

        return str(value)

    def _log_command(
        self,
        command: str,
        args: tuple,
        kwargs: dict,
        result: Any = None,
        error: Exception = None,
        duration_ms: float = None,
    ):
        """Log a Redis command with formatting."""
        if not self._redis_logging_enabled:
            return

        # Format command and arguments
        cmd_parts = [command.upper()]
        for arg in args:
            cmd_parts.append(self._format_value(arg))

        if kwargs:
            for k, v in kwargs.items():
                cmd_parts.append(f"{k}={self._format_value(v)}")

        cmd_str = " ".join(cmd_parts)

        # Format timing
        if duration_ms is not None:
            if duration_ms > 10:
                time_str = f"{duration_ms:.1f}ms"
            else:
                time_str = f"{duration_ms:.2f}ms"
        else:
            time_str = ""

        # Log to dedicated Redis logger (only goes to debug log, not email logs)
        if error:
            redis_logger.debug(
                f"{DIM_GRAY}[{time_str}] {CYAN}{cmd_str}{RESET} {DIM_GRAY}→ ERROR: {error}{RESET}"
            )
        elif result is not None:
            # Format result
            result_str = self._format_value(result)
            redis_logger.debug(
                f"{DIM_GRAY}[{time_str}] {CYAN}{cmd_str}{RESET} {DIM_GRAY}→ {result_str}{RESET}"
            )
        else:
            redis_logger.debug(f"{DIM_GRAY}[{time_str}] {CYAN}{cmd_str}{RESET}")

    def __getattr__(self, name):
        """Proxy all method calls to the underlying Redis client with logging."""
        attr = getattr(self._client, name)

        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = attr(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                self._log_command(name, args, kwargs, result=result, duration_ms=duration_ms)
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                self._log_command(name, args, kwargs, error=e, duration_ms=duration_ms)
                raise

        return wrapper

    # Proxy essential properties
    @property
    def connection_pool(self):
        return self._client.connection_pool


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
                client = redis.from_url(
                    redis_url,
                    max_connections=50,
                    decode_responses=False,
                    ssl_cert_reqs=None,  # Don't verify certificates for managed Redis
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                    # Don't use socket_keepalive_options - causes Error 22 on Linux
                )
                # Check if Redis logging is enabled for SSL client
                redis_logging = os.getenv("REDIS_LOGGING", "false").lower()
                redis_logging_enabled = redis_logging not in ["false", "0", "no", "off"]
                environment = os.getenv("ENVIRONMENT", "").lower()
                is_development = os.getenv("ENVIRONMENT") in [None, "", "dev", "development"]

                if (is_development or environment in ["dev", "staging"]) and redis_logging_enabled:
                    self._client = LoggingRedisClient(client)
                else:
                    self._client = client

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

            # Wrap the client with logging if enabled
            if self._client:
                # Check if Redis logging is enabled
                redis_logging = os.getenv("REDIS_LOGGING", "false").lower()
                redis_logging_enabled = redis_logging not in ["false", "0", "no", "off"]
                environment = os.getenv("ENVIRONMENT", "").lower()
                is_development = os.getenv("ENVIRONMENT") in [None, "", "dev", "development"]

                if (is_development or environment in ["dev", "staging"]) and redis_logging_enabled:
                    self._client = LoggingRedisClient(self._client)

            # Test the connection
            if self._client:
                ping_start = time.time()
                self._client.ping()
                ping_time = time.time() - ping_start
                total_time = time.time() - start_time
                logger.info(
                    f"[REDIS CONNECT] SUCCESS - Connected to Redis at {redis_url} - Ping: {ping_time:.3f}s, Total: {total_time:.3f}s"
                )

                # Log which database we're connected to
                connection_kwargs = self._client.connection_pool.connection_kwargs
                db_num = connection_kwargs.get("db", 0)
                logger.info(f"[REDIS CONNECT] Connected to database {db_num}")

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

    connection = RedisConnection.get_instance()
    return connection.client
