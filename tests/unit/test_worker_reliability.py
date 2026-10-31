from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from flowforge.retry import RetryableActivityError
from flowforge.worker import Worker, crash_after_effect_step


class FakeRepository:
    def __init__(self) -> None:
        self.claimed = SimpleNamespace(
            step=SimpleNamespace(
                id=uuid4(),
                workflow_id=uuid4(),
                step_name="reserve_inventory",
                max_attempts=3,
            ),
            attempt_number=1,
        )
        self.retries: list[tuple] = []
        self.failed: list[tuple] = []

    def recover_expired_leases(self) -> int:
        return 0

    def claim_next_runnable_step(self, worker_id: str, lease_duration: timedelta):
        result, self.claimed = self.claimed, None
        return result

    def get_workflow(self, workflow_id):
        return SimpleNamespace(id=workflow_id, input={}), []

    def schedule_step_retry(self, *args):
        self.retries.append(args)

    def mark_step_failed(self, *args):
        self.failed.append(args)


def test_worker_schedules_retryable_failure(monkeypatch) -> None:
    repository = FakeRepository()
    worker = Worker(repository, "test-worker")

    def fail_retryably(*_args):
        raise RetryableActivityError("temporary")

    monkeypatch.setattr(worker, "_invoke", fail_retryably)

    assert worker.run_once() is True
    assert len(repository.retries) == 1
    assert repository.failed == []
    assert repository.retries[0][2]["type"] == "RetryableActivityError"
    assert repository.retries[0][3] > datetime.now(timezone.utc)


def test_worker_fails_unknown_exception(monkeypatch) -> None:
    repository = FakeRepository()
    worker = Worker(repository, "test-worker")

    def fail_permanently(*_args):
        raise RuntimeError("bad")

    monkeypatch.setattr(worker, "_invoke", fail_permanently)

    assert worker.run_once() is True
    assert len(repository.failed) == 1
    assert repository.failed[0][2]["type"] == "RuntimeError"


def test_crash_configuration_is_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("FLOWFORGE_CRASH_AFTER_EFFECT", raising=False)
    assert crash_after_effect_step("charge_payment") is False
    monkeypatch.setenv("FLOWFORGE_CRASH_AFTER_EFFECT", "charge_payment")
    assert crash_after_effect_step("charge_payment") is True
    assert crash_after_effect_step("send_receipt") is False
