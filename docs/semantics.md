# FlowForge Durable-Execution Semantics

## Goal

FlowForge demonstrates durable execution for a small sequential workflow:

```text
reserve_inventory → charge_payment → send_receipt
```

The problem is the failure window in which a worker completes an external side effect, then crashes before recording that completion in FlowForge. On restart, FlowForge must not lose the workflow's progress or create a duplicate side effect when it retries the interrupted step.

## Guarantees

FlowForge provides:

- Durable workflow state, step state, attempts, timestamps, inputs, outputs, errors, and history in PostgreSQL.
- At-least-once step execution. A step can run again after an interruption or expired lease.
- Persisted retry state and exponential backoff: attempts are limited to three total attempts, with delays of 1, 2, and 4 seconds.
- Recovery after worker failure through expiring worker leases.
- Deterministic side-effect keys in the form `{workflow_id}:{step_name}`. An external system that honors this key can make repeated requests return the original result instead of creating another effect.

## Non-guarantees

FlowForge does not provide:

- Generic exactly-once execution or delivery.
- A distributed transaction spanning PostgreSQL and an external system.
- Automatic compensation or saga behavior in the MVP.

The idempotency boundary is explicit: FlowForge supplies a stable key, but an external system must enforce the key's uniqueness and replay behavior.

## State machines

### Workflow

```text
              ┌───────────┐
              │  running  │
              └─────┬─────┘
                    │ all steps succeeded
                    v
              ┌───────────┐
              │ completed │
              └───────────┘
                    ^
                    │ terminal step failure
              ┌─────┴─────┐
              │  failed   │
              └───────────┘
```

### Step

```text
pending ──claim──> running ──success──> succeeded
                      │
                      ├──retryable error──> retry_wait ──eligible──> running
                      │
                      └──terminal error or exhausted retries──> failed
```

`retry_wait` is durable state. The worker does not rely on sleeping in memory to remember a retry.

## Completion definition

A step is considered complete only after FlowForge has durably committed its successful output and the corresponding success event in PostgreSQL. For a non-final step, the same transaction also makes the next sequential step runnable. An activity returning successfully is not, by itself, a recorded FlowForge completion.

## Normal success path

1. The workflow and its ordered steps are inserted durably.
2. A worker atomically claims the first eligible step and records an attempt and claim event.
3. The worker invokes the activity with its deterministic idempotency key where applicable.
4. The worker commits the step output, success state, success event, and successor scheduling in one transaction.
5. The worker repeats the process for the next step.
6. After `send_receipt` succeeds, the workflow is marked completed in the same completion transaction.

Completed steps are not eligible for claiming, so a normal restart does not re-run them.

## Retry behavior

Only explicitly retryable/transient activity errors enter `retry_wait`. The retry schedule is persisted as the next eligible timestamp. The maximum is three total attempts, with exponential delays of 1 second, 2 seconds, and 4 seconds as applicable to the configured retry policy.

If a retryable error occurs before the third attempt, the worker records the error, attempt result, retry event, and next eligible time. Once eligible, another worker may claim the step. If the final allowed attempt fails, the step becomes `failed` and the workflow becomes terminally failed. Non-retryable errors fail immediately.

## Leases, expiry, and recovery

Claiming uses a database transaction and row locks compatible with `FOR UPDATE SKIP LOCKED`. The claim records the worker identity and a lease expiration 30 seconds in the future. The worker may update the claimed step only while holding its current lease.

Each polling cycle first makes expired running work eligible for recovery and records a recovery event. The recovery operation does not assume the original process is still alive; the database lease is the authority. The recovered step can then be claimed and executed again, preserving at-least-once behavior.

## The side-effect failure window

There is necessarily a boundary between an activity's external effect and FlowForge's completion transaction:

1. FlowForge claims `charge_payment` and records its attempt.
2. The activity calls the payment provider using `{workflow_id}:charge_payment`.
3. The provider accepts the payment and durably stores the key and payment result.
4. Before FlowForge commits the step's successful output, the worker crashes.
5. The lease expires; recovery makes the step eligible again.
6. A worker retries `charge_payment` with the same deterministic key.
7. The provider's unique constraint finds the existing key and returns the original payment result.
8. FlowForge records the returned result and marks the step succeeded.

No second payment is created because the mock provider treats the idempotency key as a unique effect identity. Without that downstream guarantee, a retry could duplicate the external effect.

This is why interrupted steps may be re-executed while completed steps are not: completion is a durable FlowForge fact, but a crash before that fact is committed leaves the step indistinguishable from unfinished work. Re-execution plus idempotency closes the practical failure window without claiming exactly-once execution.

## Failure injection

When `FLOWFORGE_CRASH_AFTER_EFFECT=charge_payment`, the worker terminates immediately after the payment provider accepts the side effect and before FlowForge records task completion. The resulting expired lease and provider idempotency record make the recovery behavior observable and repeatable.
