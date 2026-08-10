# Makefile for omp-mypai plugin tools, daemons, and FastMCP services

.PHONY: default help test clean lint check

# Default target prints usage instructions when invoked without arguments
default: help

help:
	@echo "omp-mypai Makefile Usage:"
	@echo "  make test   - Run unit tests for heartbeat daemon, executors, and cron_mcp"
	@echo "  make clean  - Clean up temporary files, SQLite test DBs, and Python bytecode"
	@echo "  make lint   - Run ruff code linter on tools codebase"
	@echo "  make check  - Run linter and execute unit tests"

test:
	@echo "Running unit tests for omp-mypai..."
	PYTHONPATH=tools python3 -m unittest discover -s tools/tests -p "test_*.py" -v

clean:
	@echo "Cleaning temporary files, SQLite test caches, and Python bytecode..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage

lint:
	@echo "Running ruff check on omp-mypai tools..."
	ruff check tools/ || true

check: test lint
