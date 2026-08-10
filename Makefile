# Makefile for omp-mypai plugin tools, daemons, and FastMCP services

VENV ?= .venv
VENV_BIN = $(VENV)/bin
PYTHON = $(VENV_BIN)/python3
RUFF = $(VENV_BIN)/ruff
OMP_RPC_DIR ?= $(shell pwd)/../../scratch/oh-my-pi/python/omp-rpc

.PHONY: default help test clean lint check buildenv cleanenv

# Default target prints usage instructions when invoked without arguments
default: help

help:
	@echo "omp-mypai Makefile Usage:"
	@echo "  make buildenv - Create local virtualenv (.venv) and install dependencies"
	@echo "  make test     - Run unit tests inside venv (builds venv if missing)"
	@echo "  make lint     - Run ruff code linter inside venv (builds venv if missing)"
	@echo "  make check    - Run linter and execute unit tests inside venv"
	@echo "  make clean    - Clean up temporary test caches and Python bytecode"
	@echo "  make cleanenv - Remove local virtualenv (.venv)"

$(VENV)/bin/activate:
	@echo "Building virtual environment in $(VENV)..."
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip setuptools wheel 2>/dev/null || true
	if [ -d "$(OMP_RPC_DIR)" ]; then \
		if command -v uv >/dev/null 2>&1; then \
			uv pip install --python $(PYTHON) -e "$(OMP_RPC_DIR)"; \
		else \
			$(PYTHON) -m pip install -e "$(OMP_RPC_DIR)"; \
		fi; \
	fi
	if command -v uv >/dev/null 2>&1; then \
		uv pip install --python $(PYTHON) -e tools/mypai_tools ruff; \
	else \
		$(PYTHON) -m pip install -e tools/mypai_tools ruff; \
	fi

buildenv: $(VENV)/bin/activate

test: buildenv
	@echo "Running unit tests for omp-mypai in $(VENV)..."
	PYTHONPATH=tools $(PYTHON) -m unittest discover -s tools/tests -p "test_*.py" -v

lint: buildenv
	@echo "Running ruff check on omp-mypai tools in $(VENV)..."
	$(RUFF) check tools/ || true

check: test lint

cleanenv:
	@echo "Removing virtual environment $(VENV)..."
	rm -rf $(VENV)

clean:
	@echo "Cleaning temporary files, SQLite test caches, and Python bytecode..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage
