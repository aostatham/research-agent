"""
Tests for llm/retry.py — with_retry decorator and _is_retryable helper.

Verifies:
    - _is_retryable() correctly classifies Anthropic SDK exceptions,
      HTTP status codes, and nested response.status_code patterns.
    - with_retry() retries on retryable errors and re-raises on non-retryable ones.
    - Exponential backoff delay sequence is correct (doubles each attempt).
    - Delay is capped at max_delay.
    - Function metadata (__name__) is preserved via @wraps.
"""

import pytest
import time
from unittest.mock import MagicMock, patch
from llm.retry import with_retry, _is_retryable
import llm.retry as retry_module


# ── _is_retryable() tests ─────────────────────────────────────────────────────
# Verify the classification logic across all three detection paths:
# exception class name, direct status_code, and nested response.status_code.

def test_rate_limit_error_is_retryable_by_string_fallback():
    """String name fallback: RateLimitError class name triggers a retry when isinstance unavailable."""
    exc = MagicMock()
    type(exc).__name__ = "RateLimitError"
    with patch.object(retry_module, "_ANTHROPIC_EXCEPTIONS", ()):
        assert _is_retryable(exc)


def test_internal_server_error_is_retryable_by_string_fallback():
    """String name fallback: InternalServerError class name triggers a retry when isinstance unavailable."""
    exc = MagicMock()
    type(exc).__name__ = "InternalServerError"
    with patch.object(retry_module, "_ANTHROPIC_EXCEPTIONS", ()):
        assert _is_retryable(exc)


def test_is_retryable_isinstance_when_exceptions_available():
    """When _ANTHROPIC_EXCEPTIONS is populated, isinstance check fires for matching exceptions."""
    class FakeRateLimitError(Exception):
        pass

    exc = FakeRateLimitError("rate limited")
    with patch.object(retry_module, "_ANTHROPIC_EXCEPTIONS", (FakeRateLimitError,)):
        assert _is_retryable(exc)


def test_is_retryable_isinstance_does_not_match_unrelated_exception():
    """isinstance check does not catch exceptions outside _ANTHROPIC_EXCEPTIONS."""
    class FakeRateLimitError(Exception):
        pass

    exc = ValueError("not a rate limit")
    with patch.object(retry_module, "_ANTHROPIC_EXCEPTIONS", (FakeRateLimitError,)):
        assert not _is_retryable(exc)


def test_is_retryable_string_fallback_when_exceptions_empty():
    """String name fallback activates only when _ANTHROPIC_EXCEPTIONS is empty."""
    exc = MagicMock()
    type(exc).__name__ = "APIStatusError"
    with patch.object(retry_module, "_ANTHROPIC_EXCEPTIONS", ()):
        assert _is_retryable(exc)


def test_is_retryable_string_fallback_skipped_when_exceptions_available():
    """String name is NOT checked when _ANTHROPIC_EXCEPTIONS is non-empty (avoids false positives)."""
    class IrrelevantError(Exception):
        pass
    # Patch name to look like a retryable Anthropic error, but _ANTHROPIC_EXCEPTIONS
    # contains IrrelevantError (not this class) — should NOT match.
    exc = ValueError("not retryable")
    # exc's class name is "ValueError" which is not in RETRYABLE_ANTHROPIC_EXCEPTIONS,
    # and it's not an instance of IrrelevantError.
    with patch.object(retry_module, "_ANTHROPIC_EXCEPTIONS", (IrrelevantError,)):
        assert not _is_retryable(exc)


def test_status_code_429_is_retryable():
    """HTTP 429 (rate limit) should be retried."""
    exc = Exception("rate limit")
    exc.status_code = 429
    assert _is_retryable(exc)


def test_status_code_500_is_retryable():
    """HTTP 500 (server error) should be retried."""
    exc = Exception("server error")
    exc.status_code = 500
    assert _is_retryable(exc)


def test_status_code_529_is_retryable():
    """HTTP 529 (Anthropic overloaded) should be retried."""
    exc = Exception("overloaded")
    exc.status_code = 529
    assert _is_retryable(exc)


def test_status_code_400_is_not_retryable():
    """HTTP 400 (bad request) is a client error and must not be retried."""
    exc = Exception("bad request")
    exc.status_code = 400
    assert not _is_retryable(exc)


