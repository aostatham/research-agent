"""
Exponential-backoff retry decorator for LLM API calls.

Wraps any function with automatic retries on transient failures (rate limits,
server errors).  The delay doubles after each failed attempt and is capped at
max_delay.  Non-retryable errors (bad requests, auth failures, value errors)
are re-raised immediately without retrying.

Usage:
    @with_retry(max_attempts=3, base_delay=1.0, max_delay=30.0)
    def my_api_call(...):
        ...
"""

import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)

# HTTP status codes that indicate a transient server-side problem worth retrying.
# 429 = rate limited, 500/502/503 = server errors, 529 = Anthropic overloaded.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# Anthropic SDK exception class names — used as a fallback when the anthropic
# package is not importable (e.g. in environments that only run Ollama).
# APIStatusError must NOT be included — it is the base class for the entire
# Anthropic status-error hierarchy and would match non-retryable errors such
# as AuthenticationError and BadRequestError (D021).
RETRYABLE_ANTHROPIC_EXCEPTIONS = {
    "RateLimitError",
    "InternalServerError",
}

# Preferred: actual exception classes for isinstance matching (avoids false
# positives from name collisions with non-Anthropic exceptions).
# Falls back to an empty tuple when the anthropic package is not installed.
# APIStatusError excluded — see D021.
try:
    from anthropic import RateLimitError as _AnthropicRateLimitError
    from anthropic import InternalServerError as _AnthropicInternalServerError
    _ANTHROPIC_EXCEPTIONS: tuple = (
        _AnthropicRateLimitError,
        _AnthropicInternalServerError,
    )
except ImportError:
    _ANTHROPIC_EXCEPTIONS = ()


def with_retry(max_attempts: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
    """
    Decorator factory that adds exponential-backoff retry logic to a function.

    Delay sequence: base_delay * 2^(attempt-1), capped at max_delay.
    Example with base_delay=1.0, max_delay=30.0: 1s, 2s, 4s, 8s, 15s, 30s…

    Args:
        max_attempts: Total number of attempts including the first.  A value of
                      3 means one initial try plus up to two retries.
        base_delay:   Seconds to wait before the first retry.
        max_delay:    Upper bound on the inter-retry delay in seconds.

    Returns:
        A decorator that wraps the target function with retry logic.
    """
    def decorator(func):
        @wraps(func)  # preserve __name__, __doc__ etc. on the wrapped function
        def wrapper(*args, **kwargs):
            delay = base_delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    # Re-raise immediately for errors we cannot recover from
                    # (e.g. 400 Bad Request, 401 Unauthorized, ValueError).
                    if not _is_retryable(e):
                        raise

                    # On the final attempt, log and re-raise instead of sleeping.
                    if attempt == max_attempts:
                        logger.error(
                            f"All {max_attempts} attempts failed. Last error: {e}"
                        )
                        raise

                    logger.warning(
                        f"Attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    print(f"  ⚠️  API error, retrying in {delay:.1f}s... "
                          f"(attempt {attempt}/{max_attempts})")
                    time.sleep(delay)
                    # Double the delay, but never exceed max_delay
                    delay = min(delay * 2, max_delay)

        return wrapper
    return decorator


def _is_retryable(exception: Exception) -> bool:
    """
    Decide whether an exception represents a transient failure worth retrying.

    Checks three sources of retryability in order:
    1. isinstance against _ANTHROPIC_EXCEPTIONS when the package is installed;
       falls back to string class name when the package is absent.
    2. Direct status_code attribute (used by Anthropic SDK and httpx)
    3. Nested response.status_code (used by requests.exceptions.HTTPError)

    Args:
        exception: The exception that was raised.

    Returns:
        True if the exception indicates a transient problem; False otherwise.
    """
    # Prefer isinstance when the anthropic package is available — avoids false
    # positives from other libraries that happen to share a class name.
    if _ANTHROPIC_EXCEPTIONS:
        if isinstance(exception, _ANTHROPIC_EXCEPTIONS):
            return True
    else:
        # Fall back to string name when anthropic is not installed.
        if type(exception).__name__ in RETRYABLE_ANTHROPIC_EXCEPTIONS:
            return True

    # httpx / Anthropic SDK attach status_code directly to the exception object.
    if hasattr(exception, "status_code"):
        return exception.status_code in RETRYABLE_STATUS_CODES

    # requests raises HTTPError with a nested response object.
    if hasattr(exception, "response") and hasattr(exception.response, "status_code"):
        return exception.response.status_code in RETRYABLE_STATUS_CODES

    return False
