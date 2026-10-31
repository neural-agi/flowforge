.PHONY: up down logs db-shell migrate lint

up:
	docker compose up -d postgres

down:
	docker compose down

logs:
	docker compose logs -f postgres

db-shell:
	docker compose exec postgres psql -U "$${POSTGRES_USER:-flowforge}" -d "$${POSTGRES_DB:-flowforge}"

migrate:
	scripts/migrate.sh

lint:
	ruff check src
