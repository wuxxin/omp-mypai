# Makefile for omp-mypai plugin tools, daemons, and FastMCP services

VENV ?= .venv
INSTALL_VENV ?= .venv

VENV_BIN = $(VENV)/bin
PYTHON = $(VENV_BIN)/python3
RUFF = $(VENV_BIN)/ruff

INSTALL_VENV_BIN = $(INSTALL_VENV)/bin
INSTALL_PYTHON = $(INSTALL_VENV_BIN)/python3

SYSTEM_OMP_RPC_WHL = $(firstword $(wildcard /usr/share/oh-my-pi/python/omp-rpc/dist/*.whl))
SYSTEM_OMP_RPC_DIR = /usr/share/oh-my-pi/python/omp-rpc

OMP_RPC_SRC ?= $(if $(SYSTEM_OMP_RPC_WHL),$(SYSTEM_OMP_RPC_WHL),$(SYSTEM_OMP_RPC_DIR))

.PHONY: default help test clean lint check buildenv installenv cleaninstallenv cleanenv

# Default target prints usage instructions when invoked without arguments
default: help

help:
	@echo "omp-mypai Makefile Usage:"
	@echo "  make buildenv       - Create local virtualenv ($(VENV)) and install editable dependencies"
	@echo "  make buildenv OMP_RPC_SRC=../custom-omp-rpc"
	@echo "                      - Buildenv but install omp-rpc from a custom location"
	@echo "  make test           - Run unit tests inside venv (builds venv if missing)"
	@echo "  make lint           - Run ruff code linter inside venv (builds venv if missing)"
	@echo "  make coverage       - Run pytest with coverage reporting. COV_FAIL_UNDER=$(COV_FAIL_UNDER)"
	@echo "  make clean          - Clean up temporary test caches and Python bytecode"
	@echo "  make cleanenv       - Remove local virtualenv ($(VENV))"
	@echo "  make installenv     - Build independent plugin runtime venv (snapshot) into $(INSTALL_VENV)"
	@echo "  make cleaninstallenv- Clean and rebuild plugin runtime venv ($(INSTALL_VENV))"

$(VENV)/bin/pytest:
	@echo "Building virtual environment in $(VENV)..."
	@if [ ! -d "$(VENV)" ]; then uv venv $(VENV); fi
	echo "Installing omp-rpc from $(OMP_RPC_SRC)..."
	uv pip install --python $(PYTHON) "$(OMP_RPC_SRC)"
	echo "Installing plugin package and test dependencies"
	uv pip install --python $(PYTHON) -e ./src pytest pytest-asyncio ruff

buildenv: $(VENV)/bin/pytest

installenv:
	@echo "Building independent plugin runtime environment in $(INSTALL_VENV)..."
	rm -rf $(INSTALL_VENV)
	uv venv $(INSTALL_VENV)
	echo "Installing omp-rpc from $(OMP_RPC_SRC)..."
	uv pip install --python $(INSTALL_PYTHON) "$(OMP_RPC_SRC)"
	@echo "Installing plugin package from src..."
	uv pip install --python $(INSTALL_PYTHON) ./src
	@echo "Verifying runtime env import..."
	$(INSTALL_PYTHON) -c "import mypai_tools, mypai_tools.chat_mcp, mypai_tools.host_tools.cron_tools; print('runtime env OK')"

cleaninstallenv:
	@echo "Cleaning and rebuilding plugin runtime environment $(INSTALL_VENV)..."
	rm -rf $(INSTALL_VENV)
	$(MAKE) installenv

test: buildenv
	@echo "Running unit tests for omp-mypai in $(VENV)..."
	PYTHONPATH=src $(PYTHON) -m pytest src/tests -v

lint: buildenv
	@echo "Running ruff check on omp-mypai tools in $(VENV)..."
	$(RUFF) check src/ || true

coverage: buildenv
	@echo "Runing pytest with coverage reporting. COV_FAIL_UNDER=$(COV_FAIL_UNDER)"
	uv run --python $(INSTALL_PYTHON) pytest --junit-xml coverage.xml src

cleanenv:
	@echo "Removing virtual environment $(VENV)..."
	rm -rf $(VENV)

clean: cleanenv
	@echo "Cleaning temporary files, SQLite test caches, and Python bytecode..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "mypai_tools.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage .coverage.xml

