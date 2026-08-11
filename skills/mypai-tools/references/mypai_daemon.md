# MyPAI Daemon Architectural Specification (`mypai_daemon.md`)

## Executive Summary

The **MyPAI Daemon** (`mypai_tools.daemon`) is the central background coordinator, RPC session manager, cron engine, and input serialization gateway for **MyPAI**. It refactors and subsumes the former `heartbeat` process into a unified, high-performance asynchronous daemon. 

`mypai_daemon` maintains a persistent `omp --mode rpc` connection to a single active session in a project workspace (`workdir`). It aggregates, prioritizes, and serializes incoming prompts and triggers from multiple producers—including **Signal** messaging webhooks, **Input Spooler** sidecar events, **FastMCP** tools (`cron_mcp`), scheduled **Cron** tasks, and an embedded **Single-Page WebUI**—into a single-threaded execution queue for the active `omp` session.

---

## 1. System Architecture & Component Diagram

```
+-----------------------------------------------------------------------------------+
|                                Input Event Sources                                |
|  +--------------------+  +--------------------+  +------------+  +-----------------+  |
|  | signal-cli Webhook |  | Input Spooler      |  | cron_mcp   |  | WebUI Browser   |  |
|  +---------+----------+  +---------+----------+  +-----+------+  +--------+--------+  |
+------------|-----------------------|-------------------|------------------|-------+
             |                       |                   |                  |
             v                       v                   v                  v
+-----------------------------------------------------------------------------------+
|                        mypai_daemon Core Process (Port 52080)                     |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | FastAPI REST Web Server & WebSocket Engine (/api/v1)                        |  |
|  +-------------------------------------+---------------------------------------+  |
|                                        |                                          |
|                                        v                                          |
|  +-----------------------------------------------------------------------------+  |
|  | Prioritized Event Queue & Serializer (Multi-Producer, Single-Consumer)        |  |
|  +-------------------------------------+---------------------------------------+  |
|                                        |                                          |
|                                        v                                          |
|  +-----------------------+   +---------+--------------+   +--------------------+  |
|  | APScheduler Engine    |   | OMP RPC Session Manager|   | Embedded WebUI     |  |
|  | (cron-<hash>.db)      |   | (Auto-Reconnect/Ping) |   | (Glassmorphism SPA)|  |
|  +-----------------------+   +---------+--------------+   +--------------------+  |
+----------------------------------------|------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                      Target Workdir OMP Session Execution                         |
|  +-----------------------------------------------------------------------------+  |
|  | omp --mode rpc --auto-approve --continue                                    |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

---

## 2. Core Responsibilities & Functional Features

1. **Persistent OMP RPC Session Management**:
   - Manages a continuous `omp --mode rpc` background process attached to a single target workspace directory (`project_dir`).
   - Installs `install_headless_ui()` for prompt monitoring.
   - Monitors process health and automatically recovers from lost connections or crashes by re-instantiating `RpcClient` with `--continue` and exponential backoff retry.

2. **Prioritized Event Queue & Serialization**:
   - Implements an `asyncio.Queue` (Multi-Producer, Single-Consumer) that serializes all prompt injections into `omp_rpc`.
   - Prevents turn interleaving and RPC socket locks when multiple events arrive simultaneously.

3. **Central REST API & WebSocket Server (FastAPI + Uvicorn)**:
   - Exposes clean REST endpoints (`/api/v1/...`) for session prompting, steering, status queries, cron management, and Signal webhooks.
   - Streams real-time session logs, agent responses, and telemetry to the WebUI over WebSockets (`/api/v1/ws`).

4. **APScheduler Version-Aware Cron Engine**:
   - Manages task schedules stored in `$HOME/.omp/cron/cron-<project_hash>.db` (SQLite with WAL mode enabled).
   - Supports 5-field Unix cron syntax (normalizing Sunday `0` to `6` for APScheduler < 4.0 compatibility) and one-shot `@now` triggers (`DateTrigger`).
   - Automatically records execution duration, return codes, output snippets, and call counts in SQLite.

5. **Signal Entanglement & Webhook Gateway**:
   - Receives instant `POST /api/v1/signal/webhook` notifications from `signal-cli-rest-api`.
   - Injects a lightweight notification prompt into the session:  
     `"NEW Signal message received from {sender}. Read using chat_mcp."`
   - Relies on `chat_mcp` to perform the actual message fetching, trigger **Read Receipts** (two checkmarks), and issue **Typing Indicators** via a shared `mypai_tools.signal_client` SDK.

6. **Embedded Single-Page WebUI**:
   - Serves an embedded, responsive glassmorphism web application directly from `/ui` or `/`.
   - Displays real-time session status, log output streams, execution stats, an interactive prompt/steer input box, and a full cron scheduler management dashboard.

---

## 3. REST API Endpoint Specifications

All endpoints are hosted on `http://127.0.0.1:52080` under `/api/v1`.