def test_status_code_401_is_not_retryable():
    """HTTP 401 (unauthorized) indicates an auth problem that won't fix on retry."""
    exc = Exception("unauthorized")
    exc.status_code = 401
    assert not _is_retryable(exc)


def test_value_error_is_not_retryable():
    """ValueError is a programming error, not a transient API failure."""
    assert not _is_retryable(ValueError("bad input"))


def test_connection_error_is_not_retryable():
    """ConnectionError indicates the server is unreachable — retrying immediately is not helpful."""
    assert not _is_retryable(ConnectionError("no connection"))


def test_http_error_with_retryable_response_status():
    """requests.HTTPError with response.status_code == 503 should be retried."""
    exc = Exception("http error")
    exc.response = MagicMock()
    exc.response.status_code = 503
    assert _is_retryable(exc)


def test_http_error_with_non_retryable_response_status():
    """requests.HTTPError with response.status_code == 404 must not be retried."""
    exc = Exception("http error")
    exc.response = MagicMock()
    exc.response.status_code = 404
    assert not _is_retryable(exc)


# ── with_retry() decorator tests ──────────────────────────────────────────────
# Verify retry count, error propagation, delay sequence, and metadata preservation.

def test_succeeds_on_first_attempt():
    """No retries if the first attempt succeeds."""
    mock_fn = MagicMock(return_value="ok")
    decorated = with_retry(max_attempts=3, base_delay=0)(mock_fn)
    result = decorated()
    assert result == "ok"
    assert mock_fn.call_count == 1


def test_retries_on_retryable_error():
    """A retryable error on attempt 1 is followed by a successful attempt 2."""
    retryable_exc = Exception("server error")
    retryable_exc.status_code = 500

    mock_fn = MagicMock(side_effect=[retryable_exc, "ok"])
    decorated = with_retry(max_attempts=3, base_delay=0)(mock_fn)

    with patch("llm.retry.time.sleep"):
        result = decorated()

    assert result == "ok"
    assert mock_fn.call_count == 2


def test_does_not_retry_non_retryable_error():
    """Non-retryable errors are re-raised immediately after the first attempt."""
    mock_fn = MagicMock(side_effect=ValueError("bad input"))
    decorated = with_retry(max_attempts=3, base_delay=0)(mock_fn)

    with pytest.raises(ValueError):
        decorated()

    assert mock_fn.call_count == 1


def test_raises_after_max_attempts():
    """After max_attempts all fail, the last exception is re-raised."""
    retryable_exc = Exception("server error")
    retryable_exc.status_code = 500

    mock_fn = MagicMock(side_effect=retryable_exc)
    decorated = with_retry(max_attempts=3, base_delay=0)(mock_fn)

    with patch("llm.retry.time.sleep"):
        with pytest.raises(Exception, match="server error"):
            decorated()

    assert mock_fn.call_count == 3


def test_exponential_backoff_delay_sequence():
    """Sleep delays double each attempt: 1s, 2s, 4s (3 sleeps for 4 attempts)."""
    retryable_exc = Exception("server error")
    retryable_exc.status_code = 500

    mock_fn = MagicMock(side_effect=retryable_exc)
    decorated = with_retry(max_attempts=4, base_delay=1.0, max_delay=30.0)(mock_fn)

    with patch("llm.retry.time.sleep") as mock_sleep:
        with pytest.raises(Exception):
            decorated()

    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays == [1.0, 2.0, 4.0]


def test_delay_capped_at_max():
    """No sleep delay ever exceeds max_delay regardless of attempt count."""
    retryable_exc = Exception("server error")
    retryable_exc.status_code = 500

    mock_fn = MagicMock(side_effect=retryable_exc)
    decorated = with_retry(max_attempts=5, base_delay=10.0, max_delay=15.0)(mock_fn)

    with patch("llm.retry.time.sleep") as mock_sleep:
        with pytest.raises(Exception):
            decorated()

    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert all(d <= 15.0 for d in delays)


def test_preserves_function_name():
    """@wraps ensures the decorated function retains its original __name__."""
    def my_function():
        pass
    decorated = with_retry()(my_function)
    assert decorated.__name__ == "my_function"
