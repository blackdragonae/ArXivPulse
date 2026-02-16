.PHONY: help smoke profile lint fmt-check test type-check validate

PYTHON ?= .venv/bin/python
NODE ?= node
APP_JS := frontend/app.js
PY_QUALITY_TARGETS := arxivc/client.py arxivc/fetch_service.py arxivc/routers/workflow_actions.py tests

help:
	@echo "Available targets:"
	@echo "  make smoke      - run API smoke checks"
	@echo "  make profile    - run hot-path profiling"
	@echo "  make lint       - run ruff + frontend JS syntax checks"
	@echo "  make fmt-check  - run black --check"
	@echo "  make test       - run pytest suite"
	@echo "  make type-check - run mypy (optional)"
	@echo "  make validate   - run compile checks + lint + fmt-check + test"

smoke:
	$(PYTHON) scripts/smoke_api.py

profile:
	$(PYTHON) scripts/profile_hotpaths.py

lint:
	$(PYTHON) -m ruff check $(PY_QUALITY_TARGETS)
	@if command -v $(NODE) >/dev/null 2>&1; then \
		for f in frontend/*.js; do \
			$(NODE) --check $$f; \
		done; \
	else \
		echo "node not found; skipping JS syntax check"; \
	fi

fmt-check:
	$(PYTHON) -m black --check $(PY_QUALITY_TARGETS)

test:
	$(PYTHON) -m pytest -q tests

type-check:
	$(PYTHON) -m mypy --ignore-missing-imports arxivc/client.py arxivc/fetch_service.py arxivc/routers/workflow_actions.py

validate:
	$(PYTHON) -m py_compile arxivc/*.py arxivc/routers/*.py scripts/*.py
	$(MAKE) lint
	$(MAKE) fmt-check
	$(MAKE) test