### 3.1 Session Management Endpoints

* **`POST /api/v1/session/prompt`**
  - **Description**: Queue a new prompt turn into the OMP session.
  - **Request Body**:
    ```json
    {
      "prompt": "Review the test coverage report",
      "mode": "prompt",
      "source": "webui",
      "context": {}
    }
    ```
  - **Response**: `{"status": "queued", "task_id": "evt_8a9b1c2d"}`

* **`POST /api/v1/session/steer`**
  - **Description**: Inject a high-priority steering interrupt into the active OMP turn.
  - **Request Body**: `{"prompt": "Stop current command and output summary"}`
  - **Response**: `{"status": "steered", "task_id": "evt_3f2e1d"}`

* **`GET /api/v1/session/status`**
  - **Description**: Return current session connection state, RPC health, active task, and uptime.
  - **Response**:
    ```json
    {
      "status": "connected",
      "pid": 12345,
      "project_dir": "/home/user/project",
      "is_busy": false,
      "queue_depth": 0,
      "uptime_sec": 3600.5
    }
    ```

* **`GET /api/v1/session/history`**
  - **Description**: Get recent turn history and telemetry logs.

---

### 3.2 Cron & Scheduler Endpoints

* **`GET /api/v1/cron/jobs`**
  - **Description**: List all registered cron jobs and execution telemetry.
  - **Query Params**: `include_disabled=true`

* **`POST /api/v1/cron/jobs`**
  - **Description**: Register a new scheduled cron job.
  - **Request Body**:
    ```json
    {
      "name": "Nightly Audit",
      "cron": "0 3 * * *",
      "kind": "shell",
      "action": "python3 scripts/audit.py",
      "result_action": "prompt",
      "result_prompt": "Audit finished: #[_OUTPUT]"
    }
    ```

* **`PUT /api/v1/cron/jobs/{job_id}`**: Modify job parameters.
* **`DELETE /api/v1/cron/jobs/{job_id}`**: Remove job from SQLite database.
* **`POST /api/v1/cron/jobs/{job_id}/enable`**: Enable job.
* **`POST /api/v1/cron/jobs/{job_id}/disable`**: Disable job.
* **`POST /api/v1/cron/jobs/run_once`**: Queue an immediate one-shot (`now`) job.
* **`POST /api/v1/cron/import`**: Import cron jobs from JSON payload/file.
* **`GET /api/v1/cron/export`**: Export all registered cron jobs to JSON format.

---

### 3.3 Signal Webhook Endpoint

* **`POST /api/v1/signal/webhook`**
  - **Description**: Webhook target for `signal-cli-rest-api`.
  - **Request Body**: Raw JSON payload from `signal-cli-rest-api` containing envelope metadata.
  - **Behavior**: Extracts sender phone number/UUID, enqueues turn notification `"NEW Signal message received from {sender}. Read with chat_mcp."` into the Event Queue, and returns `{"status": "acknowledged"}`.

---

### 3.4 Real-time WebSocket Endpoint

* **`WS /api/v1/ws`**
  - **Description**: Bi-directional WebSocket stream for WebUI clients.
  - **Server Events Emitted**: `session_state_change`, `turn_started`, `turn_completed`, `log_line`, `cron_executed`.
  - **Client Messages Handled**: `{"action": "ping"}`, `{"action": "submit_prompt", "prompt": "..."}`.

---

## 4. Integration Specs for Sidecars & MCP Tool Servers

### 4.1 `chat_mcp` FastMCP Tool Server

The `chat-channel` FastMCP server exposes 3 core tools for Signal messaging interaction. It uses the shared SDK `mypai_tools.signal_client.SignalClient`.

