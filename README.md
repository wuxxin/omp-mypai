# omp-mypai Agent Plugin

Official **Agent Plugins 1.0.0** compliant plugin package for **`mypai`** and **`oh-my-pi` (omp)**.

## Package Structure

```
omp-mypai/
├── plugin.json             # Agent Plugins 1.0.0 root manifest
├── mcp.json                # Agent Plugins 1.0.0 MCP server registry
├── skills/                 # Portable skills (agentskills.io format)
│   ├── mypai-tools/
│   ├── arbor/
│   ├── hindsight-api/
│   ├── sequential-thinking/
│   └── openadapt/
├── tools/                  # Python mypai_tools package & daemons
│   └── mypai_tools/
│       ├── chat_mcp.py
│       ├── chat_bridge.py
│       ├── cron_mcp.py
│       ├── heartbeat.py
│       ├── input_spooler.py
│       └── speech_mcp.py
├── agents/                 # Subagent prompt profiles (pai, reviewer, scout, etc.)
├── rules/                  # Execution policies (verification.md)
└── config/                 # Bank configs & templates
```

## Configured MCP Servers (`mcp.json`)

- **`chat-channel`**: Signal messaging interface (`mypai_tools.chat_mcp`).
- **`cron-scheduler`**: Task & cron job scheduler backed by SQLite (`mypai_tools.cron_mcp`).
- **`local-speech`**: Speech-to-text (Whisper) & Text-to-speech (`mypai_tools.speech_mcp`).
- **`arbor`**: Graph-native AST code intelligence (`arbor mcp`).
- **`sequential-thinking`**: 
- **`openadapt`**:

## Daemons

- **heartbeat**: `python3 -m mypai_tools.heartbeat daemon`
  - Background cron runner & RPC poke engine for periodic work audits and Hindsight reflection sweeps (`daemon` or `once` mode).
- **input_spooler**: `python3 -m mypai_tools.input_spooler watch`
  - Inbox folder file watcher with 10s quiescence gating, SHA256 hashing, sidecar parsing, STT, and Hindsight retention (`watch` or `once` mode).
- **chat_bridge**: `python3 -m mypai_tools.chat_bridge`
  - RPC poke bridge forwarding incoming Signal messages to persistent OMP daemon with Hindsight recall. |

## Skills

- **`mypai-tools`**: Complete guide for using `mypai_tools` MCP services (`cron-scheduler`, `chat-channel`, `local-speech`) and background daemons (`heartbeat`, `input_spooler`, `chat_bridge`).
- **`arbor`**: Graph-native AST code intelligence and workspace navigation.
- **`sequential-thinking`**: Dynamic reflective reasoning chain.
- **`openadapt`**: Browser capture and UI automation skills.
- **`hindsight-api`**: REST API guide for Hindsight memory bank management and mental model updates.

