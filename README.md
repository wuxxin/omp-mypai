# omp-mypai Agent Plugin

Personal Artificial Intelligence (PAI) agent plugin based on **Oh-my-PI** and **Hindsight** adding Cron, Chat, Inbound Spooler and speech tools

## Repository Structure

- `plugin.json` — Plugin root manifest
- `mcp.json` — MCP server registry configuration
- `skills/` — Portable skills definitions
- `tools/mypai_tools/` — Python package (`mypai_tools`), MCP services, and background daemons
- `agents/` — Custom subagent prompt profiles
- `rules/` — Execution policies and guidelines
- `config/` — Hindsight bank configurations and templates

## Configured MCP Servers (`mcp.json`)

All MCP servers comply with **Agent Plugins 1.0.0 Standard** (`https://agent-plugins.org/schemas/1.0.0/mcp.schema.json`) and are declared in [mcp.json](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/mcp.json):

- **`chat-channel`**: Signal messaging interface (`mypai_tools.chat_mcp`).
- **`cron-scheduler`**: Task & cron job scheduler backed by SQLite (`mypai_tools.cron_mcp`).
- **`local-speech`**: Speech-to-text (Whisper) & Text-to-speech (`mypai_tools.speech_mcp`).
- **`arbor`**: Graph-native AST code intelligence (`arbor mcp`).
- **`openadapt`**: GUI/Browser capture and process automation (`openadapt`).

---

## Background Daemons

Each daemon maintains a standalone architectural specification document under `tools/mypai_tools/`:

- **heartbeat** (`python3 -m mypai_tools.heartbeat daemon`)
  - **Spec**: [heartbeat.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/tools/mypai_tools/heartbeat.md)
  - **Function**: Background cron runner, SQLite WAL manager, & RPC poke engine for periodic work audits and Hindsight reflection sweeps (`daemon` or `once` mode).
- **input_spooler** (`python3 -m mypai_tools.input_spooler daemon`)
  - **Spec**: [input_spooler.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/tools/mypai_tools/input_spooler.md)
  - **Function**: Asynchronous sidecar daemon watching inbox folder (`~/Recordings/Inbox`), SHA256 hashing, sidecar parsing, STT transcription, and Hindsight memory bank retention. Enabled via `LAUNCHER_SIDECARS` in `omp.env`.
- **chat_bridge** (`python3 -m mypai_tools.chat_bridge daemon`)
  - **Spec**: [chat_bridge.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/tools/mypai_tools/chat_bridge.md)
  - **Function**: RPC bridge forwarding incoming Signal messages to active OMP sessions with Hindsight recall.

---

## Agent Skills

All skills conform to the closed 6-field frontmatter schema ([agentskills.io](https://agentskills.io/specification)):

- **`mypai-tools`**: [SKILL.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/skills/mypai-tools/SKILL.md) — Complete agent guide for `mypai_tools` MCP servers and background daemons.
- **`arbor`**: [SKILL.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/skills/arbor/SKILL.md) — Graph-native AST code intelligence and workspace navigation.
- **`openadapt`**: [SKILL.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/skills/openadapt/SKILL.md) — Browser capture and UI automation.
- **`hindsight-api`**: [SKILL.md](file:///home/wuxxin/agent-shared/code/mypai/submodules/omp-mypai/skills/hindsight-api/SKILL.md) — REST API guide for Hindsight memory bank management and mental model updates.


