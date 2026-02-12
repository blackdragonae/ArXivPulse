.PHONY: help smoke profile validate

PYTHON ?= .venv/bin/python
NODE ?= node
APP_JS := frontend/app.js

help:
	@echo "Available targets:"
	@echo "  make smoke    - run API smoke checks"
	@echo "  make profile  - run hot-path profiling"
	@echo "  make validate - compile Python, check JS syntax, run smoke checks"

smoke:
	$(PYTHON) scripts/smoke_api.py

profile:
	$(PYTHON) scripts/profile_hotpaths.py

validate:
	$(PYTHON) -m py_compile arxivc/*.py scripts/*.py
	@if command -v $(NODE) >/dev/null 2>&1; then \
		$(NODE) --check $(APP_JS); \
	else \
		echo "node not found; skipping JS syntax check"; \
	fi
	$(PYTHON) scripts/smoke_api.py
