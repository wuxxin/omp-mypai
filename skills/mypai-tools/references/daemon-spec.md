# MyPAI Daemon Core Architecture Specification (`daemon-spec.md`)

## Executive Summary

The **MyPAI Daemon** (`mypai_tools.daemon`) is the central background coordinator, RPC session manager, and input serialization gateway for **MyPAI**. It refactors the legacy `heartbeat` process into a unified, high-performance asynchronous daemon running a **FastAPI** web server and **APScheduler** engine on port `52080`.

It maintains a persistent `omp --mode rpc --auto-approve --continue` connection to a single active session in a workspace directory (`workdir`) and serializes all incoming prompts from Signal webhooks, Input Spooler sidecars, FastMCP toolcalls (`cron_mcp`), scheduled Cron tasks, and an embedded WebUI.

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

## 2. Core Subsystems & Mechanisms

### 2.1 Prioritized Event Queue & Turn Serializer (`mypai_daemon.queue`)
* **Pattern**: Multi-Producer, Single-Consumer (MPSC) `asyncio.Queue`.
* **Purpose**: Prevents prompt turn interleaving and RPC socket locks when multiple events arrive simultaneously.
* **Priority Order**:
  1. `steer` & `abort_and_prompt` (High-priority user interrupt / abort).
  2. `webui` & `signal` (Interactive human turns).
  3. `cron` & `spooler` (Background automated tasks).

### 2.2 OMP Session Manager (`mypai_daemon.session_manager`)
* **RPC SDK**: Wraps `omp_rpc.RpcClient`.
* **Launch Arguments**: `omp --mode rpc --auto-approve --continue --cwd <project_dir>`.
* **Process Recovery**: Monitors PID via `proc.poll()`. On crash or broken pipe, cleans up old handles and automatically re-instantiates `RpcClient` with `--continue` in the configured workspace directory.
* **Session Actions Supported**: **`prompt`**, **`steer`**, **`followup`**, and **`abort_and_prompt`**.

---

## 3. Signal Entanglement & Shared SDK (`mypai_tools.signal_client`)

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

---

## 4. Sub-Specification Cross-Reference Matrix

For specific subsystem implementation details, schemas, and usage guides, refer to these reference documents:

| Component / Subsystem | Detailed Reference Document | Purpose |
| :--- | :--- | :--- |
| **REST & WebSocket API** | [daemon-api-spec.md](daemon-api-spec.md) | Endpoint specifications (`/api/v1/...`) supporting `prompt`, `steer`, `followup`, `abort_and_prompt`, & WebSocket stream (`/api/v1/ws`) |
| **Embedded WebUI** | [web-ui-spec.md](web-ui-spec.md) | Single-Page Application design, WebSocket transcript stream, prompt/steer input box, & cron dashboard |
| **Cron Task Scheduler** | [scheduler-usage.md](scheduler-usage.md) | Cron expression syntax, `@now` triggers, job engines (`omp`, `http`, `shell`, `python`), telemetry macros, & SQLite schema |
| **FastMCP Tool Servers** | [mcp-spec.md](mcp-spec.md) | FastMCP tool signatures & return schemas for `chat-channel`, `cron-scheduler`, and `local-speech` |
| **Input Spooler Sidecar** | [input_spooler.md](input_spooler.md) | Inbox directory watcher, STT pipeline, Hindsight memory retention, & `mypai_daemon` REST notifications |
| **Pytest Architecture** | [daemon-testing.md](daemon-testing.md) | Hermetic test suite structure, fixtures (`FakeRpcClient`, `in_memory_db`), and test coverage matrix |
| **CLI Command Usage** | [cli-usage.md](cli-usage.md) | Command line options (`--project-dir`, `--port`, `--once`, `import`, `export`, `pytest`) |