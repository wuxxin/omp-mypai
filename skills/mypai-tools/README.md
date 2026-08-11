# `mypai_tools`

Python package containing MCP tool servers and background sidecar daemons for `omp-mypai`.

Detailed architectural specifications, CLI usage guidelines, and agent instructions are documented in dedicated spec files:

- Agent Skill: `mypai_tools`: [SKILL.md](SKILL.md)
- References: `mypai_tools`: [references/](references/)

## Installation & Tests

Managed via the root plugin [Makefile](../../Makefile):

```bash
make buildenv  # Create .venv and install mypai_tools in editable mode
make test      # Run unit tests in tools/tests/
make check     # Run linter and tests
```
