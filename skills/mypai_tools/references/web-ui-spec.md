# MyPAI Embedded WebUI Specification (`web-ui-spec.md`)

## Executive Summary

`mypai_daemon` embeds a responsive, dark-mode Single-Page Application (SPA) served directly by FastAPI at `/` or `/ui`. Built with Vanilla HTML, modern CSS tokens, and JavaScript, it requires zero build steps and communicates via HTTP REST (`/api/v1`) and WebSockets (`/api/v1/ws`).

---

## 1. Screen Wireframe Layout

```
myPAI Console * Connected (steady green/red) STREAMING (red 'ON AIR' pulse if active, grey if idle) | Session | Cron | Team | [⟳ Refresh]

RPC Session Live Console             Reload History  Clear Console  [ ] Show Stream Chunks  [x] Show Events  Port: 52080
+-----------------------------------------------------------------------------------------------+
| [00:35:05] Queued run_once for 'Nightly Database Backup & Audit'                              |
| [00:35:06] [Turn (PROMPT)] Audit active project todos, verify pending commitments...          |
| [00:35:12] [Turn Completed] Task evt_0bbd1bd8 (6.2s)                                          |
+-----------------------------------------------------------------------------------------------+

Turn:                                                                             Abort Turn
+-----------------------------------------------------------------------------------------------+
| Type a prompt, CTRL-Enter to submit                                                           |
+-----------------------------------------------------------------------------------------------+
                                                                Submit  [ Create (Prompt) [v] ]  [?]

Options:
  • Create (Prompt)      -> Normal prompt (dispatches when turn is idle)
  • Inject into (Steer)  -> Steer (interrupts active turn mid-execution)
  • Append to (Followup) -> Followup (appends to turn conversation)
  • Abort and Create     -> Abort & Prompt (drops queue, aborts active turn, and prompts)
```

---

## 2. Keyboard Shortcuts & Ergonomics

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| **`Enter`** | **New Line** | Inserts newline in prompt textarea without submitting. |
| **`Ctrl+Enter`** / **`Cmd+Enter`** | **Submit Turn** | Submits prompt using currently selected mode (`Create`, `Inject into`, etc.). |
| **`Alt+Enter`** | **Quick Steer / Inject** | Submits prompt immediately as `steer`, regardless of dropdown selection. |
| **`Ctrl+Shift+Enter`** | **Quick Followup** | Submits prompt immediately as `followup`, regardless of dropdown selection. |
| **`Ctrl+Escape`** / **`Cmd+Escape`** | **Turn Abort** | Immediately triggers turn abort and purges pending queue. |
| **`/`** or **`Ctrl+K`** / **`Cmd+K`** | **Focus Prompt Input** | Focuses prompt textarea. |
| **`Ctrl+B`** / **`Alt+S`** | **Toggle Sidebar** | Collapses/expands right-hand sidebar. |
| **`?`** or **`Shift+/`** / **`F1`** | **Shortcuts Overlay** | Toggles the keyboard shortcuts cheat sheet overlay modal. |
| **`Escape`** | **Close Overlay** | Closes the keyboard shortcuts overlay modal if active. |
| **`Ctrl+Alt+1`** / **`Cmd+Alt+1`** | **Session Tab** | Activates Session telemetry tab. |
| **`Ctrl+Alt+2`** / **`Cmd+Alt+2`** | **Cron Tab** | Activates Cron tasks tab. |
| **`Ctrl+Alt+3`** / **`Cmd+Alt+3`** | **Team Tab** | Activates Team (External Agents / ACP) tab. |

---

## 3. Sidebar Tab Specifications

### 3.1 Sidebar Tab: Session (`Session`)

```
Harness:          [connected]
  Profile: mypai
  PID: 12345      Reconnect
  Runtime: 4h 14m
  Tasks (Queued/Running/Done): [3] , [2] , [344]

Session:
  Name: mypai_daemon - running
  UUID: x-y-z-a-b
  Model: qwen3
  Steering: one-at-a-time
  Runtime: 2h 13m
  Messages (U/A): 12 / 12
  Tool Calls: 45
  Token Total/In/Out: 45,210 / 32,100 / 13,110
  Context Window: 58,471 / 128,000 (45.7%)
  [########################          ]

Turn:             [Inactive]
  Queued: 0 entries
  Status: Inactive
  Last/Current: evt_0bbd1bd8@prompt
  Model: qwen3
  Runtime: 6s
  Messages (U/A), ToolCalls: Last turn completed OK
  Snippet: "Audit active project todos..."
```

### 3.2 Sidebar Tab: Cron (`Cron`)

```
Cron Jobs:            [Enabled]
  Total/ Active Jobs: 4 Total (4 enabled, 0 disabled)
  
  [ Disable Cron ]  [ Export ]  [ Import ]

  Name | Cron     | Kind | Calls | Action
  +------------------------------------+
  | Nightly Backup | 0 3 * * * | shell | 14 | Run |
  | Work Sweep     | */30 * * * * | omp | 48 | Run |
```

### 3.3 Sidebar Tab: Team (`Team`)

```
Team (External Agents):     [Connected]
  Workers: 1
  Total / Active Tasks: 2 / 1
  Runtime: 12h 13m

  [ Disable External Agents ]

  Workers:
  - [PID 2852442] /home/wuxxin/agent-shared/mypai-workspace (Runtime: 2s)

  Tasks:
  - [PID 2852442][TASK 123] [*] db_audit (Runtime: 4s)
  - [PID 2852442][TASK 124] code_sweep (Runtime: 12s)
```
