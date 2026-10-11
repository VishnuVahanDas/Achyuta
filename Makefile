VENV ?= .venv
PY := $(VENV)/bin/python
ADDR ?= 127.0.0.1:8000
TAILWIND_VERSION := 4.3.3
TAILWIND := bin/tailwindcss
CSS_IN := static_src/app.css
CSS_OUT := static/css/app.css

.PHONY: setup run test lint format migrate migrations superuser css css-watch

setup: $(TAILWIND)  ## First-time install: virtualenv, dependencies, git hooks, Tailwind CLI
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PY) -m pip install -r requirements-dev.txt
	$(VENV)/bin/pre-commit install

$(TAILWIND):
	scripts/install_tailwind.sh $(TAILWIND_VERSION)

css: $(TAILWIND)  ## Build the stylesheet once
	$(TAILWIND) -i $(CSS_IN) -o $(CSS_OUT) --minify

css-watch: $(TAILWIND)  ## Rebuild the stylesheet on every template change
	$(TAILWIND) -i $(CSS_IN) -o $(CSS_OUT) --watch

run: css  ## Dev server (ADDR=0.0.0.0:8000 to reach it from a phone)
	$(PY) manage.py runserver $(ADDR)

test:
	$(VENV)/bin/pytest

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format:
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

migrate:
	$(PY) manage.py migrate

migrations:
	$(PY) manage.py makemigrations

superuser:
	$(PY) manage.py createsuperuser
