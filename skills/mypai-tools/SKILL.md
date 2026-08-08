---
name: mypai-tools
description: Complete guide for using mypai_tools MCP services (cron-scheduler, chat-channel, local-speech) and background daemons (heartbeat, input_spooler, chat_bridge). Use when scheduling automated jobs, processing Signal messages, handling STT/TTS audio, or interacting with per-project cron entries.
---

# `mypai_tools` MCP Services


`mypai_tools` exposes three primary MCP servers configured in `config.yml`:

| MCP Server Name | Module Runner | Purpose | Key Tools |
|---|---|---|---|
| `cron-scheduler` | `python3 -m mypai_tools.cron_mcp` | Project task & cron scheduling via SQLite DB (`$HOME/.omp/cron/projects/<project_hash>/cron.db`). | `cron_add_job`, `cron_remove_job`, `cron_pause_job`, `cron_resume_job`, `cron_list_jobs`, `cron_modify_job`, `cron_import_jobs`, `cron_export_jobs` |
| `chat-channel` | `python3 -m mypai_tools.chat_mcp` | Signal messaging interface via `signal-cli` and Nanobot Gateway. | `get_pending_signal_messages`, `send_signal_message`, `list_signal_chats` |
| `local-speech` | `python3 -m mypai_tools.speech_mcp` | Local STT transcription and TTS synthesis | `transcribe_audio`, `synthesize_speech` |


## 1. Task Scheduling (`cron-scheduler`)

Per-project cron tasks are stored in SQLite databases located at `$HOME/.omp/cron/projects/<project_hash>/cron.db`.

### Supported Job Types

- **`"rpc"`** *(default)*: Sends JSON-RPC pokes to the OMP agent service endpoint.
- **`"command"`**: Executes local CLI shell commands.
- **`"http"`**: Executes HTTP REST calls (`GET`, `POST`, `PUT`, `PATCH`) to specified URLs with JSON headers and body.

### Common Usage Patterns

#### Adding a Scheduled Job
```python
# Schedule a recurring RPC work sweep every 30 minutes
cron_add_job(
    name="30m Work Sweep",
    cron_expression="*/30 * * * *",
    prompt="Audit active tasks and reflect on project progress",
    job_type="rpc",
    job_action='{"method": "work_sweep", "params": {"audit": true}}'
)

# Schedule a shell command execution every morning at 8 AM
cron_add_job(
    name="Daily Backup",
    cron_expression="0 8 * * *",
    prompt="Backup project state",
    job_type="command",
    job_action="tar -czf /tmp/backup.tar.gz ."
)
```

> [!NOTE]
> `cron_add_job` automatically checks if the `heartbeat.pid` daemon process is alive for the current project. If the heartbeat runner is offline, it returns status `"scheduled_heartbeat_offline"` with a helpful warning message.

#### Managing & Exporting Jobs
- **Listing**: Call `cron_list_jobs()` to inspect all active/paused jobs and next run times.
- **Pausing / Resuming**: Call `cron_pause_job(job_id)` or `cron_resume_job(job_id)`.
- **Import / Export**:
  - Export: `cron_export_jobs(file_path="schedule_backup.json")`
  - Import: `cron_import_jobs(file_path="schedule_backup.json")`

---

## 2. Signal Messaging (`chat-channel`)

Interacts with local `signal-cli` (port 50889) and Nanobot REST gateway (port 8790).

### Fetching & Responding to Messages
```python
# 1. Fetch pending unread messages
messages = get_pending_signal_messages(limit=1)

# 2. Reply to recipient
send_signal_message(
    recipient="+1234567890",
    message="Task completed successfully!"
)
```

---

## 3. Audio & Speech Processing (`local-speech`)

Processes audio files and voice synthesis using local OpenAI-compatible inference servers.

### Audio Transcription & Speech Synthesis
```python
# Transcribe audio recording to text
result = transcribe_audio(file_path="/path/to/voice_note.wav", language="en")
transcript = result.get("text")

# Synthesize text to WAV audio output
speech_res = synthesize_speech(
    text="Hello, your background task has completed.",
    voice="serena",
    output_file="~/.omp/scratch/response.wav"
)
audio_path = speech_res.get("file_path")
```

