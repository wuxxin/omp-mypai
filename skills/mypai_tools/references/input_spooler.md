# Input Spooler Daemon Architectural Specification (`input_spooler.md`)

## Executive Summary

The **Input Spooler Daemon** (`mypai_tools.input_spooler`) is an independent, persistent **asynchronous sidecar daemon** for **MyPAI**. It watches an inbox folder (`~/Recordings/Inbox`), detects dropped audio/text/document files, applies quiescence file-stability gating, parses sidecar metadata, transcribes audio via local Whisper STT, hashes content for idempotency, retains facts in **Hindsight** vector memory, and notifies active **OMP** sessions by calling the **`mypai_daemon` REST API**.

> [!IMPORTANT]
> **Asynchronous Sidecar Architecture**: `input_spooler` runs continuously in the background as an asynchronous sidecar daemon (`python3 -m mypai_tools.input_spooler daemon`). It connects to `mypai_daemon` over HTTP REST (`POST http://127.0.0.1:52080/api/v1/session/prompt`) rather than invoking OMP RPC sockets directly.

---

## 1. Primary Responsibilities & Functional Features

1. **Inbox Directory Monitoring & Quiescence Gating**:
   - Watches `~/Recordings/Inbox` for new audio recordings, voice notes, markdown notes, or document drops.
   - Implements a 10-second file modification quiescence threshold to prevent reading partially written files.

2. **Deduplication via SHA256 Hashing**:
   - Computes SHA256 digest of ingested files and stores processed hashes in `~/.omp/profiles/<profile>/data/omp-mypai/spooler_processed_hashes.json` (or `~/.omp/data/omp-mypai/` for default profile).
   - Prevents duplicate processing on process restarts or repeated directory scans.

3. **Sidecar Metadata Parsing**:
   - Scans for accompanying `.md` or `.json` sidecar files (e.g. `recording_123.wav` + `recording_123.md`).
   - Extracts structured metadata fields (`title`, `author`, `tags`, `timestamp`, `context`) to enrich memory retention payloads.

4. **Speech-to-Text (STT) Ingestion**:
   - For audio formats (`.wav`, `.m4a`, `.mp3`, `.ogg`, `.flac`), dispatches HTTP multipart requests to local Whisper STT service (`http://localhost:50090/v1/audio/transcriptions`).

5. **Hindsight Long-Term Memory Retention**:
   - Posts transcribed audio or text contents to Hindsight API (`http://localhost:8888/v1/default/banks/{bank_id}/retain`).
   - Tags memories with project, source, and ingestion timestamps.

6. **Agent Notification via `mypai_daemon` REST API**:
   - Issues an HTTP request to `mypai_daemon` endpoint:
     `POST http://127.0.0.1:52080/api/v1/session/prompt`
   - Request Body:
     ```json
     {
       "prompt": "🎙️ New inbox voice note transcribed: 'Remember to check the deployment logs.'",
       "mode": "prompt",
       "source": "spooler",
       "context": {
         "file_path": "/home/user/Recordings/Inbox/note_1.wav",
         "hindsight_bank": "mypai"
       }
     }
     ```
   - Supports `mode` selection (`prompt`, `steer`, `followup`, `abort_and_prompt`).

---

## 2. Asynchronous Sidecar Launching & Execution

```bash
# Asynchronous sidecar daemon mode (Continuous background execution in mypai profile)
python3 -m mypai_tools.input_spooler daemon [--inbox ~/Recordings/Inbox] [--profile mypai]

# Optional flags
python3 -m mypai_tools.input_spooler daemon \
  --inbox ~/Recordings/Inbox \
  --profile mypai \
  --stt-url http://localhost:50090/v1/audio/transcriptions \
  --hindsight-url http://localhost:8888 \
  --daemon-url http://127.0.0.1:52080 \
  --bank-id mypai \
  --quiescence-sec 10 \
  -v
```
