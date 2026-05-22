.PHONY: up down test fmt
up:
	docker compose up --build

down:
	docker compose down -v

test:
	PYTHONPATH=libs/common pytest -q

fmt:
	ruff check . --fix
