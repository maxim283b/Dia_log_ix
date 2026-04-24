PYTHON ?= python3

.PHONY: install test migrate run run-webhook docker-up docker-down docker-build

install:
	$(PYTHON) -m pip install -e .

test:
	pytest -q

migrate:
	alembic upgrade head

run:
	BOT_MODE=polling $(PYTHON) -m app.main

run-webhook:
	BOT_MODE=webhook $(PYTHON) -m app.main

docker-up:
	docker compose up --build

docker-down:
	docker compose down

docker-build:
	docker compose build

