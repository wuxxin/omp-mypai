# ACP Intra-Agent Tool Specification (`acp-tool-spec.md`)

This document details the architectural specification for the **ACP (Agent Control Protocol)** intra-agent task delegation engine, SQLite state management, custom host tools, and REST API endpoints in `mypai_tools.acp` and `mypai_daemon`.

---

## 1. Asynchronous Delegation Architecture

The ACP task delegation system enables the primary `mypai_daemon` agent (`omp --mode rpc`) to dispatch asynchronous subagent tasks to worker processes (`omp --mode acp`) running in target workspace directories without blocking the main agent.

- **Zero Synchronous RPC / ACP Calls**: All ACP task dispatches are purely asynchronous (`acp_task_async`), returning a `task_id` immediately.
- **Background Execution**: Worker processes execute concurrently in the Background Execution Plane.
- **Main Profile Default (No Profile Inheritance)**: ACP workers never inherit the `mypai` profile. While internal subagents within the `mypai` harness run in the `mypai` profile, ACP workers intentionally execute against the main/default Oh-My-Pi profile (`~/.omp/agent/`, `oh-my-pi`) by default. This allows the `mypai` agent to control external Oh-My-Pi instances and base tools across workspaces.
- **Default Worker Auto-Attachment on Startup**: When `mypai_daemon` starts with ACP enabled (the default state), `AcpDelegationManager` automatically provisions and attaches an initial worker process to `$MYPAI_AGENT_DIR` (the workspace root). This ensures the worker process PID, session ID, and telemetry are immediately active and live on daemon launch without requiring a disable/re-enable cycle.
- **Completion Ingestion & Turn Queue Callback**: When an async ACP subagent finishes, its results are logged in the ACP task store. The delegation manager automatically enqueues a system event callback into the daemon's **Turn Queue** (`source="acp_callback"`, priority=2) so the main agent receives the completed result without manual polling.

---

## 2. Injected Subagent Host Tools (`mypai_tools.acp.tools`)

Registered into `omp_rpc.RpcClient` via `set_custom_tools()`:

| Host Tool Name | Parameter Schema | Description & Functionality |
| :--- | :--- | :--- |
| **`acp_task_async`** | `cwd: str, prompt: str, agent_profile: str = ""` | Dispatches asynchronous background task turn, notifies WebSocket clients, and returns `task_id` immediately. |
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

* **`GET /api/v1/acp/status`**: Get current state (`running` vs `suspended`), active worker child PIDs, task queue depth, `running_tasks`, and recent `finished_tasks`.
* **`GET /api/v1/acp/tasks/{task_id}`**: Fetch details and output of a specific ACP task.
* **`POST /api/v1/acp/enable`**: Enable ACP execution state in SQLite settings and broadcast WebSocket event `acp_state_changed`.
* **`POST /api/v1/acp/suspend`** / **`POST /api/v1/acp/disable`**: Suspend ACP execution state in SQLite settings.
* **`POST /api/v1/acp/shutdown`**: Stop worker processes and clear pool.
* **`POST /api/v1/acp/restart`**: Restart worker process pool.
