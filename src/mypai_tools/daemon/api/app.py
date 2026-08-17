"""FastAPI Application Server for mypai_daemon."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from mypai_tools.daemon.api.acp_router import router as acp_router
from mypai_tools.daemon.api.ws import router as ws_router
from mypai_tools.daemon.api.ws import ws_manager
from mypai_tools.persistence import (
    CronJobModel,
    CronJobSchema,
    export_jobs_from_db,
    get_db_session,
    get_default_timeout_for_kind,
    import_jobs_to_db,
)

app = FastAPI(
    title="MyPAI Daemon REST API",
    description="Central coordinator, OMP RPC session manager, cron scheduler, and Signal gateway.",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(ws_router)
app.include_router(acp_router)


class SessionPromptRequest(BaseModel):
    prompt: str = Field(..., description="Prompt text to submit to OMP session")
    mode: str = Field(
        "prompt", description="Turn mode: prompt, steer, followup, or abort_and_prompt"
    )
    source: str = Field("webui", description="Event source: webui, signal, spooler, or cron")
    context: dict[str, Any] = Field(default_factory=dict, description="Optional turn context")
    sender: str | None = Field(None, description="Optional sender identifier")


# Session Routes
@app.post("/api/v1/session/prompt")
async def session_prompt(req: SessionPromptRequest, request: Request) -> dict[str, Any]:
    queue = getattr(request.app.state, "daemon_queue", None)
    if not queue:
        raise HTTPException(status_code=500, detail="Daemon TurnQueue uninitialized.")

    item = await queue.enqueue(
        prompt=req.prompt,
        mode=req.mode,
        source=req.source,
        context=req.context,
        sender=req.sender,
    )
    await ws_manager.broadcast({"event": "turn_queued", "item": item})
    return {"status": "queued", "task_id": item["task_id"]}


@app.post("/api/v1/session/steer")
async def session_steer(req: SessionPromptRequest, request: Request) -> dict[str, Any]:
    req.mode = "steer"
    return await session_prompt(req, request)


@app.post("/api/v1/session/followup")
async def session_followup(req: SessionPromptRequest, request: Request) -> dict[str, Any]:
    req.mode = "followup"
    return await session_prompt(req, request)


@app.post("/api/v1/session/abort_and_prompt")
async def session_abort_and_prompt(req: SessionPromptRequest, request: Request) -> dict[str, Any]:
    req.mode = "abort_and_prompt"
    return await session_prompt(req, request)


@app.post("/api/v1/session/abort")
async def session_abort(request: Request) -> dict[str, Any]:
    queue = getattr(request.app.state, "daemon_queue", None)
    if queue:
        queue.purge_all()

    session_mgr = getattr(request.app.state, "session_manager", None)
    if not session_mgr:
        raise HTTPException(status_code=500, detail="Session Manager uninitialized.")

    res = session_mgr.abort()
    await ws_manager.broadcast({"event": "turn_aborted", "last_turn": session_mgr.last_turn})
    return res


@app.get("/api/v1/session/status")
async def session_status(request: Request) -> dict[str, Any]:
    session_mgr = getattr(request.app.state, "session_manager", None)
    queue = getattr(request.app.state, "daemon_queue", None)
    if not session_mgr:
        raise HTTPException(status_code=500, detail="Session Manager uninitialized.")

    q_depth = queue.depth() if queue else 0
    return session_mgr.get_status(queue_depth=q_depth)


@app.get("/api/v1/session/state")
async def session_state(request: Request) -> dict[str, Any]:
    session_mgr = getattr(request.app.state, "session_manager", None)
    if not session_mgr:
        raise HTTPException(status_code=500, detail="Session Manager uninitialized.")
    return session_mgr.get_session_state()


@app.post("/api/v1/session/reconnect")
async def session_reconnect(request: Request) -> dict[str, Any]:
    session_mgr = getattr(request.app.state, "session_manager", None)
    queue = getattr(request.app.state, "daemon_queue", None)
    if not session_mgr:
        raise HTTPException(status_code=500, detail="Session Manager uninitialized.")
    session_mgr.triage_connection()
    q_depth = queue.depth() if queue else 0
    return session_mgr.get_status(queue_depth=q_depth)


@app.get("/api/v1/session/stats")
async def session_stats(request: Request) -> dict[str, Any]:
    session_mgr = getattr(request.app.state, "session_manager", None)
    if not session_mgr:
        raise HTTPException(status_code=500, detail="Session Manager uninitialized.")
    return session_mgr.get_session_stats()


@app.get("/api/v1/session/history")
async def session_history(request: Request) -> list[dict[str, Any]]:
    queue = getattr(request.app.state, "daemon_queue", None)
    return queue.history if queue else []


# Cron Routes
@app.get("/api/v1/cron/jobs")
async def cron_list_jobs(request: Request, include_disabled: bool = True) -> list[dict[str, Any]]:
    session = get_db_session(request.app.state.agent_dir)
    try:
        query = session.query(CronJobModel)
        if not include_disabled:
            query = query.filter_by(enabled=True)
        return [j.to_dict() for j in query.all()]
    finally:
        session.close()


@app.post("/api/v1/cron/jobs")
async def cron_add_job(request: Request, job: CronJobSchema) -> dict[str, Any]:
    session = get_db_session(request.app.state.agent_dir)
    job_id = job.id or str(uuid.uuid4())[:8]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    opts_dict = job.opts.model_dump()
    if opts_dict.get("timeout_sec") is None:
        opts_dict["timeout_sec"] = get_default_timeout_for_kind(job.kind)

    result_dict = job.result.model_dump()

    db_job = CronJobModel(
        id=job_id,
        name=job.name.strip(),
        description=job.description.strip(),
        cron=job.cron.strip(),
        kind=job.kind,
        action=job.action.strip(),
        enabled=job.enabled,
        args=json.dumps(job.args),
        kwargs=json.dumps(job.kwargs),
        opts=json.dumps(opts_dict),
        result=json.dumps(result_dict),
        total_runs=0,
        total_failures=0,
        next_run_at="",
        last_run_at="",
        last_runtime=0.0,
        last_returncode=0,
        last_httpcode=0,
        last_output="",
        last_error="",
        created_at=now_iso,
        updated_at=now_iso,
    )
    try:
        session.add(db_job)
        session.commit()
        db_job_dict = db_job.to_dict()

        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler and str(job.cron).strip().lower() in ("now", "@now", "@once"):
            asyncio.create_task(scheduler.run_job(db_job_dict))
        elif scheduler:
            scheduler.sync_jobs_from_db()

        return {"status": "scheduled", "job": db_job_dict}
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@app.put("/api/v1/cron/jobs/{job_id}")
async def cron_modify_job(request: Request, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    session = get_db_session(request.app.state.agent_dir)
    try:
        db_job = (
            session.query(CronJobModel)
            .filter((CronJobModel.id == job_id) | (CronJobModel.name == job_id))
            .first()
        )
        if not db_job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

        for k, v in updates.items():
            if k in ("args", "kwargs", "opts", "result") and isinstance(v, (dict, list)):
                setattr(db_job, k, json.dumps(v))
            elif hasattr(db_job, k):
                setattr(db_job, k, v)

        db_job.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        session.commit()
        return {"status": "modified", "job": db_job.to_dict()}
    finally:
        session.close()


@app.delete("/api/v1/cron/jobs/{job_id}")
async def cron_delete_job(request: Request, job_id: str) -> dict[str, Any]:
    session = get_db_session(request.app.state.agent_dir)
    try:
        db_job = (
            session.query(CronJobModel)
            .filter((CronJobModel.id == job_id) | (CronJobModel.name == job_id))
            .first()
        )
        if not db_job:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
        res = db_job.to_dict()
        session.delete(db_job)
        session.commit()
        return {"status": "deleted", "job": res}
    finally:
        session.close()


@app.post("/api/v1/cron/jobs/{job_id}/enable")
async def cron_enable_job(request: Request, job_id: str) -> dict[str, Any]:
    return await cron_modify_job(request, job_id, {"enabled": True})


@app.post("/api/v1/cron/jobs/{job_id}/disable")
async def cron_disable_job(request: Request, job_id: str) -> dict[str, Any]:
    return await cron_modify_job(request, job_id, {"enabled": False})


@app.post("/api/v1/cron/jobs/run_once")
async def cron_run_once(request: Request, job: CronJobSchema) -> dict[str, Any]:
    session = get_db_session(request.app.state.agent_dir)
    try:
        db_job = (
            session.query(CronJobModel)
            .filter((CronJobModel.id == job.name) | (CronJobModel.name == job.name))
            .first()
        )
        if db_job:
            db_job_dict = db_job.to_dict()
            db_job_dict["cron"] = "now"

            scheduler = getattr(request.app.state, "scheduler", None)
            if scheduler:
                asyncio.create_task(scheduler.run_job(db_job_dict))

            return {"status": "scheduled", "job": db_job_dict}
    finally:
        session.close()

    job.cron = "now"
    return await cron_add_job(request, job)


@app.post("/api/v1/cron/enable")
async def cron_enable_execution(request: Request) -> dict[str, Any]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.enable_cron_execution()
    return {"status": "enabled", "cron_execution_enabled": True}


@app.post("/api/v1/cron/disable")
async def cron_disable_execution(request: Request) -> dict[str, Any]:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.disable_cron_execution()
    return {"status": "disabled", "cron_execution_enabled": False}


@app.get("/api/v1/cron/status")
async def cron_status(request: Request) -> dict[str, Any]:
    session = get_db_session(request.app.state.agent_dir)
    try:
        all_jobs = session.query(CronJobModel).all()
        enabled_count = sum(1 for j in all_jobs if j.enabled)
        disabled_count = len(all_jobs) - enabled_count
        scheduler = getattr(request.app.state, "scheduler", None)
        is_running = bool(
            scheduler and getattr(scheduler, "scheduler", None) and scheduler.scheduler.running
        )
        exec_enabled = bool(scheduler and scheduler.is_cron_execution_enabled())
        return {
            "status": (
                "active"
                if (is_running and exec_enabled)
                else ("disabled" if not exec_enabled else "idle")
            ),
            "cron_execution_enabled": exec_enabled,
            "total_jobs": len(all_jobs),
            "enabled_jobs": enabled_count,
            "disabled_jobs": disabled_count,
        }
    finally:
        session.close()


@app.get("/api/v1/cron/export")
async def cron_export_jobs(request: Request) -> list[dict[str, Any]]:
    session = get_db_session(request.app.state.agent_dir)
    try:
        return export_jobs_from_db(session)
    finally:
        session.close()


@app.post("/api/v1/cron/import")
async def cron_import_jobs(request: Request, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    session = get_db_session(request.app.state.agent_dir)
    try:
        imported, updated = import_jobs_to_db(session, jobs)
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler:
            scheduler.sync_jobs_from_db()
        return {"status": "imported", "imported": imported, "updated": updated}
    finally:
        session.close()


# Signal Webhook Endpoint with Whitelist Filter
@app.post("/api/v1/signal/webhook")
async def signal_webhook(request: Request) -> dict[str, Any]:
    signal_client = getattr(request.app.state, "signal_client", None)
    queue = getattr(request.app.state, "daemon_queue", None)

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return {"status": "error", "error": "Invalid JSON payload"}

    env = payload.get("envelope", {}) if isinstance(payload, dict) else {}
    sender = env.get("sourceNumber") or env.get("source") or env.get("sourceUuid") or ""

    if signal_client and not signal_client.is_sender_allowed(sender):
        return {"status": "ignored_unauthorized", "sender": sender}

    if queue and sender:
        prompt_text = f"📬 NEW Signal message received from {sender}. Use 'chat_mcp.get_next_unread_message' to read."
        await queue.enqueue(prompt=prompt_text, mode="prompt", source="signal", sender=sender)
        await ws_manager.broadcast({"event": "signal_webhook", "sender": sender})
        return {"status": "acknowledged", "sender": sender}

    return {"status": "ignored_empty"}


# Static Single-Page WebUI Handler
@app.get("/ui", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def serve_webui() -> Any:
    webui_path = os.path.join(os.path.dirname(__file__), "..", "..", "webui", "index.html")
    if os.path.isfile(webui_path):
        return FileResponse(webui_path, media_type="text/html")
    return HTMLResponse(content="<h1>MyPAI Daemon WebUI (Index File Missing)</h1>")
