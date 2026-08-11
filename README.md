# omp-mypai Agent Plugin

Personal Artificial Intelligence (PAI) agent plugin based on **Oh-my-PI** and **Hindsight** adding Cron, Chat, Inbound Spooler and speech tools.

---

## 1. Development & Testing (`Makefile`)

The plugin includes a dedicated [Makefile](Makefile) for virtualenv management, testing, and linting:

```bash
make buildenv  # Create .venv and install mypai_tools & dependencies
make test      # Run unit tests inside .venv (auto-builds .venv if missing)
make lint      # Run ruff check inside .venv
make check     # Run linter and execute unit tests
make clean     # Clean up test caches and Python bytecode
make cleanenv  # Remove .venv directory
```

---

## 2. Sandbox Launcher & Service Configuration (`omp.env`)

The plugin environment launcher configuration is defined in [omp.env](../../omp.env):

- **Default Headless Service**: Executes `omp --headless` inside the target workspace directory (`$MYPAI_PROJECT_DIR`).
  ```bash
  LAUNCHER_SERVICE_ENABLED="true"
  LAUNCHER_SERVICE_CMD="omp"
  LAUNCHER_SERVICE_ARGS="--headless"
  ```
- **Sidecars Project Binding (`sandbox-ctl` spec)**: `heartbeat` and `input_spooler` daemons are launched as background sidecars bound to the target project workspace:
  ```bash
  LAUNCHER_SIDECARS="heartbeat input_spooler"

  LAUNCHER_SIDECAR_HEARTBEAT_CMD="python3"
  LAUNCHER_SIDECAR_HEARTBEAT_ARGS="-m mypai_tools.heartbeat daemon --project-dir $MYPAI_PROJECT_DIR"

  LAUNCHER_SIDECAR_INPUT_SPOOLER_CMD="python3"
  LAUNCHER_SIDECAR_INPUT_SPOOLER_ARGS="-m mypai_tools.input_spooler daemon --project-dir $MYPAI_PROJECT_DIR"
  ```

---

## 3. Repository Structure

- `Makefile` — Buildenv, virtualenv, testing, and linting targets
- `plugin.json` — Plugin root manifest
- `mcp.json` — MCP server registry configuration
- `skills/` — Portable skills definitions
- `tools/mypai_tools/` — Python package (`mypai_tools`), MCP services, and background daemons
- `agents/` — Custom subagent prompt profiles
- `rules/` — Execution policies and guidelines
- `config/` — Hindsight bank configurations and templates

---

## 4. Configured MCP Servers (`mcp.json`)

All MCP servers comply with **Agent Plugins 1.0.0 Standard** (`https://agent-plugins.org/schemas/1.0.0/mcp.schema.json`) and are declared in [mcp.json](mcp.json):

- **`chat-channel`**: Signal messaging interface (`mypai_tools.chat_mcp`).
- **`cron-scheduler`**: Task & cron job scheduler backed by SQLite (`mypai_tools.cron_mcp`).
- **`local-speech`**: Speech-to-text (Whisper) & Text-to-speech (`mypai_tools.speech_mcp`).
- **`arbor`**: Graph-native AST code intelligence (`arbor mcp`).
- **`openadapt`**: GUI/Browser capture and process automation (`openadapt`).

---

## 5. Background Daemons

Each daemon maintains a standalone architectural specification document under `tools/mypai_tools/`:

- **heartbeat** (`python3 -m mypai_tools.heartbeat daemon --project-dir "$MYPAI_PROJECT_DIR"`)
  - **Spec**: [heartbeat.md](tools/mypai_tools/heartbeat.md)
  - **Function**: Background cron runner, SQLite WAL manager, & RPC poke engine for periodic work audits and Hindsight reflection sweeps (`daemon`, `once`, `import`, or `export` mode).
- **input_spooler** (`python3 -m mypai_tools.input_spooler daemon --project-dir "$MYPAI_PROJECT_DIR"`)
  - **Spec**: [input_spooler.md](tools/mypai_tools/input_spooler.md)
  - **Function**: Asynchronous sidecar daemon watching inbox folder (`~/Recordings/Inbox`), SHA256 hashing, sidecar parsing, STT transcription, and Hindsight memory bank retention.
- **chat_bridge** (`python3 -m mypai_tools.chat_bridge daemon --project-dir "$MYPAI_PROJECT_DIR"`)
  - **Spec**: [chat_bridge.md](tools/mypai_tools/chat_bridge.md)
  - **Function**: RPC bridge forwarding incoming Signal messages to active OMP sessions with Hindsight recall.

---

## 6. Agent Skills

All skills conform to the closed 6-field frontmatter schema ([agentskills.io](https://agentskills.io/specification)):

- **`mypai-tools`**: [SKILL.md](skills/mypai-tools/SKILL.md) — Complete agent guide for `mypai_tools` MCP servers and background daemons.
- **`arbor`**: [SKILL.md](skills/arbor/SKILL.md) — Graph-native AST code intelligence and workspace navigation.
- **`openadapt`**: [SKILL.md](skills/openadapt/SKILL.md) — Browser capture and UI automation.
- **`hindsight-api`**: [SKILL.md](skills/hindsight-api/SKILL.md) — REST API guide for Hindsight memory bank management and mental model updates.