#### 1. `get_next_unread_message`
- **Signature**: `get_next_unread_message(sender: str | None = None) -> dict[str, Any]`
- **Behavior**:
  - Fetches the single **oldest unread message** (FIFO order) from `signal-cli-rest-api`.
  - Automatically dispatches **Read Receipt** (`POST /v1/receipts`) $\rightarrow$ shows **two white checkmarks** 🗸🗸 on sender's app.
  - Automatically dispatches **Typing Indicator** (`POST /v1/typing-indicator`) $\rightarrow$ shows **"Typing..."** on sender's app.
  - **Attachment Handling (Incoming)**: Automatically extracts attachment files from `signal-cli-rest-api`, saves them to `$PROJECT_DIR/scratch/signal_attachments/`, and returns resolved local file paths and MIME metadata. *(No separate download tool call required; prevents base64 token bloat in LLM context).*
- **Return Schema**:
  ```json
  {
    "status": "success",
    "sender": "+15559992222",
    "message": "Here is the architectural diagram and audio note",
    "timestamp": 1723420000000,
    "attachments": [
      {
        "filename": "diagram.png",
        "content_type": "image/png",
        "file_path": "/home/user/project/scratch/signal_attachments/1723420000_diagram.png",
        "size_bytes": 1048576
      },
      {
        "filename": "voicenote.ogg",
        "content_type": "audio/ogg",
        "file_path": "/home/user/project/scratch/signal_attachments/1723420000_voicenote.ogg",
        "size_bytes": 256000
      }
    ],
    "remaining_unread_count": 0
  }
  ```
  *(Returns `{"status": "empty", "message": "No unread Signal messages."}` when queue is empty).*

#### 2. `send_signal_message`
- **Signature**: `send_signal_message(recipient: str, message: str, attachments: list[str] | None = None) -> dict[str, Any]`
- **Behavior**: 
  - Dispatches outbound message via `POST /v2/send`.
  - **Attachment Handling (Outgoing)**: Accepts a list of local file paths (e.g. `["scratch/chart.png", "docs/report.pdf"]`). `chat_mcp` validates local file existence, encodes them into base64 payloads required by `signal-cli-rest-api`, and dispatches the payload.
- **Return Schema**: `{"status": "sent", "recipient": "+15559992222", "attachments_sent": 1}`

#### 3. `list_signal_chats`
- **Signature**: `list_signal_chats() -> dict[str, Any]`
- **Behavior**: Queries registered Signal contacts and group IDs via `GET /v1/contacts`.

---

### 4.2 `cron_mcp` FastMCP Tool Server

The `cron-scheduler` FastMCP server exposes 9 tools for scheduling tasks. `cron_mcp` no longer opens SQLite DB sessions directly; all tool calls execute HTTP requests targeting `mypai_daemon` REST API (`http://127.0.0.1:52080/api/v1/cron/...`).

1. **`cron_add_job(name, cron, kind='omp', action='prompt', url='', args=None, kwargs=None, result_prompt='', result_error_prompt='', result_action='ignore', result_channel='')`**: Calls `POST /api/v1/cron/jobs`.
2. **`cron_run_once(name, kind='omp', action='prompt', url='', args=None, kwargs=None, result_prompt='', result_error_prompt='', result_action='ignore', result_channel='')`**: Calls `POST /api/v1/cron/jobs/run_once`. Schedules or updates task for immediate execution (`cron="now"`).
3. **`cron_list_jobs(include_disabled=True)`**: Calls `GET /api/v1/cron/jobs`.
4. **`cron_disable_job(job_id)`**: Calls `POST /api/v1/cron/jobs/{job_id}/disable`.
5. **`cron_enable_job(job_id)`**: Calls `POST /api/v1/cron/jobs/{job_id}/enable`.
6. **`cron_modify_job(job_id, ...)`**: Calls `PUT /api/v1/cron/jobs/{job_id}`.
7. **`cron_remove_job(job_id)`**: Calls `DELETE /api/v1/cron/jobs/{job_id}`.
8. **`cron_import_jobs(file_path)`**: Reads JSON file and calls `POST /api/v1/cron/import`.
9. **`cron_export_jobs(file_path)`**: Calls `GET /api/v1/cron/export` and writes JSON file.

---

### 4.3 `input_spooler` Sidecar Integration
`input_spooler.py` retains its independent inbox file watching (`~/Recordings/Inbox`), Whisper STT transcription, and Hindsight memory retention logic. Once processing is complete, it calls `POST http://127.0.0.1:52080/api/v1/session/prompt` to queue a notification turn into `mypai_daemon`.

### 4.4 Shared `mypai_tools.signal_client` Module SDK

