# FlowForge Architecture

FlowForge is a Python 3.12, PostgreSQL-backed, CLI-first execution engine for one code-defined sequential workflow. The MVP uses `argparse`, direct SQL through `psycopg`, and numbered SQL migrations planned for a later implementation phase.

## High-level design

```text
                 ┌──────────────┐
                 │     CLI      │
                 │ argparse     │
                 └──────┬───────┘
                        │ start/status/history
                        v
┌──────────────┐  SQL  ┌────────────────┐  SQL  ┌────────────────────┐
│    Worker    │◄─────►│   PostgreSQL   │◄─────►│ Mock payment        │
│ poll/execute │       │ durable state │       │ provider/effects     │
└──────┬───────┘       └────────────────┘       └────────────────────┘
       │
       v
┌──────────────┐       ┌──────────────────┐
│ Workflow     │──────►│ Activity handlers │
│ registry     │       │ inventory/payment │
│ sequential   │       │ /receipt          │
└──────────────┘       └──────────────────┘
```

The diagram shows logical boundaries, not network requirements. The mock payment provider is PostgreSQL-backed so its uniqueness guarantee participates in the same durable local system, while still modeling a downstream side-effecting service.

## Components and boundaries

- **CLI:** Accepts workflow start, worker, status, and history operations. It validates user input and delegates persistence or execution; it does not hold correctness-critical state.
- **PostgreSQL:** The source of truth for workflows, steps, attempts, events, leases, retry timing, and payment effects.
- **Worker:** Polls every second, recovers expired leases, claims eligible work, invokes activities, and records outcomes. A worker process may crash at any point.
- **Workflow registry:** Maps the fixed workflow name and step names to their ordered definition and activity handler. It is code-defined, not user-authored.
- **Activity handlers:** Perform the small domain operations for inventory, payment, and receipt. They return explicit success or classified retryable/terminal errors.
- **Mock payment provider:** Accepts a payment idempotency key, stores the first payment result, and returns that result for duplicates. A unique database constraint on the key prevents two payments for one key.

## Planned database entities

The exact SQL schema will be designed in the migration phase. The intended entities and essential fields are:

| Entity | Essential fields |
|---|---|
| `workflows` | workflow ID, workflow type, input, status, created/updated timestamps, completion/error data |
| `workflow_steps` | workflow ID, step name/order, state, input/output, attempt count, next eligible time, lease owner/expiry, error data, timestamps |
| `step_attempts` | attempt ID, workflow/step references, attempt number, worker identity, claimed/started/finished timestamps, outcome, error |
| `workflow_events` | event ID, workflow/step references, event type, attempt/worker metadata, payload, timestamp |
| `payment_effects` | idempotency key with a unique constraint, payment ID/result, request data, created timestamp |

## Planned worker loop

1. Recover running steps whose 30-second lease has expired and append recovery history.
2. Atomically claim one runnable step using row locks and `FOR UPDATE SKIP LOCKED` or an equivalent safe pattern.
3. Record the attempt and claim event as part of the claim transaction.
4. Resolve the step through the workflow registry and invoke its activity.
5. Persist success, retry, or terminal failure according to the classified result.
6. On success, persist the output and schedule the next sequential step in one transaction. After the final step, mark the workflow completed.
7. Poll again after the one-second interval.

The worker may be stopped or killed between any two operations. Correctness comes from PostgreSQL state, not from an in-memory queue or local progress marker.

## Transaction boundaries and concurrency

Claiming is one transaction: it locks an eligible step, assigns the worker and lease, increments/records the attempt, and writes the claim history. Competing workers skip locked rows and cannot claim the same currently leased step.

Completion is one transaction: it verifies the lease, stores the activity output, marks the step succeeded, writes the success event, and either makes the successor runnable or completes the workflow. Retry and failure transactions similarly persist the outcome, error, event, and next state together.

The external activity call is intentionally outside the completion transaction. PostgreSQL cannot atomically commit with an arbitrary external system, so an activity can succeed while FlowForge is still unrecorded. Stable idempotency keys are the protection for repeatable side effects.

## Compatibility with multiple workers

Although the MVP demo can run one worker, each claim is lease-based and database-coordinated. Worker identity, lease expiration, row locking, and `SKIP LOCKED` avoid a shared in-memory scheduler and allow multiple workers to poll the same database later. The design still requires activities to honor their idempotency contract wherever side effects can be repeated.

## Deferred work

The following are intentionally out of scope for the MVP:

- Parallel branches and joins
- Worker pools
- HTTP APIs
- Dashboards
- Benchmarks

