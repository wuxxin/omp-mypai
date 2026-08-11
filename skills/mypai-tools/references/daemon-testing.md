# MyPAI Daemon Test Architecture & Pytest Suite Specification (`daemon-testing.md`)

## 1. Future Roadmap: Integration, E2E & Advanced Robustness Targets

> [!TIP]
> **Next-Phase Followup Implementation Targets**:
> 1. **Live Process E2E Integration Suite**:
>    - Launch real `mypai_daemon` daemon background process (`python3 -m mypai_tools.daemon --port 52089 --session-name mypai-e2e`).
>    - Spawn an actual `omp --mode rpc` headless binary in scratch directory, send REST prompts to `/api/v1/session/prompt`, and poll for completion via WebSocket `/api/v1/ws`.
> 2. **Signal REST API Mock Server Integration**:
>    - Build a standalone mock `signal-cli-rest-api` HTTP server running on port `50899` to test live multipart attachments upload/download and 2-checkmark receipt delivery without mock monkeypatching.
> 3. **Chaos & Resiliency Testing**:
>    - **Database Lock Contention**: Simulate multiple parallel threads writing to `cron-<hash>.db` simultaneously under WAL mode (`PRAGMA journal_mode=WAL`).
>    - **RPC Process SIGKILL Recovery**: Issue `kill -9` on the underlying `RpcClient` PID mid-turn, verify automatic session recovery via `--continue --session <MYPAI_SESSION_NAME>` without dropping queue items.
>    - **Network Disconnect & Reconnect**: Test WebSocket `/api/v1/ws` automatic reconnect and state re-synchronization on transient network drops.
> 4. **Headless Browser E2E UI Automation**:
>    - Automated Playwright/Puppeteer UI test suite validating WebUI (`index.html`) prompt submit, mode selector (`steer`, `followup`, `abort_and_prompt`), live transcript console rendering, and cron task manager buttons.

---

## 2. Executive Summary & Implemented Test Suite

The test suite for `mypai_daemon` and `mypai_tools` is located at `submodules/omp-mypai/tools/tests/`. It uses a **Fast, Hermetic, Mock-Based Architecture** (`pytest` + `fastapi.testclient.TestClient` + `FakeRpcClient` + `in_memory_db`). 

It requires **zero external services** (no live LLM, no running `signal-cli`, no SQLite disk locks) and executes the **entire 46-test suite in ~1 second**.

---

## 3. Implemented Test Directory Structure

```
submodules/omp-mypai/tools/tests/
├── conftest.py                       # Fixtures: in_memory_db, FakeRpcClient, test_client, signal_client
├── test_queue.py                     # MPSC EventQueue serialization & priority ordering (0: steer/abort, 1: webui/signal, 2: cron/spooler)
├── test_session_manager.py           # OMPSessionManager fixed session name, 4 action modes (prompt, steer, followup, abort_and_prompt)
├── test_scheduler.py                 # APScheduler, 5-field cron normalization, DateTrigger 'now'
├── test_api_session.py               # REST API /api/v1/session/* (/prompt, /steer, /followup, /abort_and_prompt, /status)
├── test_api_cron.py                  # REST API /api/v1/cron/* (CRUD, enable, disable, run_once)
├── test_api_webhook.py               # REST API /api/v1/signal/webhook & SIGNAL_ALLOWED_SENDER whitelist filter
├── test_websocket.py                 # WebSocket stream /api/v1/ws & ping/pong
├── test_signal_client.py             # SignalClient whitelist check
├── test_signal_client_extended.py    # SignalClient read receipts (🗸🗸), typing indicator, send message, fetch unread
├── test_chat_mcp.py                  # chat-channel FastMCP tools (get_next_unread_message, send_signal_message, list_signal_chats)
├── test_input_spooler_daemon_notify.py # InputSpooler notify_daemon REST prompt dispatch
├── test_webui.py                     # Embedded WebUI static HTML routes (/ui and /)
├── test_fault_tolerance.py          # RPC socket crash recovery & multi-part attachment extraction to scratch/signal_attachments/
├── test_coverage_boost.py           # Content SHA256 hashing, sidecar .md parsing, state file persistence, daemon CLI --once flag
├── test_executors_and_spooler.py     # http_executor, python_executor, omp_rpc_executor, transcribe_audio, retain_hindsight
└── test_deep_robustness.py           # Multi-producer concurrent queue stress test, database telemetry, shell error template macro substitution
```

