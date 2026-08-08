# mypai_tools

Agent tools package and MCP servers for mypai / Oh-my-PI.

## Background Daemons

### Heartbeat Daemon (`heartbeat.py`)
- **Invocation**: `python3 -m mypai_tools.heartbeat daemon|once [--project-dir <path>]`
- **Modes**:
  - `daemon`: Run continuous background scheduler loop.
  - `once`: Execute a single pass over all active database jobs and exit.
- **Options**: `--project-dir <path>`, `--project-db <path>`, `--rpc-url <url>`, `-v` / `--verbose`.
- **Behavior**: Manages `heartbeat.pid` in the project DB directory, loads jobs from `cron.db` (auto-seeding `default_jobs.json` if absent), and executes triggers via APScheduler `AsyncIOScheduler`.

### Input Spooler (`input_spooler.py`)
Inbox folder file ingestion pipeline watcher and STT / Hindsight retention.
- **Invocation**: `python3 -m mypai_tools.input_spooler daemon|once [--inbox <path>]`
- **Modes**:
  - `daemon`: Run continuous inbox directory polling loop.
  - `once`: Execute a single scan pass over the inbox folder and exit.
- **Options**: `--inbox <path>`, `--stt-url <url>`, `--hindsight-url <url>`, `--bank-id <id>`, `--quiescence-sec <sec>`, `--state-file <path>`, `-v` / `--verbose`.
- **Behavior**: Monitors drop folder (`~/Recordings/Inbox`), applies 10s quiescence stability gating, SHA256 content hashing, sidecar markdown metadata parsing, STT transcription, and Hindsight memory bank retention.

### Chat Bridge (`chat_bridge.py`)
RPC bridge for forwarding incoming Signal messages to the persistent OMP daemon with Hindsight recall.
- **Invocation**: `python3 -m mypai_tools.chat_bridge [options]`
- **Options**: `--poll-interval <sec>`, `--once`.
- **Behavior**: Background RPC bridge listening for incoming Signal messages, recalling sender/global context from Hindsight REST API (`http://localhost:8888`), poking the persistent OMP daemon (`http://localhost:51080/v1/rpc`), and dispatching responses back via Signal.


## MCP Services

### `cron_mcp`
MCP server for project cron task management (`"cron-scheduler"`).
- **Runner**: `python3 -m mypai_tools.cron_mcp`
- **Database**: Per-project SQLite DB at `$HOME/.omp/cron/projects/<project_hash>/cron.db`.
- **Tools Exposed**: `cron_add_job`, `cron_remove_job`, `cron_pause_job`, `cron_resume_job`, `cron_list_jobs`, `cron_modify_job`, `cron_import_jobs`, `cron_export_jobs`.

### `chat_mcp`
MCP server for Nanobot Signal messaging integration (`"chat-channel"`).
- **Runner**: `python3 -m mypai_tools.chat_mcp`
- **Tools Exposed**: `get_pending_signal_messages`, `send_signal_message`, `list_signal_chats`.

### `speech_mcp`
MCP server for local STT (Speech-to-Text) and TTS (Text-to-Speech) processing (`"local-speech"`).
- **Runner**: `python3 -m mypai_tools.speech_mcp`
- **Tools Exposed**: `transcribe_audio` (Whisper port 50090), `synthesize_speech` (TTS port 50095).
