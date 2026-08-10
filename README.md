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

- **`chat-channel`**: Signal messaging interface (`mypai_tools.chat_mcp`).
- **`cron-scheduler`**: Task & cron job scheduler backed by SQLite (`mypai_tools.cron_mcp`).
- **`local-speech`**: Speech-to-text (Whisper) & Text-to-speech (`mypai_tools.speech_mcp`).
- **`arbor`**: Graph-native AST code intelligence (`arbor mcp`).
- **`openadapt`**:

## Daemons

- **heartbeat**: `python3 -m mypai_tools.heartbeat daemon`
  - Background cron runner & RPC poke engine for periodic work audits and Hindsight reflection sweeps (`daemon` or `once` mode).
- **input_spooler**: `python3 -m mypai_tools.input_spooler daemon`
  - Inbox folder file watcher, SHA256 hashing, sidecar parsing, STT, and Hindsight retention (`daemon` or `once` mode).
- **chat_bridge**: `python3 -m mypai_tools.chat_bridge daemon`
  - RPC poke bridge forwarding incoming Signal messages to persistent OMP daemon with Hindsight recall. |

## Skills

- **`mypai-tools`**: Complete guide for using `mypai_tools` MCP services (`cron-scheduler`, `chat-channel`, `local-speech`) and background daemons (`heartbeat`, `input_spooler`, `chat_bridge`).
- **`arbor`**: Graph-native AST code intelligence and workspace navigation.
- **`openadapt`**: Browser capture and UI automation skills.
- **`hindsight-api`**: REST API guide for Hindsight memory bank management and mental model updates.

