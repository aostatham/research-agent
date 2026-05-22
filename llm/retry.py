import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)

# HTTP status codes worth retrying
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# Anthropic SDK exception names worth retrying
RETRYABLE_ANTHROPIC_EXCEPTIONS = {
    "RateLimitError",
    "InternalServerError",
    "APIStatusError",
}


def with_retry(max_attempts: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
    """
    Decorator that retries a function with exponential backoff.

    Delay sequence: 1s, 2s, 4s, 8s... capped at max_delay.

    Args:
        max_attempts: Maximum number of attempts (including the first)
        base_delay:   Initial delay in seconds
        max_delay:    Maximum delay in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    if not _is_retryable(e):
                        raise

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
                    delay = min(delay * 2, max_delay)

        return wrapper
    return decorator


def _is_retryable(exception: Exception) -> bool:
    """Determine if an exception is worth retrying."""
    exc_type = type(exception).__name__

    # Anthropic SDK exceptions
    if exc_type in RETRYABLE_ANTHROPIC_EXCEPTIONS:
        return True

    # HTTP errors with retryable status codes
    if hasattr(exception, "status_code"):
        return exception.status_code in RETRYABLE_STATUS_CODES

    # requests.exceptions.HTTPError
    if hasattr(exception, "response") and hasattr(exception.response, "status_code"):
        return exception.response.status_code in RETRYABLE_STATUS_CODES

    return False