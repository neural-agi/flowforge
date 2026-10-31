import pytest

from flowforge.models import StepSpecification, WorkflowSpecification


def step(name: str, order: int, max_attempts: int = 3) -> StepSpecification:
    return StepSpecification(name, order, max_attempts=max_attempts)


def test_valid_workflow_specification() -> None:
    specification = WorkflowSpecification("order", "1", {}, (step("a", 1), step("b", 2)))
    assert specification.steps[1].order == 2


def test_workflow_requires_steps() -> None:
    with pytest.raises(ValueError, match="at least one"):
        WorkflowSpecification("order", "1", {}, ())


def test_workflow_requires_consecutive_order() -> None:
    with pytest.raises(ValueError, match="consecutive"):
        WorkflowSpecification("order", "1", {}, (step("a", 2),))


def test_workflow_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="unique"):
        WorkflowSpecification("order", "1", {}, (step("a", 1), step("a", 2)))


def test_step_requires_positive_attempts() -> None:
    with pytest.raises(ValueError, match="positive"):
        step("a", 1, 0)
