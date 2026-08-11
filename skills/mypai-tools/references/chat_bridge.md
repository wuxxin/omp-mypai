# Chat Bridge Daemon Architectural Specification (`chat_bridge.md`)

## Executive Summary

The **Chat Bridge Daemon** (`mypai_tools.chat_bridge`) connects incoming Signal messaging channels (via `signal-cli` REST API) to persistent **OMP** (oh-my-pi) sessions. It listens for incoming Signal text messages, recalls sender-specific & global context from **Hindsight**, formats customized RPC prompts, queues events into `omp` via `omp_rpc.RpcClient`, and dispatches generated assistant responses back to the Signal chat.

---

## 1. Primary Responsibilities & Functional Features

1. **Signal Daemon Polling**:
   - Polls `signal-cli-rest-api` daemon (`http://127.0.5.1:50888/v1/receive/+15550000000`).
   - Retrieves unread user messages, sender phone numbers/uuids, timestamps, and attachments.

2. **Hindsight Context Recall**:
   - Performs automated recall queries (`POST /v1/default/banks/{bank_id}/recall`) targeting `mypai-orchestrator` and `mypai-developer-profile` to assemble past conversation state and user preferences.

3. **RPC Event Injection into OMP**:
   - Instantiates `omp_rpc.RpcClient`, sets `install_headless_ui()`, and queues customized prompt turns into the active `omp` session.

4. **Outbound Response Dispatch**:
   - Formats assistant responses and dispatches outbound messages back to Signal via `POST /v2/send`.

---

## 2. CLI Command Usage

```bash
# Continuous background bridge mode
python3 -m mypai_tools.chat_bridge [--signal-url http://127.0.5.1:50888] [--number +15550000000]

# Execute single poll pass and exit
python3 -m mypai_tools.chat_bridge --once
```
