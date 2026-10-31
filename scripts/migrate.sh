#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-flowforge}" -d "${POSTGRES_DB:-flowforge}")
"${compose[@]}" -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"

for migration in migrations/*.sql; do
  filename=$(basename "$migration")
  applied=$("${compose[@]}" -Atqc "SELECT 1 FROM schema_migrations WHERE filename = '$filename'")
  if [[ "$applied" == "1" ]]; then
    echo "already applied: $filename"
    continue
  fi
  echo "applying: $filename"
  {
    echo "BEGIN;"
    cat "$migration"
    printf "INSERT INTO schema_migrations (filename) VALUES ('%s');\n" "$filename"
    echo "COMMIT;"
  } | "${compose[@]}"
done
