CREATE TABLE workflows (
    id uuid PRIMARY KEY,
    definition_name text NOT NULL,
    definition_version text NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    status text NOT NULL,
    input jsonb NOT NULL,
    output jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT workflows_status_check
        CHECK (status IN ('running', 'succeeded', 'failed'))
);

CREATE TABLE workflow_steps (
    id uuid PRIMARY KEY,
    workflow_id uuid NOT NULL REFERENCES workflows(id),
    step_name text NOT NULL,
    step_order integer NOT NULL,
    status text NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_expires_at timestamptz,
    input jsonb NOT NULL,
    output jsonb,
    last_error jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    CONSTRAINT workflow_steps_status_check
        CHECK (status IN ('pending', 'running', 'retry_wait', 'succeeded', 'failed')),
    CONSTRAINT workflow_steps_attempt_count_check CHECK (attempt_count >= 0),
    CONSTRAINT workflow_steps_max_attempts_check CHECK (max_attempts > 0),
    CONSTRAINT workflow_steps_order_unique UNIQUE (workflow_id, step_order)
);

CREATE INDEX workflow_steps_runnable_idx
    ON workflow_steps (available_at, step_order)
    WHERE status IN ('pending', 'retry_wait');

CREATE INDEX workflow_steps_expired_lease_idx
    ON workflow_steps (lease_expires_at)
    WHERE status = 'running';

CREATE TABLE step_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow_step_id uuid NOT NULL REFERENCES workflow_steps(id),
    attempt_number integer NOT NULL,
    worker_id text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    error jsonb,
    CONSTRAINT step_attempts_attempt_unique UNIQUE (workflow_step_id, attempt_number)
);

CREATE TABLE workflow_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow_id uuid NOT NULL REFERENCES workflows(id),
    workflow_step_id uuid REFERENCES workflow_steps(id),
    event_type text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX workflow_events_history_idx
    ON workflow_events (workflow_id, created_at, id);

CREATE TABLE payment_effects (
    id uuid PRIMARY KEY,
    idempotency_key text NOT NULL UNIQUE,
    workflow_id uuid NOT NULL REFERENCES workflows(id),
    amount_cents integer NOT NULL,
    currency text NOT NULL,
    status text NOT NULL,
    provider_reference text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
