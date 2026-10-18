.PHONY: up down seed reset dev test logs wheels lock

up:          ## start FalkorDB + app in Docker
	docker compose up -d --build

down:
	docker compose down

seed:        ## wipe and load the Kettle Labs graph
	docker compose exec app python -m backend.seed

reset: seed

dev:         ## run the app locally against Dockerised FalkorDB
	docker compose up -d falkordb
	python -m uvicorn backend.main:app --reload --port 8000

test:        ## run the test suite (needs FalkorDB on localhost:6379)
	python -m pytest -q

logs:
	docker compose logs -f app

lock:        ## re-pin Linux deps from the running app container
	docker compose exec -T app pip freeze > requirements.lock

wheels:      ## pre-download the pinned Linux wheels on the host (for slow Docker networks)
	python -m pip download --no-deps -r requirements.lock -d wheels --only-binary=:all: --python-version 3.12 --implementation cp --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_5_x86_64 --platform manylinux1_x86_64 --platform any
