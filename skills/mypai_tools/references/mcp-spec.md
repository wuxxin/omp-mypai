# MyPAI FastMCP Tool Servers Specification (`mcp-spec.md`)

## Executive Summary

`mypai_tools` configures FastMCP tool servers for external protocol integrations that benefit from stdio isolation:

1. **`signal_chat`** (`mypai_tools.chat_mcp`): Signal messaging tools delegating to `mypai_tools.signal_client.SignalClient`.
2. **`local-speech`** (`mypai_tools.speech_mcp`): Local Whisper STT (:50090) and TTS synthesis (:50095).

*(Note: Cron management and ACP delegation are registered natively as in-process **Host Tools** in `omp_rpc` rather than external MCP subprocesses).*

---

## 1. Signal Messaging MCP Server (`signal_chat`)

Interacts with `signal-cli-rest-api` via the shared `mypai_tools.signal_client.SignalClient` SDK.

### 1.1 `get_next_unread_message`
- **Signature**: `get_next_unread_message(sender: str | None = None) -> dict[str, Any]`
- **Behavior**:
  - Fetches the single **oldest unread message** (FIFO order).
  - Automatically dispatches **Read Receipt** (`POST /v1/receipts`) $\rightarrow$ shows **two white checkmarks** 🗸🗸 on sender's app.
  - Automatically dispatches **Typing Indicator** (`POST /v1/typing-indicator`) $\rightarrow$ shows **"Typing..."** on sender's app.
  - **Attachment Handling**: Extracts attachment files from `signal-cli-rest-api`, saves them to `$PROJECT_DIR/scratch/signal_attachments/`, and returns resolved local file paths.
- **Return Schema**:
  ```json
  {
    "status": "success",
    "sender": "+15559992222",
    "message": "Here is the architectural diagram",
    "timestamp": 1723420000000,
    "attachments": [
      {
        "filename": "diagram.png",
        "content_type": "image/png",
        "file_path": "/home/user/project/scratch/signal_attachments/1723420000_diagram.png",
        "size_bytes": 1048576
      }
    ],
    "remaining_unread_count": 0
  }
  ```
  *(Returns `{"status": "empty", "message": "No unread Signal messages."}` when queue is empty).*

### 1.2 `send_signal_message`
- **Signature**: `send_signal_message(recipient: str, message: str, attachments: list[str] | None = None) -> dict[str, Any]`
- **Behavior**: Dispatches outbound message via `POST /v2/send`. Accepts local file paths in `attachments` list.
- **Return Schema**: `{"status": "sent", "recipient": "+15559992222", "attachments_sent": 1}`

### 1.3 `list_signal_chats`
- **Signature**: `list_signal_chats() -> dict[str, Any]`
- **Behavior**: Queries registered Signal contacts and group IDs via `GET /v1/contacts`.

---

## 2. Local Speech Processing MCP Server (`local-speech`)

- **`transcribe_audio(audio_path, language=None)`**: Transcribe audio via local Whisper STT server (`http://localhost:50090/v1/audio/transcriptions`).
- **`synthesize_speech(text, voice=None)`**: Synthesize speech audio via local TTS server (`http://localhost:50095/v1/audio/speech`).
