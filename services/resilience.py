"""
Advanced Resilience Module for LatterPay
=========================================
Production-grade resilience patterns for robust error handling:
- Circuit Breaker: Prevents cascading failures
- Rate Limiter: Protects against abuse
- Retry with Exponential Backoff: Resilient external calls
- Request validation and sanitization
"""


import time
import threading
import functools
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable, Optional, Any, Dict
from enum import Enum
import re
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)


# ============================================================================
# CIRCUIT BREAKER PATTERN
# ============================================================================

class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, rejecting requests
    HALF_OPEN = "half_open" # Testing if service recovered


class CircuitBreaker:
    """
    Circuit Breaker implementation to prevent cascading failures.
    
    States:
    - CLOSED: Normal operation, all requests pass through
    - OPEN: Service is failing, reject all requests immediately  
    - HALF_OPEN: Testing recovery, allow one request through
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        expected_exceptions: tuple = (Exception,)
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._lock = threading.RLock()
        
    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if self._last_failure_time and \
                   datetime.now() - self._last_failure_time > timedelta(seconds=self.recovery_timeout):
                    self._state = CircuitState.HALF_OPEN
                    logger.info("Circuit breaker transitioning to HALF_OPEN state")
            return self._state
    
    def record_failure(self, exception: Exception) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = datetime.now()
            
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(f"Circuit breaker OPEN after {self._failure_count} failures")
    
    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            logger.debug("Circuit breaker reset to CLOSED state")
    
    def __call__(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_state = self.state
            
            if current_state == CircuitState.OPEN:
                logger.warning(f"Circuit breaker OPEN for {func.__name__}, rejecting request")
                raise CircuitBreakerOpenError(
                    f"Service temporarily unavailable. Please try again later."
                )
            
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except self.expected_exceptions as e:
                self.record_failure(e)
                raise
                
        return wrapper


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and rejecting requests."""
    pass


# ============================================================================
# RATE LIMITER (Token Bucket Algorithm)
# ============================================================================

class RateLimiter:
    """
    Token Bucket Rate Limiter for protecting against abuse.
    
    Features:
    - Per-user rate limiting
    - Configurable limits and refill rates
    - Thread-safe implementation
    """
    
    def __init__(
        self,
        max_tokens: int = 30,
        refill_rate: float = 1.0,  # tokens per second
        refill_amount: int = 1
    ):
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.refill_amount = refill_amount
        
        self._buckets: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"tokens": max_tokens, "last_refill": time.time()}
        )
        self._lock = threading.RLock()
    
    def _refill(self, bucket: Dict[str, Any]) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - bucket["last_refill"]
        refill_amount = int(elapsed * self.refill_rate) * self.refill_amount
        
        if refill_amount > 0:
            bucket["tokens"] = min(self.max_tokens, bucket["tokens"] + refill_amount)
            bucket["last_refill"] = now
    
    def is_allowed(self, identifier: str, tokens_required: int = 1) -> bool:
        """Check if request is allowed for given identifier."""
        with self._lock:
            bucket = self._buckets[identifier]
            self._refill(bucket)
            
            if bucket["tokens"] >= tokens_required:
                bucket["tokens"] -= tokens_required
                return True
            
            logger.warning(f"Rate limit exceeded for {identifier}")
            return False
    
    def get_retry_after(self, identifier: str, tokens_required: int = 1) -> float:
        """Get seconds until tokens will be available."""
        with self._lock:
            bucket = self._buckets[identifier]
            tokens_needed = tokens_required - bucket["tokens"]
            
            if tokens_needed <= 0:
                return 0
            
            return tokens_needed / (self.refill_rate * self.refill_amount)


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after:.1f} seconds.")


