from datetime import timedelta

from flowforge.models import StepSpecification
from flowforge.repository import IdempotencyConflictError, LeaseLostError, WorkflowRepository


def test_repository_exposes_persistence_contracts() -> None:
    repository = WorkflowRepository()
    assert callable(repository.claim_next_runnable_step)
    assert callable(repository.mark_step_succeeded)
    assert callable(repository.schedule_step_retry)
    assert callable(repository.mark_step_failed)
    assert timedelta(seconds=30).total_seconds() == 30


def test_domain_errors_are_clear() -> None:
    assert issubclass(IdempotencyConflictError, RuntimeError)
    assert issubclass(LeaseLostError, RuntimeError)
    assert StepSpecification("payment", 1).max_attempts == 3