A shared Python SDK module `mypai_tools.signal_client.SignalClient` wraps all HTTP communication with `signal-cli-rest-api`. Both `mypai_daemon` and `chat_mcp` import and use this SDK:

```python
# mypai_tools/signal_client.py

class SignalClient:
    def __init__(self, api_url: str = "http://localhost:50889", account: str = ""):
        self.api_url = api_url
        self.account = account

    def fetch_next_unread_message(
        self, sender: str | None = None, attachment_dir: str | None = None
    ) -> dict | None:
        """Fetch oldest unread message, send read receipt (2 checkmarks) & typing indicator, 
        and extract attachments to local disk."""
        ...

    def fetch_unread_messages(self, limit: int = 10) -> list[dict]:
        """Fetch pending/unread Signal messages from signal-cli-rest-api."""
        ...

    def send_read_receipt(self, recipient: str, timestamps: list[int]) -> dict:
        """Send POST /v1/receipts/<account> to show two white checkmarks 🗸🗸."""
        ...

    def send_typing_indicator(self, recipient: str) -> dict:
        """Send POST /v1/typing-indicator/<account> to show 'Typing...' status."""
        ...

    def send_message(
        self, recipient: str, text: str, attachments: list[str] | None = None
    ) -> dict:
        """Encode local file attachments to base64 and dispatch outbound message via POST /v2/send."""
        ...

    def list_chats(self) -> dict:
        """Fetch registered contacts and group IDs via GET /v1/contacts."""
        ...
```

#### How `chat_mcp` Uses `SignalClient`:
All FastMCP tools in `chat_mcp` delegate directly to `SignalClient` methods:
- `chat_mcp.get_next_unread_message` $\rightarrow$ calls `SignalClient.fetch_next_unread_message(...)`
- `chat_mcp.send_signal_message` $\rightarrow$ calls `SignalClient.send_message(...)`
- `chat_mcp.list_signal_chats` $\rightarrow$ calls `SignalClient.list_chats()`

---

## 5. Comprehensive Unit & Integration Test Specification (Option A)

The test suite uses a **Fast, Hermetic, Mock-Based Architecture** (Pytest + `FastAPI.testclient` + `httpx.MockTransport` + `FakeRpcClient`). It requires **zero external services** running during test execution and runs in under 2 seconds.

### 5.1 Test Directory Structure

```
submodules/omp-mypai/tools/tests/
├── conftest.py                # Fixtures: in_memory_db, fake_rpc_client, test_client, mock_signal_api
├── test_queue.py              # Test EventQueue serialization & prioritization
├── test_session_manager.py    # Test OMPSessionManager RPC lifecycle & auto-reconnect
├── test_scheduler.py          # Test APScheduler, cron normalization, and DateTrigger 'now'
├── test_api_session.py        # Test /api/v1/session/* endpoints (prompt, steer, status, history)
├── test_api_cron.py           # Test /api/v1/cron/* endpoints (CRUD, enable, disable, run_once, import/export)
├── test_api_webhook.py        # Test /api/v1/signal/webhook endpoint & event queue dispatch
├── test_websocket.py          # Test /api/v1/ws WebSocket connection, log streaming, ping/pong
├── test_signal_client.py      # Test signal_client (read receipt 🗸🗸, typing indicator, fetch/send)
├── test_cron_mcp.py           # Test cron_mcp HTTP REST toolcalls
└── test_input_spooler.py      # Test input_spooler HTTP REST notifications
```

---

### 5.2 Test Fixtures (`conftest.py`)

* **`in_memory_db`**: Creates an isolated SQLite database using `sqlite:///:memory:` for rapid DB assertions.
* **`fake_rpc_client`**: A lightweight stub class implementing `omp_rpc.RpcClient` methods (`start`, `stop`, `prompt`, `steer`), capturing sent prompts in an internal list.
* **`test_client`**: Instantiates `fastapi.testclient.TestClient(app)` with `fake_rpc_client` and `in_memory_db` injected into `mypai_daemon`.
* **`mock_signal_api`**: Intercepts HTTP requests using `httpx.MockTransport` or `respx` to stub `signal-cli-rest-api` endpoints (`/v1/receive`, `/v1/receipts`, `/v1/typing-indicator`, `/v2/send`).

---

### 5.3 Test Suite Coverage Matrix

