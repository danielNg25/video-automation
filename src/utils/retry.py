"""Retry decorators with exponential backoff and jitter."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from tenacity import (
    RetryCallState,
    retry as tenacity_retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Default retryable exceptions (network errors, rate limits, transient server errors)
RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)

try:
    import httpx

    RETRYABLE_EXCEPTIONS = (*RETRYABLE_EXCEPTIONS, httpx.HTTPStatusError, httpx.ConnectError)
except ImportError:
    pass


def _log_retry(retry_state: RetryCallState) -> None:
    """Log each retry attempt with delay info."""
    attempt = retry_state.attempt_number
    outcome = retry_state.outcome
    if outcome and outcome.failed:
        exc = outcome.exception()
        logger.warning(
            f"Retry attempt {attempt}: {type(exc).__name__}: {exc} "
            f"(next retry in {retry_state.next_action} seconds)"
        )


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retry_on: tuple[type[Exception], ...] | None = None,
) -> Callable:
    """Synchronous retry decorator with exponential backoff and jitter.

    Args:
        max_attempts: Maximum number of attempts before giving up.
        base_delay: Initial delay between retries in seconds.
        max_delay: Maximum delay between retries in seconds.
        retry_on: Tuple of exception types to retry on. Defaults to common
            network/transient errors.

    Returns:
        Decorator that wraps the function with retry logic.

    Example:
        @retry(max_attempts=3, base_delay=1)
        def flaky_call():
            ...
    """
    exceptions = retry_on or RETRYABLE_EXCEPTIONS

    return tenacity_retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=base_delay, max=max_delay),
        retry=retry_if_exception_type(exceptions),
        before_sleep=_log_retry,
        reraise=True,
    )


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retry_on: tuple[type[Exception], ...] | None = None,
) -> Callable:
    """Async retry decorator with exponential backoff and jitter.

    Same parameters as `retry` but works with async functions.

    Example:
        @async_retry(max_attempts=3, base_delay=1)
        async def flaky_api_call():
            ...
    """
    exceptions = retry_on or RETRYABLE_EXCEPTIONS

    return tenacity_retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=base_delay, max=max_delay),
        retry=retry_if_exception_type(exceptions),
        before_sleep=_log_retry,
        reraise=True,
    )
