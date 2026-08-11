# Input Spooler Daemon Architectural Specification (`input_spooler.md`)

## Executive Summary

The **Input Spooler Daemon** (`mypai_tools.input_spooler`) is an independent, persistent **asynchronous sidecar daemon** for **MyPAI**. It watches an inbox folder (`~/Recordings/Inbox`), detects dropped audio/text/document files, applies quiescence file-stability gating, parses sidecar metadata, transcribes audio via local Whisper STT, hashes content for idempotency, retains facts in **Hindsight** vector memory, and notifies active **OMP** sessions using `omp_rpc.RpcClient`.

> [!IMPORTANT]
> **Asynchronous Sidecar Architecture**: `input_spooler` runs continuously in the background as an asynchronous sidecar daemon (`python3 -m mypai_tools.input_spooler daemon`). It is **NOT** invoked as a periodic cron job by `heartbeat` or `cron_mcp`.

---

## 1. Primary Responsibilities & Functional Features

1. **Inbox Directory Monitoring & Quiescence Gating**:
   - Watches `~/Recordings/Inbox` for new audio recordings, voice notes, markdown notes, or document drops.
   - Implements a 10-second file modification quiescence threshold to prevent reading partially written files.

2. **Deduplication via SHA256 Hashing**:
   - Computes SHA256 digest of ingested files and stores processed hashes in `~/.omp/spooler/processed_hashes.json`.
   - Prevents duplicate processing on process restarts or repeated scans.

3. **Sidecar Metadata Parsing**:
   - Scans for accompanying `.md` or `.json` sidecar files (e.g. `recording_123.wav` + `recording_123.md`).
   - Extracts structured metadata fields (`title`, `author`, `tags`, `timestamp`, `context`) to enrich memory retention payloads.

4. **Speech-to-Text (STT) Ingestion**:
   - For audio formats (`.wav`, `.m4a`, `.mp3`, `.ogg`, `.flac`), dispatches HTTP multipart requests to local Whisper STT service (`http://localhost:50090/v1/audio/transcriptions`).

5. **Hindsight Long-Term Memory Retention**:
   - Posts transcribed audio or text contents to Hindsight API (`http://localhost:8888/v1/default/banks/{bank_id}/retain`).
   - Tags memories with project, source, and ingestion timestamps.

6. **Agent Notification via `omp_rpc`**:
   - Queues customized notification prompts into active `omp` session turns using `omp_rpc.RpcClient`.

---

## 2. Asynchronous Sidecar Launching & Execution

```bash
# Asynchronous sidecar daemon mode (Continuous background execution)
python3 -m mypai_tools.input_spooler daemon [--inbox ~/Recordings/Inbox]

# Optional flags
python3 -m mypai_tools.input_spooler daemon \
  --inbox ~/Recordings/Inbox \
  --stt-url http://localhost:50090/v1 \
  --hindsight-url http://localhost:8888 \
  --bank-id mypai-orchestrator \
  --quiescence-sec 10 \
  -v
```
