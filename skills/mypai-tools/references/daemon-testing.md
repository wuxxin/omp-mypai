# MyPAI Daemon Test Architecture & Pytest Suite Specification (`daemon-testing.md`)

## Executive Summary

The test suite for `mypai_daemon` and `mypai_tools` is located at `submodules/omp-mypai/tools/tests/`. It uses a **Fast, Hermetic, Mock-Based Architecture** (Pytest + `FastAPI.testclient` + `httpx.MockTransport` + `FakeRpcClient` + `in_memory_db`). 

It requires **zero external services** (no live LLM, no running `signal-cli`, no SQLite disk locks) and executes the entire suite in under 2 seconds.

---

## 1. Test Suite Directory Structure

```
submodules/omp-mypai/tools/tests/
├── conftest.py                # Fixtures: in_memory_db, fake_rpc_client, test_client, mock_signal_api
├── test_queue.py              # Test EventQueue serialization & priority ordering
├── test_session_manager.py    # Test OMPSessionManager RPC lifecycle & auto-reconnect
├── test_scheduler.py          # Test APScheduler, cron normalization, and DateTrigger 'now'
├── test_api_session.py        # Test /api/v1/session/* endpoints (prompt, steer, followup, abort_and_prompt, status)
├── test_api_cron.py           # Test /api/v1/cron/* endpoints (CRUD, enable, disable, run_once, import/export)
├── test_api_webhook.py        # Test /api/v1/signal/webhook endpoint & turn queue dispatch
├── test_websocket.py          # Test /api/v1/ws WebSocket connection, log streaming, ping/pong
├── test_signal_client.py      # Test signal_client (read receipt 🗸🗸, typing indicator, fetch/send)
├── test_cron_mcp.py           # Test cron_mcp HTTP REST toolcalls
└── test_input_spooler.py      # Test input_spooler HTTP REST notifications
```

---

## 2. Test Fixtures (`conftest.py`)

* **`in_memory_db`**: Creates an isolated SQLite database using `sqlite:///:memory:` for rapid DB assertions.
* **`fake_rpc_client`**: A lightweight stub class implementing `omp_rpc.RpcClient` methods (`start`, `stop`, `prompt`, `steer`), capturing sent prompts in an internal list without spawning LLM processes.
* **`test_client`**: Instantiates `fastapi.testclient.TestClient(app)` with `fake_rpc_client` and `in_memory_db` injected into `mypai_daemon`.
* **`mock_signal_api`**: Intercepts HTTP requests using `httpx.MockTransport` or `respx` to stub `signal-cli-rest-api` endpoints (`/v1/receive`, `/v1/receipts`, `/v1/typing-indicator`, `/v2/send`).

---

## 3. Test Suite Coverage Matrix

### 3.1 `test_queue.py` (Queue Serialization & Priority)
- `test_queue_serial_execution`: Enqueues 5 prompt tasks simultaneously. Asserts tasks complete strictly sequentially.
- `test_queue_steer_priority`: Enqueues a normal prompt followed by a high-priority steer event. Asserts the steer interrupt is prioritized.

### 3.2 `test_session_manager.py` (RPC Client Lifecycle & Recovery)
- `test_rpc_connection_start`: Asserts `OMPSessionManager` initializes `RpcClient` with `extra_args=["--auto-approve", "--continue"]`.
- `test_rpc_auto_reconnect_on_crash`: Simulates a process death (`proc.poll() == 1`). Asserts `ensure_connected()` detects failure, cleans up old handles, and re-instantiates `RpcClient` with `--continue`.

### 3.3 `test_scheduler.py` (APScheduler & DB Normalization)
- `test_cron_expression_normalization`: Verifies day-of-week remapping for standard Unix cron syntax (`0 8 * * 0` $\rightarrow$ Sunday).
- `test_one_shot_now_trigger`: Schedules a task with `cron="now"`. Asserts it executes immediately via `DateTrigger`, updates DB telemetry (`total_calls`, `last_runtime`), and sets `enabled=False`.

### 3.4 `test_api_session.py` (Session REST API Coverage)
- `test_post_prompt_success`: `POST /api/v1/session/prompt` returns `HTTP 200` with `status: queued`.
- `test_post_steer_success`: `POST /api/v1/session/steer` returns `HTTP 200` with `status: steered`.
- `test_post_followup_success`: `POST /api/v1/session/followup` returns `HTTP 200`.
- `test_post_abort_and_prompt_success`: `POST /api/v1/session/abort_and_prompt` returns `HTTP 200`.
- `test_get_status`: `GET /api/v1/session/status` returns connection state, PID, queue depth, and uptime.

### 3.5 `test_api_cron.py` (Cron REST API Coverage)
- `test_cron_crud`: Tests `GET`, `POST`, `PUT`, `DELETE`, `/enable`, `/disable`, `/run_once`, and `/import`/`/export`.

### 3.6 `test_signal_client.py` (Visual Feedback & Signal SDK)
- `test_chat_mcp_triggers_read_and_typing`: Calls `chat_mcp.get_next_unread_message("sender")`. Asserts mock HTTP transport recorded `POST /v1/receipts` (read receipt 🗸🗸) and `POST /v1/typing-indicator` before returning message payload.
- `test_chat_mcp_empty_queue`: Asserts `get_next_unread_message()` returns `{"status": "empty"}` when queue is empty.
