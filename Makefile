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
	docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$${POSTGRES_USER:-flowforge}" -d "$${POSTGRES_DB:-flowforge}" < migrations/001_initial_schema.sql

lint:
	ruff check src
