"""Retry classification and the fixed FlowForge retry policy."""

from datetime import timedelta


class RetryableActivityError(Exception):
    """An activity failure that may be retried."""


class NonRetryableActivityError(Exception):
    """An activity failure that must fail the workflow immediately."""


def retry_delay(attempt_number: int) -> timedelta:
    """Return the delay after a failed attempt: 1s, 2s, then 4s."""
    if attempt_number < 1:
        raise ValueError("attempt_number must be positive")
    return timedelta(seconds=2 ** (attempt_number - 1))


def error_details(error: Exception) -> dict[str, str]:
    return {"type": type(error).__name__, "message": str(error)}