#### 1. `test_queue.py` (Queue Serialization & Priority)
- `test_queue_serial_execution`: Enqueues 5 prompt tasks simultaneously from different sources. Asserts that tasks complete strictly sequentially in 1-by-1 order.
- `test_queue_steer_priority`: Enqueues a normal prompt followed by a high-priority steer event. Asserts that the steer interrupt is prioritized.

#### 2. `test_session_manager.py` (RPC Client Lifecycle & Recovery)
- `test_rpc_connection_start`: Asserts `OMPSessionManager` correctly initializes `RpcClient` with `extra_args=["--auto-approve", "--continue"]`.
- `test_rpc_auto_reconnect_on_crash`: Simulates a process death (`proc.poll() == 1`). Asserts `ensure_connected()` detects the failure, cleans up old handles, and successfully reconnects with `--continue`.

#### 3. `test_scheduler.py` (APScheduler & DB Normalization)
- `test_cron_expression_normalization`: Verifies day-of-week remapping for standard Unix cron syntax (`0 8 * * 0` -> Sunday).
- `test_one_shot_now_trigger`: Schedules a task with `cron="now"`. Asserts it executes immediately via `DateTrigger`, updates DB telemetry (`total_calls`, `last_runtime`), and sets `enabled=False`.

#### 4. `test_api_session.py` (Session REST API Coverage)
- `test_post_prompt_success`: `POST /api/v1/session/prompt` returns `HTTP 200` with `status: queued` and valid `task_id`.
- `test_post_steer_success`: `POST /api/v1/session/steer` returns `HTTP 200`.
- `test_get_status`: `GET /api/v1/session/status` returns current connection state, PID, queue depth, and uptime.
- `test_invalid_prompt_payload`: `POST /api/v1/session/prompt` with missing `prompt` field returns `HTTP 422` validation error.

#### 5. `test_api_cron.py` (Cron REST API Coverage)
- `test_cron_list_jobs`: `GET /api/v1/cron/jobs` returns JSON list of active jobs.
- `test_cron_add_job`: `POST /api/v1/cron/jobs` creates entry in SQLite DB and schedules task.
- `test_cron_modify_and_delete`: Tests `PUT /api/v1/cron/jobs/{id}` and `DELETE /api/v1/cron/jobs/{id}`.
- `test_cron_enable_disable`: Tests `/enable` and `/disable` endpoints.
- `test_cron_run_once`: `POST /api/v1/cron/jobs/run_once` reschedules matching task or creates one-shot entry.
- `test_cron_import_export`: Validates importing/exporting JSON cron job arrays.

#### 6. `test_api_webhook.py` (Signal Webhook & Integration)
- `test_signal_webhook_dispatches_event`: Sends mock `POST /api/v1/signal/webhook` payload. Asserts notification prompt `"NEW Signal message received from..."` is pushed to Event Queue.

#### 7. `test_websocket.py` (WebSocket Streaming)
- `test_websocket_connect_and_ping`: Establishes WS connection to `/api/v1/ws`, sends `{"action": "ping"}`, asserts receiving `{"event": "pong"}`.
- `test_websocket_log_broadcast`: Triggers a session prompt and asserts log events are pushed down the WebSocket stream.

#### 8. `test_signal_client.py` (Visual Feedback & Signal SDK)
- `test_chat_mcp_triggers_read_and_typing`: Calls `chat_mcp.get_next_unread_message("sender")`. Asserts that mock HTTP transport recorded `POST /v1/receipts` (read receipt 🗸🗸) and `POST /v1/typing-indicator` before returning the single message payload.
- `test_chat_mcp_empty_queue`: Asserts `get_next_unread_message()` returns `{"status": "empty"}` when no messages remain.
- `test_send_signal_message`: Asserts `send_signal_message("recipient", "text")` dispatches `POST /v2/send`.

---

## 6. CLI Command Usage

```bash
# Start mypai_daemon in continuous background mode (default port 52080)
python3 -m mypai_tools.daemon [--project-dir /path/to/project] [--port 52080]

# Run daemon single-pass execution (executes pending jobs and exits)
python3 -m mypai_tools.daemon --once [--project-dir /path/to/project]

# Import/Export cron configuration via CLI
python3 -m mypai_tools.daemon import /path/to/jobs.json
python3 -m mypai_tools.daemon export /path/to/jobs_export.json

# Execute complete Pytest suite (Mock-based, fast execution)
pytest submodules/omp-mypai/tools/tests/ -v
```
