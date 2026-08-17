# ACP Intra-Agent Tool Specification (`acp-tool-spec.md`)

This document details the architectural specification for the **ACP (Agent Control Protocol)** intra-agent task delegation engine, SQLite state management, custom host tools, and REST API endpoints in `mypai_tools.acp` and `mypai_daemon`.

---

## 1. Asynchronous Delegation Architecture

The ACP task delegation system enables the primary `mypai_daemon` agent (`omp --mode rpc`) to dispatch asynchronous subagent tasks to worker processes (`omp --mode acp`) running in target workspace directories without blocking the main agent.

- **Zero Synchronous RPC / ACP Calls**: All ACP task dispatches are purely asynchronous (`acp_task_async`), returning a `task_id` immediately.
- **Background Execution**: Worker processes execute concurrently in the Background Execution Plane.
- **Completion Ingestion**: When an async ACP subagent finishes, its results are logged in the ACP task store and, if a result action is configured, enqueued into the **Turn Queue** with `is_result_call=True`.

---

## 2. Injected Subagent Host Tools (`mypai_tools.acp.tools`)

Registered into `omp_rpc.RpcClient` via `set_custom_tools()`:

| Host Tool Name | Parameter Schema | Description & Functionality |
| :--- | :--- | :--- |
| **`acp_task_async`** | `cwd: str, prompt: str, agent_profile: str = ""` | Dispatches asynchronous background task turn and returns `task_id` immediately. |
| **`acp_task_status`** | `task_id: str = ""` | Checks status, progress, and telemetry of running or completed ACP tasks. |
| **`acp_task_result`** | `task_id: str` | Retrieves final text output and token statistics for a completed `task_id`. |
| **`acp_task_steer`** | `task_id: str, guidance: str` | Injects mid-turn guidance into a running ACP worker turn. |
| **`acp_task_cancel`** | `task_id: str` | Aborts/cancels an active ACP worker task. |
| **`acp_list_agents`** | *(none)* | Lists active ACP worker processes, workspace directories, and session PIDs. |
| **`acp_inspect_session`**| `session_id: str` | Inspects transcript history for a target ACP session ID. |

---

## 3. SQLite State Persistence & REST Control API

### State Management (`AcpState`)
* Key name: `"acp_execution_state"` saved in `SettingsModel` (SQLite).
* Values: `"running"` (default) or `"suspended"`.
* When state is `"suspended"`, all `@host_tool` functions return:
  `{"status": "error", "error": "ACP delegation is currently suspended in daemon configuration."}`.

### REST API Endpoints (`mypai_tools.daemon.api.acp_router`)

* **`GET /api/v1/acp/status`**: Get current state (`running` vs `suspended`), active worker child PIDs, task queue depth, and memory telemetry.
* **`POST /api/v1/acp/enable`**: Enable ACP execution state in SQLite settings and broadcast WebSocket event `acp_state_changed`.
* **`POST /api/v1/acp/suspend`** / **`POST /api/v1/acp/disable`**: Suspend ACP execution state in SQLite settings.
* **`POST /api/v1/acp/shutdown`**: Stop worker processes and clear pool.
* **`POST /api/v1/acp/restart`**: Restart worker process pool.
