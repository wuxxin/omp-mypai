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
    "mode": "prompt",
    "source": "webui",
    "context": {}
  }
  ```
* **Response (HTTP 200)**: `{"status": "queued", "task_id": "evt_8a9b1c2d"}`

### `POST /api/v1/session/steer`
* **Description**: Inject a high-priority steering interrupt turn (`mode: "steer"`).
* **Request Body**: `{"prompt": "Stop execution immediately and summarize progress"}`
* **Response (HTTP 200)**: `{"status": "queued", "task_id": "evt_3f2e1d"}`

### `POST /api/v1/session/followup`
* **Description**: Append a followup message to the active OMP turn (`mode: "followup"`).
* **Request Body**: `{"prompt": "Also check the staging error logs"}`
* **Response (HTTP 200)**: `{"status": "queued", "task_id": "evt_5e6f7a"}`

### `POST /api/v1/session/abort_and_prompt`
* **Description**: Abort the currently running OMP turn immediately, flush the turn queue, and inject a new prompt (`mode: "abort_and_prompt"`).
* **Request Body**: `{"prompt": "Cancel deployment and roll back database"}`
* **Response (HTTP 200)**: `{"status": "queued", "task_id": "evt_9b8c7d"}`

### `POST /api/v1/session/abort`
* **Description**: Instant Control-Plane Interrupt. Purges all pending turns from `TurnQueue` immediately and triggers `session_mgr.abort()`, stopping execution without waiting for queue worker loop ticks.
* **Response (HTTP 200)**:
  ```json
  {
    "status": "aborted",
    "last_turn": {
      "task_id": "evt_9b8c7d",
      "mode": "prompt",
      "model": "qwen3-32b",
      "source": "webui",
      "duration_sec": 4.2,
      "prompt_snippet": "Run migration script...",
      "status": "aborted",
      "completed_at": "2026-08-18T00:15:00Z"
    }
  }
  ```

### `GET /api/v1/session/status`
* **Description**: Return current RPC connection state, process PID, daemon profile, session UUID, active call details, queue depth, and uptime.

### `GET /api/v1/session/state`
* **Description**: Return session state telemetry (model, thinking level, streaming status, steering mode, context window usage).

### `GET /api/v1/session/stats`
* **Description**: Return session message counts, tool call counts, token in/out/total, and estimated cost.

### `POST /api/v1/session/reconnect`
* **Description**: Force RPC connection triage & reattachment.

### `GET /api/v1/session/history`
* **Description**: Return queued and completed OMP session turn history.

---

## 2. Cron & Scheduler Management Endpoints

### `GET /api/v1/cron/jobs`
* **Description**: List all registered cron jobs and telemetry stats.
* **Query Parameters**: `include_disabled=true` (boolean)

### `GET /api/v1/cron/export`
* **Description**: Export all registered cron jobs from SQLite database as a JSON array.

### `POST /api/v1/cron/import`
* **Description**: Import or update a JSON array of cron job definitions into SQLite database.

### `POST /api/v1/cron/jobs`
* **Description**: Register a new scheduled task in SQLite database according to `CronJobSchema`.

### `PUT /api/v1/cron/jobs/{job_id}`
* **Description**: Modify parameters of an existing cron task.

### `DELETE /api/v1/cron/jobs/{job_id}`
* **Description**: Delete cron job from SQLite database.

### `POST /api/v1/cron/jobs/{job_id}/enable` & `/disable`
* **Description**: Enable or disable target individual cron task.

### `POST /api/v1/cron/enable` & `POST /api/v1/cron/disable`
* **Description**: Enable or disable global cron execution across the scheduler engine.

### `GET /api/v1/cron/status`
* **Description**: Get telemetry status overview (`active`, `disabled`, `idle`), global execution state, total jobs, enabled jobs, and disabled jobs count.

### `POST /api/v1/cron/jobs/run_once`
* **Description**: Queue or execute an immediate one-shot task (`cron="now"`).

---

## 3. ACP Control Endpoints (`/api/v1/acp`)

* **`GET /api/v1/acp/status`**: Return ACP worker status, worker process list, and task metrics.
* **`POST /api/v1/acp/enable`**: Enable ACP delegation state.
* **`POST /api/v1/acp/disable`** / **`POST /api/v1/acp/suspend`**: Suspend ACP delegation.
* **`POST /api/v1/acp/shutdown`**: Terminate active ACP worker processes.
* **`POST /api/v1/acp/restart`**: Restart ACP worker process pool.

---

## 4. Signal Gateway Webhook Endpoint

### `POST /api/v1/signal/webhook`
* **Description**: Webhook target for `signal-cli-rest-api`.
* **Access Control**: Validates sender against `SIGNAL_ALLOWED_SENDER`.
* **Behavior**: If authorized, enqueues notification prompt into Turn Queue and returns `{"status": "acknowledged"}`.
