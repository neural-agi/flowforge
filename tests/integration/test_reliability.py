"""PostgreSQL reliability checks; skipped unless explicitly configured."""

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from flowforge.config import Settings
from flowforge.models import StepSpecification
from flowforge.repository import WorkflowRepository
from flowforge.worker import Worker
from flowforge.workflows.order_fulfillment import get_workflow_definition

DATABASE_URL = os.getenv("FLOWFORGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.integration


@pytest.fixture
def repository():
    if not DATABASE_URL:
        pytest.skip("FLOWFORGE_TEST_DATABASE_URL is not set")
    repo = WorkflowRepository(Settings(DATABASE_URL))
    yield repo
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """DELETE FROM payment_effects
               WHERE workflow_id IN (
                   SELECT id FROM workflows WHERE idempotency_key LIKE 'integration-%'
               )"""
        )
        connection.execute(
            """DELETE FROM workflow_events
               WHERE workflow_id IN (
                   SELECT id FROM workflows WHERE idempotency_key LIKE 'integration-%'
               )"""
        )
        connection.execute(
            """DELETE FROM step_attempts
               WHERE workflow_step_id IN (
                   SELECT id FROM workflow_steps WHERE workflow_id IN (
                       SELECT id FROM workflows WHERE idempotency_key LIKE 'integration-%'
                   )
               )"""
        )
        connection.execute(
            """DELETE FROM workflow_steps
               WHERE workflow_id IN (
                   SELECT id FROM workflows WHERE idempotency_key LIKE 'integration-%'
               )"""
        )
        connection.execute("DELETE FROM workflows WHERE idempotency_key LIKE 'integration-%'")
        connection.commit()


def start(repo: WorkflowRepository, key: str, max_attempts: int = 3):
    return repo.create_workflow(
        "order_fulfillment",
        "1",
        f"integration-{key}",
        {"order_id": key},
        (StepSpecification("only_step", 1, max_attempts=max_attempts),),
    )


def test_expired_lease_is_recovered(repository):
    workflow = start(repository, str(uuid4()))
    claimed = repository.claim_next_runnable_step("integration-worker", timedelta(seconds=1))
    assert claimed is not None
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """UPDATE workflow_steps SET lease_expires_at = NOW() - INTERVAL '1 second'
               WHERE id = %s""",
            (claimed.step.id,),
        )
        connection.commit()
    assert repository.recover_expired_leases() == 1
    state = repository.get_workflow(workflow.id)
    assert state[1][0].status.value == "retry_wait"


def test_payment_effect_is_idempotent(repository):
    workflow = start(repository, str(uuid4()))
    key = f"{workflow.id}:charge_payment"
    first = repository.create_or_get_payment_effect(key, workflow.id, 1999, "USD")
    second = repository.create_or_get_payment_effect(key, workflow.id, 1999, "USD")
    assert first == second


def test_retry_wait_then_success(repository):
    workflow = start(repository, str(uuid4()))
    claimed = repository.claim_next_runnable_step("integration-worker", timedelta(seconds=30))
    assert claimed is not None
    repository.schedule_step_retry(
        claimed.step.id,
        "integration-worker",
        {"type": "RetryableActivityError", "message": "temporary"},
        datetime.now(timezone.utc),
    )
    retried = repository.claim_next_runnable_step("integration-worker-2", timedelta(seconds=30))
    assert retried is not None
    repository.mark_step_succeeded(retried.step.id, "integration-worker-2", {"ok": True})
    assert repository.get_workflow(workflow.id)[0].status.value == "succeeded"


def test_exhausted_expired_lease_fails_workflow(repository):
    workflow = start(repository, str(uuid4()), max_attempts=1)
    claimed = repository.claim_next_runnable_step("integration-worker", timedelta(seconds=1))
    assert claimed is not None
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """UPDATE workflow_steps SET lease_expires_at = NOW() - INTERVAL '1 second'
               WHERE id = %s""",
            (claimed.step.id,),
        )
        connection.commit()
    assert repository.recover_expired_leases() == 1
    assert repository.get_workflow(workflow.id)[0].status.value == "failed"


def test_crash_after_payment_recovers_to_success(repository):
    key = str(uuid4())
    payload = {
        "order_id": f"order-{key}",
        "sku": "demo-widget",
        "quantity": 1,
        "amount_cents": 1999,
        "currency": "USD",
        "customer_email": "customer@example.com",
    }
    definition = get_workflow_definition("order_fulfillment")
    workflow = repository.create_workflow(
        definition.name,
        definition.version,
        f"integration-{key}",
        payload,
        definition.specifications(payload),
    )
    Worker(repository, "integration-first-worker").run_once()
    environment = os.environ.copy()
    environment["FLOWFORGE_TEST_DATABASE_URL"] = DATABASE_URL
    environment["FLOWFORGE_CRASH_AFTER_EFFECT"] = "charge_payment"
    environment["PYTHONPATH"] = "src"
    result = subprocess.run(
        [sys.executable, "-m", "flowforge.cli", "worker", "--once"],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 137, result.stderr
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """UPDATE workflow_steps SET lease_expires_at = NOW() - INTERVAL '1 second'
               WHERE workflow_id = %s AND step_name = 'charge_payment'""",
            (workflow.id,),
        )
        connection.commit()
    Worker(repository, "integration-recovery-worker").run_until_idle()
    state = repository.get_workflow(workflow.id)
    assert state[0].status.value == "succeeded"
    assert [step.status.value for step in state[1]] == ["succeeded"] * 3
    with psycopg.connect(DATABASE_URL) as connection:
        count = connection.execute(
            "SELECT count(*) FROM payment_effects WHERE workflow_id = %s AND idempotency_key = %s",
            (workflow.id, f"{workflow.id}:charge_payment"),
        ).fetchone()[0]
    assert count == 1
    event_types = [event.event_type for event in repository.get_history(workflow.id)]
    assert "step_claimed" in event_types
    assert "step_lease_expired" in event_types
    assert "step_retry_scheduled" in event_types
    assert "step_succeeded" in event_types
    assert "workflow_succeeded" in event_types
