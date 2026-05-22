import pytest
import time
from unittest.mock import MagicMock, patch
from llm.retry import with_retry, _is_retryable


# ── _is_retryable() tests ─────────────────────────────────────────────────────

def test_rate_limit_error_is_retryable():
    exc = MagicMock()
    exc.__class__.__name__ = "RateLimitError"
    type(exc).__name__ = "RateLimitError"
    assert _is_retryable(exc)


def test_internal_server_error_is_retryable():
    exc = MagicMock()
    type(exc).__name__ = "InternalServerError"
    assert _is_retryable(exc)


def test_status_code_429_is_retryable():
    exc = Exception("rate limit")
    exc.status_code = 429
    assert _is_retryable(exc)


def test_status_code_500_is_retryable():
    exc = Exception("server error")
    exc.status_code = 500
    assert _is_retryable(exc)


def test_status_code_529_is_retryable():
    exc = Exception("overloaded")
    exc.status_code = 529
    assert _is_retryable(exc)


def test_status_code_400_is_not_retryable():
    exc = Exception("bad request")
    exc.status_code = 400
    assert not _is_retryable(exc)


def test_status_code_401_is_not_retryable():
    exc = Exception("unauthorized")
    exc.status_code = 401
    assert not _is_retryable(exc)


def test_value_error_is_not_retryable():
    assert not _is_retryable(ValueError("bad input"))


def test_connection_error_is_not_retryable():
    assert not _is_retryable(ConnectionError("no connection"))


def test_http_error_with_retryable_response_status():
    exc = Exception("http error")
    exc.response = MagicMock()
    exc.response.status_code = 503
    assert _is_retryable(exc)


def test_http_error_with_non_retryable_response_status():
    exc = Exception("http error")
    exc.response = MagicMock()
    exc.response.status_code = 404
    assert not _is_retryable(exc)


# ── with_retry() decorator tests ──────────────────────────────────────────────

def test_succeeds_on_first_attempt():
    mock_fn = MagicMock(return_value="ok")
    decorated = with_retry(max_attempts=3, base_delay=0)(mock_fn)
    result = decorated()
    assert result == "ok"
    assert mock_fn.call_count == 1


def test_retries_on_retryable_error():
    retryable_exc = Exception("server error")
    retryable_exc.status_code = 500

    mock_fn = MagicMock(side_effect=[retryable_exc, "ok"])
    decorated = with_retry(max_attempts=3, base_delay=0)(mock_fn)

    with patch("llm.retry.time.sleep"):
        result = decorated()

    assert result == "ok"
    assert mock_fn.call_count == 2


def test_does_not_retry_non_retryable_error():
    mock_fn = MagicMock(side_effect=ValueError("bad input"))
    decorated = with_retry(max_attempts=3, base_delay=0)(mock_fn)

    with pytest.raises(ValueError):
        decorated()

    assert mock_fn.call_count == 1


def test_raises_after_max_attempts():
    retryable_exc = Exception("server error")
    retryable_exc.status_code = 500

    mock_fn = MagicMock(side_effect=retryable_exc)
    decorated = with_retry(max_attempts=3, base_delay=0)(mock_fn)

    with patch("llm.retry.time.sleep"):
        with pytest.raises(Exception, match="server error"):
            decorated()

    assert mock_fn.call_count == 3


def test_exponential_backoff_delay_sequence():
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
    def my_function():
        pass
    decorated = with_retry()(my_function)
    assert decorated.__name__ == "my_function"