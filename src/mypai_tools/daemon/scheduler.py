"""APScheduler Engine and SQLite DB Task Sync for mypai_daemon."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from mypai_tools.executors import (
    execute_http_job,
    execute_omp_rpc_job,
    execute_python_job,
    execute_shell_job,
)
from mypai_tools.persistence import (
    CronJobModel,
    get_db_session,
    get_project_db_path,
)
from mypai_tools.utils import (
    normalize_cron_expression,
    substitute_vars,
)

logger = logging.getLogger("mypai_daemon.scheduler")


class CronScheduler:
    """Manages AsyncIOScheduler synced with project SQLite database."""

    def __init__(self, agent_dir: str = "", daemon_queue: Any | None = None) -> None:
        self.agent_dir = agent_dir
        self.daemon_queue = daemon_queue
        self.db_path = get_project_db_path(agent_dir)
        self.scheduler = AsyncIOScheduler()
        self.scheduled_job_ids: set[str] = set()
        self.enabled: bool = True

    def enable_cron_execution(self) -> bool:
        """Enable global cron task execution without modifying DB records."""
        self.enabled = True
        if self.scheduler.running and self.scheduler.state == 2:
            self.scheduler.resume()
        logger.info("Global cron task execution ENABLED.")
        return True

    def disable_cron_execution(self) -> bool:
        """Disable global cron task execution without modifying DB records."""
        self.enabled = False
        if self.scheduler.running and self.scheduler.state == 1:
            self.scheduler.pause()
        logger.info("Global cron task execution DISABLED.")
        return False

    def is_cron_execution_enabled(self) -> bool:
        """Check if global cron execution is currently enabled."""
        return self.enabled

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("CronScheduler AsyncIOScheduler engine started.")

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("CronScheduler AsyncIOScheduler engine shutdown.")

    async def run_job(self, job_dict: dict[str, Any]) -> dict[str, Any]:
        """Execute a cron task using the appropriate executor engine."""
        job = substitute_vars(job_dict)
        kind = str(job.get("kind", "omp")).lower()
        job_id = job.get("id", "unknown")
        name = job.get("name", "Unnamed Job")

        if not self.enabled:
            logger.info(
                "Global cron execution disabled; skipping task '%s' (ID: %s).",
                name,
                job_id,
            )
            return {
                "status": "skipped",
                "reason": "cron_disabled",
                "job_id": job_id,
                "name": name,
            }

        logger.info(
            "Executing cron task '%s' (ID: %s, kind: %s)...", name, job_id, kind
        )
        start_time = datetime.now(timezone.utc).isoformat()
        t0 = asyncio.get_event_loop().time()

        res: dict[str, Any] = {"job_id": job_id, "name": name, "kind": kind}
        returncode = 0
        output_summary = ""

        try:
            if kind == "omp":
                if self.daemon_queue:
                    # Enqueue into mypai_daemon queue
                    prompt = job.get("action", "prompt")
                    mode = job.get("result_action") or "prompt"
                    if mode not in ("prompt", "steer", "followup", "abort_and_prompt"):
                        mode = "prompt"
                    queued_item = await self.daemon_queue.enqueue(
                        prompt=prompt, mode=mode, source="cron", context=job
                    )
                    res.update({"status": "queued", "task_id": queued_item["task_id"]})
                    output_summary = f"Queued task {queued_item['task_id']}"
                else:
                    res_exec = await execute_omp_rpc_job(job)
                    res.update(res_exec)
                    returncode = res_exec.get("return_code", 0)
                    output_summary = res_exec.get("output") or ""
            elif kind == "http":
                res_exec = await execute_http_job(job)
                res.update(res_exec)
                returncode = res_exec.get("return_code", 0)
                output_summary = res_exec.get("output") or ""
            elif kind == "shell":
                res_exec = await execute_shell_job(job)
                res.update(res_exec)
                returncode = res_exec.get("return_code", 0)
                output_summary = res_exec.get("output") or ""
            elif kind == "python":
                res_exec = await execute_python_job(job)
                res.update(res_exec)
                returncode = res_exec.get("return_code", 0)
                output_summary = res_exec.get("output") or ""
            else:
                raise ValueError(f"Unsupported job kind '{kind}'")

        except Exception as exc:  # noqa: BLE001
            logger.error("Error executing cron job %s: %s", name, exc)
            returncode = 1
            output_summary = str(exc)
            res.update({"status": "error", "error": output_summary, "return_code": 1})

        duration = round(asyncio.get_event_loop().time() - t0, 3)
        res["duration_sec"] = duration

        # Record telemetry in SQLite DB
        session = get_db_session(self.agent_dir)
        try:
            db_job = session.query(CronJobModel).filter_by(id=job_id).first()
            if db_job:
                cron_clean = str(db_job.cron or "").strip().lower()
                if cron_clean in ("now", "@now", "@once"):
                    db_job.enabled = False

                db_job.last_start = start_time
                db_job.last_stop = datetime.now(timezone.utc).isoformat()
                db_job.last_runtime = duration
                db_job.last_returncode = returncode
                db_job.last_output = output_summary[:2048]
                db_job.total_calls = (db_job.total_calls or 0) + 1
                session.commit()
        except Exception as db_exc:  # noqa: BLE001
            session.rollback()
            logger.warning(
                "Failed to update DB telemetry for job %s: %s", job_id, db_exc
            )
        finally:
            session.close()

        return res

    def sync_jobs_from_db(self) -> None:
        """Query SQLite database for active cron jobs and sync AsyncIOScheduler."""
        session = get_db_session(self.agent_dir)
        try:
            db_jobs = session.query(CronJobModel).filter_by(enabled=True).all()
            active_ids: set[str] = set()

            for job in db_jobs:
                job_dict = job.to_dict()
                job_id = job.id
                active_ids.add(job_id)
                aps_id = f"cron_db_{job_id}"

                if aps_id not in self.scheduled_job_ids:
                    cron_clean = str(job.cron or "").strip().lower()
                    if cron_clean in ("now", "@now", "@once"):
                        trigger = DateTrigger(run_date=datetime.now(timezone.utc))
                    else:
                        norm_expr = normalize_cron_expression(job.cron)
                        parts = norm_expr.split()
                        if len(parts) == 5:
                            trigger = CronTrigger(
                                minute=parts[0],
                                hour=parts[1],
                                day=parts[2],
                                month=parts[3],
                                day_of_week=parts[4],
                            )
                        else:
                            logger.warning(
                                "Invalid cron expression '%s' for job '%s'",
                                job.cron,
                                job.name,
                            )
                            continue

                    self.scheduler.add_job(
                        self.run_job,
                        trigger=trigger,
                        args=[job_dict],
                        id=aps_id,
                        replace_existing=True,
                        max_instances=1,
                    )
                    self.scheduled_job_ids.add(aps_id)

            # Clean up removed or disabled tasks
            for scheduled_id in list(self.scheduled_job_ids):
                raw_id = scheduled_id.replace("cron_db_", "")
                if raw_id not in active_ids:
                    try:
                        self.scheduler.remove_job(scheduled_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "Ignored exception removing scheduled job '%s': %s",
                            scheduled_id,
                            exc,
                        )
                    self.scheduled_job_ids.remove(scheduled_id)

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to sync cron jobs from DB: %s", exc)
        finally:
            session.close()