# ============================================================================
# RETRY WITH EXPONENTIAL BACKOFF
# ============================================================================

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    retryable_exceptions: tuple = (Exception,)
):
    """
    Decorator for retrying functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        exponential_base: Base for exponential increase
        retryable_exceptions: Tuple of exceptions to retry on
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        delay = min(
                            base_delay * (exponential_base ** attempt),
                            max_delay
                        )
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries + 1} failed for {func.__name__}: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries + 1} attempts failed for {func.__name__}: {e}"
                        )
            
            raise last_exception
        return wrapper
    return decorator


# ============================================================================
# INPUT VALIDATION & SANITIZATION
# ============================================================================

class InputValidator:
    """
    Comprehensive input validation and sanitization for WhatsApp messages.
    """
    
    # Regex patterns for validation
    PHONE_PATTERN = re.compile(r'^(0|263)\d{9,10}$')
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    AMOUNT_PATTERN = re.compile(r'^\d+(\.\d{1,2})?$')
    NAME_PATTERN = re.compile(r'^[a-zA-Z\s\'-]{2,100}$')
    
    # XSS/Injection prevention patterns
    DANGEROUS_PATTERNS = [
        re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
        re.compile(r'javascript:', re.IGNORECASE),
        re.compile(r'on\w+\s*=', re.IGNORECASE),
        re.compile(r'--'),  # SQL comment
        re.compile(r';.*?(drop|delete|insert|update|select)', re.IGNORECASE),
    ]
    
    @classmethod
    def sanitize_message(cls, message: str) -> str:
        """Remove potentially dangerous content from messages."""
        if not message:
            return ""
        
        # Limit message length
        message = message[:2000]
        
        # Remove dangerous patterns
        for pattern in cls.DANGEROUS_PATTERNS:
            message = pattern.sub('', message)
        
        # Strip excessive whitespace
        message = ' '.join(message.split())
        
        return message.strip()
    
    @classmethod
    def validate_phone(cls, phone: str) -> tuple[bool, str]:
        """Validate and normalize phone number."""
        if not phone:
            return False, "Phone number is required"
        
        # Remove spaces and dashes
        phone = re.sub(r'[\s\-\(\)]', '', phone)
        
        if not cls.PHONE_PATTERN.match(phone):
            return False, "Invalid phone number format. Use 0771234567 or 263771234567"
        
        # Normalize to international format
        if phone.startswith('0'):
            phone = '263' + phone[1:]
        
        return True, phone
    
    @classmethod
    def validate_email(cls, email: str) -> tuple[bool, str]:
        """Validate email address."""
        if not email:
            return False, "Email is required"
        
        email = email.strip().lower()
        
        if not cls.EMAIL_PATTERN.match(email):
            return False, "Invalid email format"
        
        return True, email
    
    @classmethod
    def validate_amount(cls, amount_str: str) -> tuple[bool, float, str]:
        """Validate payment amount."""
        if not amount_str:
            return False, 0.0, "Amount is required"
        
        amount_str = amount_str.strip().replace(',', '.')
        
        if not cls.AMOUNT_PATTERN.match(amount_str):
            return False, 0.0, "Invalid amount format. Use numbers like 50 or 50.00"
        
        amount = float(amount_str)
        
        if amount <= 0:
            return False, 0.0, "Amount must be greater than zero"
        
        if amount > 480:
            return False, 0.0, "Maximum amount is 480"
        
        return True, amount, ""
    
    @classmethod
    def validate_name(cls, name: str) -> tuple[bool, str]:
        """Validate name input."""
        if not name:
            return False, "Name is required"
        
        name = ' '.join(name.split()).strip()
        
        if len(name) < 2:
            return False, "Name is too short"
        
        if len(name) > 100:
            return False, "Name is too long"
        
        if not cls.NAME_PATTERN.match(name):
            return False, "Name contains invalid characters"
        
        return True, name.title()


# ============================================================================
# DATABASE CONNECTION POOL
# ============================================================================

class DatabasePool:
    """
    Thread-safe SQLite connection pool with automatic cleanup.
    """
    
    def __init__(self, db_path: str = "botdata.db", max_connections: int = 10, timeout: int = 30):
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        self._pool: list = []
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
        conn = None
        
        with self._condition:
            # Wait for available connection or create new one
            while not self._pool and len(self._pool) >= self.max_connections:
                self._condition.wait(timeout=self.timeout)
            
            if self._pool:
                conn = self._pool.pop()
            else:
                conn = sqlite3.connect(
                    self.db_path, 
                    timeout=self.timeout,
                    check_same_thread=False
                )
                conn.row_factory = sqlite3.Row
        
        try:
            yield conn
        except Exception:
            # Don't return broken connections to pool
            try:
                conn.close()
            except:
                pass
            raise
        else:
            # Return connection to pool
            with self._condition:
                if len(self._pool) < self.max_connections:
                    self._pool.append(conn)
                    self._condition.notify()
                else:
                    conn.close()
    
    def close_all(self):
        """Close all connections in the pool."""
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except:
                    pass
            self._pool.clear()


# ============================================================================
# REQUEST TRACKING & METRICS
# ============================================================================

class RequestTracker:
    """
    Track request metrics for observability.
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "rate_limited_requests": 0,
            "circuit_breaker_rejections": 0,
            "avg_response_time_ms": 0.0,
            "requests_by_endpoint": defaultdict(int),
            "errors_by_type": defaultdict(int),
        }
        self._response_times: list = []
    
    def record_request(self, endpoint: str, duration_ms: float, success: bool, error_type: str = None):
        """Record metrics for a request."""
        with self._lock:
            self._metrics["total_requests"] += 1
            self._metrics["requests_by_endpoint"][endpoint] += 1
            
            if success:
                self._metrics["successful_requests"] += 1
            else:
                self._metrics["failed_requests"] += 1
                if error_type:
                    self._metrics["errors_by_type"][error_type] += 1
            
            # Keep last 1000 response times for average
            self._response_times.append(duration_ms)
            if len(self._response_times) > 1000:
                self._response_times.pop(0)
            
            self._metrics["avg_response_time_ms"] = sum(self._response_times) / len(self._response_times)
    
    def record_rate_limit(self):
        with self._lock:
            self._metrics["rate_limited_requests"] += 1
    
    def record_circuit_breaker_rejection(self):
        with self._lock:
            self._metrics["circuit_breaker_rejections"] += 1
    
    def get_metrics(self) -> dict:
        """Get current metrics snapshot."""
        with self._lock:
            return {
                **self._metrics,
                "requests_by_endpoint": dict(self._metrics["requests_by_endpoint"]),
                "errors_by_type": dict(self._metrics["errors_by_type"]),
            }


# ============================================================================
# GLOBAL INSTANCES
# ============================================================================

# Create global instances for use throughout the application
rate_limiter = RateLimiter(max_tokens=30, refill_rate=0.5)
payment_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
whatsapp_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
db_pool = DatabasePool()
request_tracker = RequestTracker()
input_validator = InputValidator()


def get_health_status() -> dict:
    """Get overall health status of the application."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "payment_service": {
                "circuit_state": payment_circuit_breaker.state.value
            },
            "whatsapp_service": {
                "circuit_state": whatsapp_circuit_breaker.state.value
            },
            "rate_limiter": {
                "enabled": True,
                "max_tokens": rate_limiter.max_tokens
            }
        },
        "metrics": request_tracker.get_metrics()
    }
