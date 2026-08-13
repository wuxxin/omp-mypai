# omp-mypai Agent Plugin

Personal Artificial Intelligence (PAI) agent plugin based on **Oh-my-PI** and **Hindsight**,
adding Cron, Signal Chat, Inbound Spooler, and WebUI tools.

---

Repository Structure: see [AGENTS.md](AGENTS.md)


## Development & Testing (`Makefile`)

The plugin includes a dedicated [Makefile](Makefile) for virtualenv management, testing, and linting:

```bash
make buildenv  # Create .venv and install mypai_tools & dependencies
make test      # Run hermetic unit tests inside .venv (auto-builds .venv if missing)
make lint      # Run ruff check inside .venv
make check     # Run linter and execute unit tests
make clean     # Clean up test caches and Python bytecode
make cleanenv  # Remove .venv directory
```

## Sandbox Launcher & Service Configuration (`omp.env`)

The plugin environment launcher configuration is defined in [omp.env](../../omp.env):

- **Default Headless Service**: Keeps systemd sandbox service unit active while persistent sidecars run:
  ```bash
  LAUNCHER_SERVICE_ENABLED="true"
  LAUNCHER_SERVICE_CMD="sleep"
  LAUNCHER_SERVICE_ARGS="infinity"
  ```
- **Sidecars Project Binding (`sandbox-ctl` spec)**: `mypai_daemon` and `input_spooler` daemons are launched as background sidecars bound to the target project workspace:
  ```bash
  LAUNCHER_SIDECARS="mypai_daemon input_spooler"

  LAUNCHER_SIDECAR_MYPAI_DAEMON_CMD="python3"
  LAUNCHER_SIDECAR_MYPAI_DAEMON_ARGS="-m mypai_tools.daemon serve --project-dir $MYPAI_PROJECT_DIR --session-name $MYPAI_SESSION_NAME"

  LAUNCHER_SIDECAR_INPUT_SPOOLER_CMD="python3"
  LAUNCHER_SIDECAR_INPUT_SPOOLER_ARGS="-m mypai_tools.input_spooler daemon --project-dir $MYPAI_PROJECT_DIR"
  ```

## Configured MCP Servers (`.mcp.json`)

All MCP servers are declared in the OMP-native [`.mcp.json`](.mcp.json):

- **`chat-channel`**: Signal messaging interface (`mypai_tools.chat_mcp`).
- **`cron-scheduler`**: Task & cron job scheduler backed by SQLite and `mypai_daemon` REST API (`mypai_tools.cron_mcp`).


## Background Daemons & Services

Each daemon maintains detailed architectural specifications under `skills/mypai_tools/references/`:

- **mypai_daemon** (`python3 -m mypai_tools.daemon serve --project-dir "$MYPAI_PROJECT_DIR" --session-name "$MYPAI_SESSION_NAME"`)
  - **Spec**: [daemon-spec.md](skills/mypai_tools/references/daemon-spec.md) | [daemon-api-spec.md](skills/mypai_tools/references/daemon-api-spec.md) | [web-ui-spec.md](skills/mypai_tools/references/web-ui-spec.md)
  - **Function**: Central coordinator, fixed OMP RPC session manager (`MYPAI_SESSION_NAME`), MPSC turn serializer (`prompt`, `steer`, `followup`, `abort_and_prompt`), FastAPI REST server (Port 52080), Signal webhook whitelist filter, and embedded Glassmorphism SPA WebUI.
- **input_spooler** (`python3 -m mypai_tools.input_spooler daemon --project-dir "$MYPAI_PROJECT_DIR"`)
  - **Spec**: [input_spooler.md](skills/mypai_tools/references/input_spooler.md)
  - **Function**: Asynchronous sidecar daemon watching inbox folder (`~/Recordings/Inbox`), SHA256 hashing, sidecar parsing, STT transcription, Hindsight memory bank retention, and `mypai_daemon` REST notification.

---

## Agent Skills

All skills conform to the closed 6-field frontmatter schema ([agentskills.io](https://agentskills.io/specification)):

- **`mypai_tools`**: [SKILL.md](skills/mypai_tools/SKILL.md) — Complete agent guide for `mypai_tools` MCP servers, `mypai_daemon`, and references.
- **`hindsight-api`**: [SKILL.md](skills/hindsight-api/SKILL.md) — REST API guide for Hindsight memory bank management.
