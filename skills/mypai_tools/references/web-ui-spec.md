# MyPAI Embedded WebUI Specification (`web-ui-spec.md`)

## Executive Summary

`mypai_daemon` embeds a responsive, dark-mode Single-Page Application (SPA) served directly by FastAPI at `/` or `/ui`. Built with Vanilla HTML, modern CSS tokens, and JavaScript, it requires zero build steps and communicates via HTTP REST (`/api/v1`) and WebSockets (`/api/v1/ws`).

---

## 1. Screen Wireframe Layout

```
myPAI Console: ● Connected | Main Agent: [IDLE / ACTIVE / STREAMING] | Team: ● Connected | Agents: X Active - Y Streaming | Session | Cron | Team | [⟳ Refresh]

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

### 1.1 Header Status Strip & Glowing Badges

* **Main Agent**:
  * `IDLE` (Gray text `#94a3b8`, subdued background) — When no active turn is running.
  * `ACTIVE` (Green text `#10b981`, emerald border) — When a turn is being processed.
  * `STREAMING` (Glowing red text `#ff8080`, broadcast pulse animation) — When active tokens are streaming.
* **Team Status**:
  * `● Connected` (Green dot) or `● Suspended` / `● Disabled` (Amber/Red dot).
* **Agents (External ACP Workers)**:
  * `X Active` (Green if X > 0, Gray if 0)
  * `Y Streaming` (Glowing Red if Y > 0, Gray if 0)

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
| **`Escape`** | **Close Overlay / Task Viewer** | Restores RPC live console if Task Viewer is active, or closes shortcuts modal. |
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

Each cron job renders in a two-row card with no long description:
- **Row 1**: `● <Title>` (red dot = running, green dot = enabled, gray dot = disabled) <space> `[Enable / Disable]` button
- **Row 2**: `<cron_expr>` | `<kind>` | `Calls: <calls>` <space> `[Run]` button

```
Cron Jobs:            [Enabled]
  Total / Active Jobs: 4 Total (4 enabled, 0 disabled)
  
  [ Disable Cron ]  [ Export ]  [ Import ]

  +-------------------------------------------------------------+
  | ● Nightly Database Backup                       [ Disable ] |
  | 0 3 * * *  ·  SHELL  ·  Calls: 14                   [ Run ] |
  +-------------------------------------------------------------+
  | ● Work Ingestion Sweep                          [ Disable ] |
  | */30 * * * *  ·  OMP  ·  Calls: 48                  [ Run ] |
  +-------------------------------------------------------------+
```

### 3.3 Sidebar Tab: Team (`Team`)

Displays worker status, currently running external agent tasks, and the last 5 finished tasks:

```
Team (External Agents):     [Connected]
  Workers: 1
  Total / Active Tasks: 2 / 1
  Runtime: 12h 13m

  [ Disable External Agents ]

  Workers:
  - [PID 2852442] /home/wuxxin/agent-shared/mypai-workspace (Runtime: 2s)

  Tasks (Running):
  - [acp-task-0bbd1bd8] Code Refactor Task (Runtime: 4s)  [ Cancel ]

  Finished Tasks (Last 5):
  - [acp-task-883c011a] Security Audit (6.2s, Completed)   [ View ]
  - [acp-task-12fa89b2] Test Suite Run (14.1s, Completed)  [ View ]
```

### 3.4 Finished Task Output Viewer

When `[View]` is clicked on any finished task:
1. The current live console stream view is saved in memory.
2. The Live Console container renders the full preformatted output of the task with a header displaying Task ID, Role, Workspace, and duration.
3. Clicking `[Back to Live Console]` or pressing `Escape` immediately restores the live console stream.
