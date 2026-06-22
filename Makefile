# HydraBrain — convenience targets. `make help` lists them.
# All targets use a local .venv so they work on modern macOS/Linux (PEP 668).

VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: help install dev global web mcp doctor test clean

help:
	@echo "HydraBrain make targets:"
	@echo "  make install   venv + runtime deps, then guided key setup (hydrabrain init)"
	@echo "  make dev       editable install + dev tools (pytest/ruff/mypy)"
	@echo "  make global    install a GLOBAL 'hydrabrain' command via pipx (isolated)"
	@echo "  make web       launch the web UI"
	@echo "  make mcp       run the MCP stdio server"
	@echo "  make doctor    health check"
	@echo "  make test      run the test suite"
	@echo "  make clean     remove .venv and build artifacts"

$(PY):
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip

install: $(PY)
	$(PY) -m pip install -q -r requirements.txt
	$(PY) -m hydrabrain.cli init

dev: $(PY)
	$(PY) -m pip install -q -e ".[bench,dev]"
	@echo "✓ editable install ready — run: source $(VENV)/bin/activate"

# Global 'hydrabrain' command, isolated by pipx (also dodges PEP 668).
global:
	@command -v pipx >/dev/null 2>&1 || { echo "pipx not found — install it: brew install pipx (or python3 -m pip install --user pipx)"; exit 1; }
	pipx install --force .
	@echo "✓ 'hydrabrain' is now on your PATH — run: hydrabrain init"

web: install
	$(PY) -m hydrabrain.cli web --open

mcp: $(PY)
	$(PY) -m hydrabrain.cli serve

doctor: $(PY)
	$(PY) -m hydrabrain.cli doctor

test: dev
	$(PY) -m pytest -q

clean:
	rm -rf $(VENV) build dist *.egg-info hydrabrain.egg-info
	@echo "✓ cleaned"
