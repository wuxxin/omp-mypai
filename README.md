# omp-mypai Agent Plugin

Personal Artificial Intelligence (PAI) agent plugin based on **Oh-my-PI** and **Hindsight**,
adding Host-Native Cron, Signal Chat, Inbound Spooler, and WebUI tools.

---

Repository Structure: see [AGENTS.md](AGENTS.md)

## Development & Testing (`Makefile`)

The plugin includes a dedicated [Makefile](Makefile) for virtualenv management, testing, and linting:

- Create .venv and install mypai_tools & dependencies: `make buildenv`
- Buildenv but install omp-rpc from a custom location: 
  - `make buildenv OMP_RPC_SRC=../custom-omp-rpc`
- Run unit tests inside .venv: `make test`
- Run ruff check inside .venv: `make lint`
- Run both test and linter `make check`
- Clean up test caches and Python bytecode: `make clean`
- Remove .venv directory: `make cleanenv`

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
  LAUNCHER_SIDECAR_MYPAI_DAEMON_ARGS="-m mypai_tools.daemon serve --agent-dir $MYPAI_AGENT_DIR"

  LAUNCHER_SIDECAR_INPUT_SPOOLER_CMD="python3"
  LAUNCHER_SIDECAR_INPUT_SPOOLER_ARGS="-m mypai_tools.input_spooler daemon --agent-dir $MYPAI_AGENT_DIR"
  ```


## Configured MCP Servers and Agent Skills

MCP servers are declared in the OMP-native [`.mcp.json`](.mcp.json):

- **`signal_chat`**: Signal messaging interface (`mypai_tools.chat_mcp`).

Agent Skills ([agentskills.io](https://agentskills.io/specification)):

- **`mypai_tools`**: [SKILL.md](skills/mypai_tools/SKILL.md) — Complete agent guide for `mypai_tools` Host Tools (cron), MCP servers, `mypai_daemon`, and references.


## Background Daemons & Services

Each daemon maintains detailed architectural specifications under `skills/mypai_tools/references/`:

- **mypai_daemon** (`python3 -m mypai_tools.daemon serve --agent-dir "$MYPAI_AGENT_DIR"`)
  - **Spec**: [daemon-spec.md](skills/mypai_tools/references/daemon-spec.md) | [daemon-api-spec.md](skills/mypai_tools/references/daemon-api-spec.md) | [acp-tool-spec.md](skills/mypai_tools/references/acp-tool-spec.md) | [web-ui-spec.md](skills/mypai_tools/references/web-ui-spec.md) | [cron-spec.md](skills/mypai_tools/references/cron-spec.md)
  - **Function**: Central coordinator, 2-Tier execution architecture, fixed OMP RPC session manager, Turn Queue priority-flush serializer (`prompt`, `steer`, `followup`, `abort_and_prompt`), native Host Tools (`cron`, `acp`), FastAPI REST server (Port 52080), Signal webhook whitelist filter, and 3-tab WebUI console.


- **input_spooler** (`python3 -m mypai_tools.input_spooler daemon --agent-dir "$MYPAI_AGENT_DIR"`)
  - **Spec**: [input_spooler.md](skills/mypai_tools/references/input_spooler.md)
  - **Function**: Asynchronous sidecar daemon watching inbox folder (`~/Recordings/Inbox`), SHA256 hashing, sidecar parsing, STT transcription, Hindsight memory bank retention, and `mypai_daemon` REST notification.
