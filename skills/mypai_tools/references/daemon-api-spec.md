# MyPAI Daemon REST & WebSocket API Specification (`daemon-api-spec.md`)

All endpoints are hosted by default on `http://127.0.0.1:52080/api/v1`.

---

## 1. Session Management Endpoints

The `/api/v1/session` routes support the complete 4-action OMP RPC feature set matching MyPAI Cron: **`prompt`**, **`steer`**, **`followup`**, and **`abort_and_prompt`**.

### `POST /api/v1/session/prompt`
* **Description**: Queue a new prompt turn into the OMP RPC session.
* **Request Body**:
  ```json
  {
    "prompt": "Review the latest build output",
    "mode": "prompt | steer | followup | abort_and_prompt",
    "source": "webui | signal | spooler | cron",
    "context": {}
  }
  ```
* **Response (HTTP 200)**: `{"status": "queued", "task_id": "evt_8a9b1c2d"}`

### `POST /api/v1/session/steer`
* **Description**: Inject a high-priority steering interrupt turn (`mode: "steer"`).
* **Request Body**: `{"prompt": "Stop execution immediately and summarize progress"}`
* **Response (HTTP 200)**: `{"status": "steered", "task_id": "evt_3f2e1d"}`

### `POST /api/v1/session/followup`
* **Description**: Append a followup message to the active OMP turn (`mode: "followup"`).
* **Request Body**: `{"prompt": "Also check the staging error logs"}`
* **Response (HTTP 200)**: `{"status": "queued", "task_id": "evt_5e6f7a"}`

### `POST /api/v1/session/abort_and_prompt`
* **Description**: Abort the currently running OMP turn immediately and inject a new prompt (`mode: "abort_and_prompt"`).
* **Request Body**: `{"prompt": "Cancel deployment and roll back database"}`
* **Response (HTTP 200)**: `{"status": "aborted_and_queued", "task_id": "evt_9b8c7d"}`

### `GET /api/v1/session/status`
* **Description**: Return current RPC connection state, process PID, queue depth, and uptime.
* **Response (HTTP 200)**:
  ```json
  {
    "status": "connected",
    "pid": 12345,
    "agent_dir": "/home/user/project",
    "is_busy": false,
    "queue_depth": 0,
    "uptime_sec": 3600.5
  }
  ```

### `GET /api/v1/session/history`
* **Description**: Return queued and completed OMP session turn history and execution telemetry.
* **Response (HTTP 200)**:
  ```json
  [
    {
      "status": "success",
      "mode": "prompt",
      "session_name": "mypai_daemon - running",
      "session_uuid": "019ff94b-a70d-7000-b992-6296fb54e774",
      "return_code": 0,
      "output": "Turn response output string...",
      "error": "",
      "duration_sec": 0.291,
      "task_id": "evt_fbee566c"
    }
  ]
  ```

---

## 2. Cron & Scheduler Management Endpoints

### `GET /api/v1/cron/jobs`
* **Description**: List all registered cron jobs and telemetry stats.
* **Query Parameters**: `include_disabled=true` (boolean)

### `POST /api/v1/cron/jobs`
* **Description**: Register a new scheduled task in SQLite database.
* **Request Body**:
  ```json
  {
    "name": "Nightly Audit",
    "cron": "0 3 * * *",
    "kind": "omp | http | shell | python",
    "action": "prompt",
    "url": "",
    "args": [],
    "kwargs": {},
    "result_prompt": "Audit finished: #[_OUTPUT]",
    "result_error_prompt": "ALERT: #[_ERROR]",
    "result_action": "ignore | prompt | steer | followup | abort_and_prompt",
    "result_channel": ""
  }
  ```

### `PUT /api/v1/cron/jobs/{job_id}`
* **Description**: Modify parameters of an existing cron task.

### `DELETE /api/v1/cron/jobs/{job_id}`
* **Description**: Delete cron job from SQLite database.

### `POST /api/v1/cron/jobs/{job_id}/enable` & `/disable`
* **Description**: Enable or disable target individual cron task.

### `POST /api/v1/cron/enable` & `POST /api/v1/cron/disable`
* **Description**: Temporarily enable or disable global cron task execution across the entire scheduler engine without mutating individual database records.

### `GET /api/v1/cron/status`
* **Description**: Get telemetry status overview (`active`, `disabled`, `idle`), global execution state, total jobs, enabled jobs, and disabled jobs count.

### `POST /api/v1/cron/jobs/run_once`
* **Description**: Reschedule an existing matching task or queue a new one-shot job (`cron="now"`).

---

## 3. Signal Gateway Webhook Endpoint

### `POST /api/v1/signal/webhook`
* **Description**: Webhook target for `signal-cli-rest-api`.
* **Request Body**: JSON envelope from `signal-cli-rest-api` containing sender metadata.
* **Access Control**: Checks if `sender` matches `SIGNAL_ALLOWED_SENDER` (read from `omp.env`). If the sender is unauthorized, returns `{"status": "ignored_unauthorized"}` and drops the payload.
* **Behavior**: If authorized, enqueues notification prompt `"NEW Signal message received from {sender}. Use 'chat_mcp.get_next_unread_message' to read."` into Event Queue, and returns `{"status": "acknowledged"}`.

---

## 4. Real-time WebSocket Endpoint

### `WS /api/v1/ws`
* **Description**: Bi-directional WebSocket stream for WebUI clients.
* **Server Events**:
  - `session_state_change`: `{"event": "state", "status": "connected | busy | disconnected"}`
  - `turn_started`: `{"event": "turn_start", "task_id": "evt_123", "source": "webui"}`
  - `log_line`: `{"event": "log", "line": "[INFO] Executing prompt..."}`
  - `turn_completed`: `{"event": "turn_complete", "output": "..."}`
* **Client Handlers**: `{"action": "ping"}`, `{"action": "submit_prompt", "prompt": "..."}`.

---

## 5. ACP Intra-Agent Delegation Endpoints

### `GET /api/v1/acp/status`
* **Description**: Get ACP execution state (`running` vs `suspended`), active worker processes, and task telemetry.
* **Response (HTTP 200)**: `{"state": "running", "running": true, "suspended": false, "active_workers": 1, "workers": [...]}`

### `POST /api/v1/acp/enable`
* **Description**: Enable ACP intra-agent delegation execution state in SQLite settings (`SettingsModel`).
* **Response (HTTP 200)**: `{"state": "running", "running": true, "suspended": false}`

### `POST /api/v1/acp/suspend` & `/disable`
* **Description**: Suspend ACP intra-agent delegation execution state in SQLite settings. Rejects new delegation host tool calls with a suspension error.
* **Response (HTTP 200)**: `{"state": "suspended", "running": false, "suspended": true}`

