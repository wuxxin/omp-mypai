# AGENTS.md

## Repository Structure

- `plugin.json` — Plugin root manifest
- `mcp.json` — MCP server registry configuration
- `skills/` — Portable skills definitions
- `tools/mypai_tools/` — Python package (`mypai_tools`), MCP services, and background daemons
- `agents/` — Custom subagent prompt profiles
- `rules/` — Execution policies and guidelines
- `config/` — Hindsight bank configurations and templates

## Code Style & Commands

- **Style:** dont use long visual lines for comment sections, eg. "# -----------"

### Shell Scripts (`.sh`)

- **Style:** `#!/usr/bin/env bash`, 4-space indent, `set -euo pipefail`, quote `"$var"`, use `$(...)`, `lowercase_vars`, `UPPERCASE_CONSTANTS`.
- **Lint & Format:**
  ```bash
  shellcheck scripts/*.sh && shfmt -i 4 -w scripts/*.sh
  ```

### Python Scripts (`.py`)
- **Style:** `#!/usr/bin/env python3`, 4-space indent, type hints, `snake_case` (functions/vars), `PascalCase` (classes), triple-quote docstrings, explicit exception handling.
- **Lint, Test & Utility Commands (Makefile):**
  ```bash
  # Manage virtualenv, unit tests, and linting via Makefile
  make buildenv  # Builds .venv & installs editable package & dependencies
  make test      # Runs unit tests inside .venv
  make lint      # Runs ruff check inside .venv
  make check     # Runs linter and unit tests
  make cleanenv  # Removes .venv
  ```

## Operating Guidelines

- if asked for agent plugins conformity on this repo:
    - git pull into: `scratch/agent-plugins-spec` from `github.com/agentplugins/agent-plugins-spec`
    - read all specs, then read all omp_mypai plugin files, and fix nonconformity, or document in research/agent-plugins-conformity.md where easy fix not possible.
 
### Workspace & Documentation
- **Specification & Test Alignment Discipline:** Whenever modifying functionality, CLI options, REST endpoints, or behaviors in `mypai_tools/`, always update the corresponding unit test suite under `tools/tests/` and the architectural specifications under `skills/mypai_tools/references/` (`cli-usage.md`, `daemon-spec.md`, `daemon-api-spec.md`, `web-ui-spec.md`, `input_spooler.md`, `daemon-testing.md`) to keep code, tests, and documentation strictly synchronized.
- **Workspace Isolation:** Use `scratch/` for temporary files, research, and git checkouts (`scratch/*-sources`). Always use the top-level repository root `scratch/`: if checked out independently, use its own root `scratch/`; if checked out as a git submodule, use the parent repository's root `scratch/`.
- create and activate an venv for testing the mypai_tools, dont try to pip install with break system packages.

### Sandboxing & Bubblewrap (`bwrap`) Discipline
Check if running inside a bwrap sandbox:
```bash
[ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/systemd/private" ] || echo "bwrapped"
```
**If bwrapped (systemd socket unavailable):**
- **Restriction:** Do **NOT** execute systemd service management commands (`systemctl start/stop/restart/status`).
- **Introspection:** You **can** however inspect all active processes and logs using `journalctl` (`--user`), `ps`, `/proc`, and `pgrep`.
