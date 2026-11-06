.PHONY: install test lint demo up down
install:
	python -m pip install -e ".[dev]"
test:
	pytest -q
lint:
	ruff check .
up:
	docker compose up -d --wait
down:
	docker compose down
demo:
	dataforge generate --orders 3000 --seed 42
	dataforge ingest
	dataforge db-init
	dataforge db-load
	dataforge db-build
	dataforge db-check
