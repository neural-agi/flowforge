#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required" >&2
  exit 1
fi
if ! command -v psql >/dev/null 2>&1; then
  echo "error: psql is required (or use the documented Docker database shell)" >&2
  exit 1
fi
if ! command -v flowforge >/dev/null 2>&1; then
  echo "error: flowforge is not installed; install the project in a Python 3.12 environment" >&2
  exit 1
fi

make up
make migrate

input='{"order_id":"demo-crash-1001","sku":"demo-widget","quantity":1,"amount_cents":1999,"currency":"USD","customer_email":"customer@example.com"}'
key="demo-crash-$(date +%s)-$$"
workflow_line=$(flowforge start --workflow order_fulfillment --idempotency-key "$key" --input "$input")
echo "$workflow_line"
workflow_id=${workflow_line#workflow_id=}
workflow_id=${workflow_id%% *}

set +e
FLOWFORGE_CRASH_AFTER_EFFECT=charge_payment flowforge worker --once
exit_code=$?
set -e
if [[ "$exit_code" != 137 ]]; then
  echo "error: expected crash exit code 137, got $exit_code" >&2
  exit "$exit_code"
fi

echo "--- state after injected crash ---"
flowforge status "$workflow_id"
flowforge history "$workflow_id"
echo "Waiting 31 seconds for the documented worker lease to expire..."
sleep 31
flowforge worker --until-idle
echo "--- recovered final state ---"
flowforge status "$workflow_id"
flowforge history "$workflow_id"
psql "${FLOWFORGE_DATABASE_URL:-postgresql://flowforge:flowforge_dev_password@localhost:5432/flowforge}" \
  -c "SELECT idempotency_key, count(*) FROM payment_effects WHERE workflow_id = '$workflow_id' GROUP BY idempotency_key;"
