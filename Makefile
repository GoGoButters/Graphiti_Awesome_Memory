.PHONY: up down build test envs

envs:
	bash scripts/generate_envs.sh

up: envs
	docker-compose up -d

down:
	docker-compose down

build:
	docker-compose build

test:
	docker-compose run --rm adapter pytest