---

## 4. Test Fixtures (`conftest.py`)

* **`in_memory_db`**: Isolated SQLite database using `sqlite:///:memory:` for rapid DB assertions.
* **`FakeRpcClient`**: Stub class implementing `omp_rpc.RpcClient` methods (`start`, `stop`, `prompt`, `steer`, `followup`, `follow_up`, `prompt_and_wait`, `abort_and_prompt`), capturing sent prompts and supplying pid telemetry without spawning LLM processes.
* **`test_client`**: Instantiates `fastapi.testclient.TestClient(app)` with `FakeRpcClient` and `in_memory_db` injected into `mypai_daemon`.
* **`signal_client`**: Instantiates `SignalClient` configured with test account (`+15550001111`) and whitelisted sender (`+15559992222`).

---

## 5. Test Suite Coverage Matrix

### 5.1 `test_queue.py` & `test_deep_robustness.py` (Queue & Multi-Producer Stress)
- `test_queue_enqueue_and_priority`: Enqueues turns from `webui`, `signal`, `cron`, and `steer`. Asserts priority ordering (0 > 1 > 2).
- `test_queue_concurrent_multi_producers`: Launches 4 concurrent `asyncio` producer tasks pushing 35 turns simultaneously. Asserts zero race conditions and correct prioritization.

### 5.2 `test_session_manager.py` & `test_fault_tolerance.py` (RPC Lifecycle & Resiliency)
- `test_session_manager_fixed_session`: Asserts `OMPSessionManager` initializes `RpcClient` with `extra_args=["--auto-approve", "--continue", "--session", session_name]`.
- `test_session_manager_fault_recovery`: Simulates a process crash / socket exception (`ConnectionResetError`). Asserts session manager captures fault, reconnects session, and resumes turn execution.

### 5.3 `test_scheduler.py` & `test_deep_robustness.py` (Scheduler & Telemetry)
- `test_cron_normalization`: Verifies day-of-week remapping for standard Unix cron syntax (`0 8 * * 0` $\rightarrow$ `0 8 * * 6`).
- `test_scheduler_telemetry_and_oneshot`: Schedules a task with `cron="now"`. Asserts execution updates DB telemetry (`total_calls`, `last_runtime`, `last_returncode`, `last_output`) and sets `enabled=False`.

### 5.4 `test_api_session.py`, `test_api_cron.py` & `test_webui.py` (REST API & WebUI)
- `test_session_*_endpoint`: Tests `/api/v1/session/prompt`, `/steer`, `/followup`, `/abort_and_prompt`, and `/status`.
- `test_cron_jobs_crud`: Tests `GET`, `POST`, `PUT`, `DELETE`, `/enable`, `/disable`, and `/run_once`.
- `test_webui_*_endpoint`: Validates static HTML dashboard rendering on `/ui` and `/`.

### 5.5 `test_api_webhook.py`, `test_signal_client_extended.py` & `test_fault_tolerance.py` (Signal & Visual Feedback)
- `test_signal_webhook_authorized_sender`: Accepts whitelisted sender `+15559992222`.
- `test_signal_webhook_unauthorized_sender`: Rejects and drops incoming webhook from unauthorized number `+19990000000`.
- `test_signal_client_send_read_receipt_and_typing`: Verifies `POST /v1/receipts` (read receipt 🗸🗸) and `POST /v1/typing-indicator` dispatches.
- `test_signal_client_attachment_extraction`: Verifies multi-part media attachments copy to `$PROJECT_DIR/scratch/signal_attachments/`.
