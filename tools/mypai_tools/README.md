# `mypai_tools`

Python package containing MCP tool servers and background sidecar daemons for `omp-mypai`.

---

## Documentation Index

Detailed architectural specifications, CLI usage guidelines, and agent instructions are documented in dedicated spec files:

| Component | Type | Module | Specification & Documentation |
| :--- | :--- | :--- | :--- |
| **`mypai-tools` Skill** | Agent Skill | `mypai_tools` | [SKILL.md](../../skills/mypai-tools/SKILL.md) |
| **`cron-scheduler`** | MCP Server | `mypai_tools.cron_mcp` | [mcp.json](../../mcp.json) / [SKILL.md](../../skills/mypai-tools/SKILL.md#2-task-scheduling--one-shot-execution-cron-scheduler) |
| **`chat-channel`** | MCP Server | `mypai_tools.chat_mcp` | [mcp.json](../../mcp.json) / [SKILL.md](../../skills/mypai-tools/SKILL.md#4-signal-messaging-channel-chat-channel) |
| **`local-speech`** | MCP Server | `mypai_tools.speech_mcp` | [mcp.json](../../mcp.json) / [SKILL.md](../../skills/mypai-tools/SKILL.md#5-speech-processing-local-speech) |
| **`heartbeat`** | Daemon | `mypai_tools.heartbeat` | [heartbeat.md](heartbeat.md) |
| **`input_spooler`** | Daemon | `mypai_tools.input_spooler` | [input_spooler.md](input_spooler.md) |
| **`chat_bridge`** | Daemon | `mypai_tools.chat_bridge` | [chat_bridge.md](chat_bridge.md) |

---

## Installation & Tests

Managed via the root plugin [Makefile](../../Makefile):

```bash
make buildenv  # Create .venv and install mypai_tools in editable mode
make test      # Run unit tests in tools/tests/
make check     # Run linter and tests
```
