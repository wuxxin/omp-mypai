# MyPAI Embedded Single-Page WebUI Specification (`web-ui-spec.md`)

## Executive Summary

`mypai_daemon` embeds a responsive, dark-mode **Glassmorphism Single-Page Application (SPA)** served directly by FastAPI at `/` or `/ui`. It requires **zero Node.js build pipeline** at runtime and connects to `mypai_daemon` via HTTP REST (`/api/v1`) and WebSockets (`/api/v1/ws`).

---

## 1. User Interface Layout & Components

<img src="webui-layout.svg" alt="MyPAI Embedded Single-Page WebUI Layout" width="840" style="max-width: 100%; height: auto;" />

> 💡 *Interactive / Standalone HTML version available at [`webui-layout.html`](webui-layout.html).*

---

## 2. Component Specifications

### 2.1 Header & Status Indicator
- Displays real-time daemon state: `CONNECTED` (green pulsing dot), `BUSY` (amber dot), or `DISCONNECTED` (red dot).
- Shows active process PID, target workspace path, and uptime counter.

### 2.2 Transcript & Log Stream
- Subscribes to `WS /api/v1/ws`.
- **Automatic History Restoration**: Queries `GET /api/v1/session/history` on load to automatically restore past turn prompts and complete assistant outputs.
- **Full Preformatted Output**: Renders multi-line responses and code blocks using `white-space: pre-wrap` without 120-character line truncation.
- **Live Text Delta Streaming**: Receives real-time text updates (`message_update` events) extracted from `omp_rpc` `MessageUpdateEvent` text deltas.
- **Stream Chunks Toggle**: Includes **Show Stream Chunks** toggle checkbox (persisted via `localStorage`). When unchecked (default), intermediate streaming deltas are hidden and only the final complete output line (`[Output]`) is displayed. When checked, live streaming tokens (`[Stream]`) are appended in real-time.
- Includes quick-action controls: **Reload History**, **Clear Console**, **Show Stream Chunks**, and **Include Debug Events** filter toggle.

### 2.3 Interactive Control Line
- **Input Textarea**: Allows human operator to type prompts directly into the active `omp` session.
- **Mode Selector**:
  - `prompt`: Submits standard turn (`POST /api/v1/session/prompt`).
  - `steer`: Submits high-priority interrupt (`POST /api/v1/session/steer`).
  - `followup`: Appends followup turn (`POST /api/v1/session/followup`).
  - `abort_and_prompt`: Aborts active turn and queues new prompt (`POST /api/v1/session/abort_and_prompt`).

### 2.4 Scrollable Sidebar Telemetry & Registered Cron Tasks
- **Collapsible Sidebar**: Dynamic grid layout with smooth collapsing toggle and layout state persistence (`localStorage`).
- **Independent Scrollbar**: `<aside>` has a maximum height (`calc(100vh - 120px)`) with independent `overflow-y: auto` scrolling and a custom smooth dark scrollbar.
- **Session Telemetry**: Displays fixed session name, daemon PID, turn queue depth, and process uptime.
- **Usage Telematics**: Real-time user/assistant message counters, tool call stats, input/output/total token counters, and estimated session cost ($0.0000).
- **Cron Telemetry**: Displays global execution state (`Enabled` / `Disabled`), total registered jobs count, active vs inactive job counts.
- **Global Cron Toggle**: Interactive button calling `POST /api/v1/cron/enable` or `POST /api/v1/cron/disable` to temporarily pause/resume engine execution without modifying database records.
- **Registered Cron Tasks Panel**:
  - Embedded inside sidebar card. Queries `GET /api/v1/cron/jobs` on load.
  - Displays registered task titles, descriptions, 5-field cron schedules, kind badges, call metrics, and one-click **Run Now** buttons (`POST /api/v1/cron/jobs/run_once`).
