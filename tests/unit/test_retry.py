from datetime import timedelta

import pytest

from flowforge.retry import (
    NonRetryableActivityError,
    RetryableActivityError,
    retry_delay,
)


def test_retry_delays_are_exponential() -> None:
    assert [retry_delay(n) for n in (1, 2, 3)] == [
        timedelta(seconds=1),
        timedelta(seconds=2),
        timedelta(seconds=4),
    ]


def test_retry_delay_rejects_invalid_attempt() -> None:
    with pytest.raises(ValueError):
        retry_delay(0)


def test_error_classes_are_distinct() -> None:
    assert not issubclass(RetryableActivityError, NonRetryableActivityError)
