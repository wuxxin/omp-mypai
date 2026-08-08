#!/usr/bin/env python3
"""OMP Background Service Heartbeat & Cron Runner.

Implements an AsyncIOScheduler background daemon connected to the per-project
SQLite database ($HOME/.omp/cron/projects/<project_hash>/cron.db).
Manages heartbeat.pid lifecycle, periodic DB job sync, and generic job execution
(RPC pokes, HTTP requests, and CLI shell commands).
"""

import argparse
import asyncio
import atexit
import json
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, Set

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

try:
    from mypai_tools.cron_mcp import (
        Base,
        CronJobModel,
        _get_db_session,
        get_heartbeat_pid_path,
        get_project_db_path,
        import_default_jobs_if_needed,
    )
except ImportError:
    from cron_mcp import (
        Base,
        CronJobModel,
        _get_db_session,
        get_heartbeat_pid_path,
        get_project_db_path,
        import_default_jobs_if_needed,
    )

DEFAULT_RPC_URL = os.getenv("OMP_RPC_URL", "http://localhost:51080/v1/rpc")
DEFAULT_HINDSIGHT_URL = os.getenv("HINDSIGHT_API_URL", "http://localhost:8888")
DEFAULT_BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "omp-orchestrator")
DEFAULT_DB_SYNC_INTERVAL_SEC = 10.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mypai_heartbeat")


def write_pid_file(pid_path: str) -> None:
    """Write current process PID to heartbeat.pid file."""
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    logger.info("Wrote PID %d to %s", os.getpid(), pid_path)


def remove_pid_file(pid_path: str) -> None:
    """Remove heartbeat.pid file if present."""
    if os.path.isfile(pid_path):
        try:
            os.remove(pid_path)
            logger.info("Cleaned up PID file %s", pid_path)
        except OSError as exc:
            logger.warning("Failed to remove PID file %s: %s", pid_path, exc)


async def execute_job(
    job: Dict[str, Any], default_rpc_url: str = DEFAULT_RPC_URL
) -> Dict[str, Any]:
    """Generic job executor supporting command, rpc, and http job types."""
    job_type = job.get("job_type", "rpc")
    job_id = job.get("id", "unknown")
    name = job.get("name", "Unnamed Job")
    logger.info("Executing job '%s' (ID: %s, type: %s)...", name, job_id, job_type)

    start_time = time.time()
    result: Dict[str, Any] = {"job_id": job_id, "name": name, "job_type": job_type}

    try:
        if job_type == "command":
            cmd = job.get("job_action") or job.get("prompt") or ""
            if not cmd:
                raise ValueError("No CLI command specified in job_action or prompt.")
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            exit_code = proc.returncode
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()
            logger.info("Command job '%s' completed with exit code %d", name, exit_code)
            result.update(
                {
                    "status": "success" if exit_code == 0 else "error",
                    "exit_code": exit_code,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                }
            )

        elif job_type == "rpc":
            action_data: Dict[str, Any] = {}
            raw_action = job.get("job_action", "")
            if raw_action:
                try:
                    action_data = json.loads(raw_action) if isinstance(raw_action, str) else raw_action
                except Exception:
                    pass

            method = action_data.get("method") or "cron_trigger"
            params = action_data.get("params") or {
                "job_id": job_id,
                "name": name,
                "prompt": job.get("prompt", ""),
                "target_channel": job.get("target_channel", "signal"),
                "timestamp": start_time,
            }
            rpc_endpoint = action_data.get("rpc_url") or default_rpc_url

            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": f"cron-{job_id}-{int(start_time)}",
            }
            headers = {"Content-Type": "application/json"}

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(rpc_endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                try:
                    res_json = resp.json()
                except Exception:
                    res_json = {"raw": resp.text}
                logger.info("RPC job '%s' returned HTTP %d", name, resp.status_code)
                result.update(
                    {"status": "success", "http_code": resp.status_code, "data": res_json}
                )

        elif job_type == "http":
            action_data: Dict[str, Any] = {}
            raw_action = job.get("job_action", "")
            if raw_action:
                try:
                    action_data = json.loads(raw_action) if isinstance(raw_action, str) else raw_action
                except Exception:
                    pass

            method = (action_data.get("method") or "POST").upper()
            url = action_data.get("url") or ""

            hindsight_url = os.getenv("HINDSIGHT_API_URL", "http://localhost:8888")
            hindsight_bank = os.getenv("HINDSIGHT_BANK_ID", "omp-orchestrator")
            omp_rpc_url = os.getenv("OMP_RPC_URL", "http://localhost:51080/v1/rpc")

            url = url.replace("{HINDSIGHT_API_URL}", hindsight_url)
            url = url.replace("{HINDSIGHT_BANK_ID}", hindsight_bank)
            url = url.replace("{OMP_RPC_URL}", omp_rpc_url)

            headers = action_data.get("headers") or {"Content-Type": "application/json"}
            payload = action_data.get("payload")

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method, url, json=payload if payload else None, headers=headers
                )
                resp.raise_for_status()
                try:
                    res_json = resp.json()
                except Exception:
                    res_json = {"raw": resp.text}
                logger.info(
                    "HTTP job '%s' (%s %s) returned HTTP %d",
                    name,
                    method,
                    url,
                    resp.status_code,
                )
                result.update(
                    {"status": "success", "http_code": resp.status_code, "data": res_json}
                )

        else:
            raise ValueError(f"Unsupported job_type '{job_type}'")

    except Exception as exc:
        logger.error("Execution error for job '%s': %s", name, exc)
        result.update({"status": "error", "error": str(exc)})

    duration_ms = round((time.time() - start_time) * 1000, 2)
    result["duration_ms"] = duration_ms
    return result


class HeartbeatDaemon:
    """Manages AsyncIOScheduler connected to project SQLite DB and daemon lifecycle."""

    def __init__(
        self,
        project_dir: str = "",
        rpc_url: str = DEFAULT_RPC_URL,
    ) -> None:
        self.project_dir = project_dir
        self.rpc_url = rpc_url
        self.db_path = get_project_db_path(project_dir)
        self.pid_path = get_heartbeat_pid_path(project_dir)

        self.scheduler = AsyncIOScheduler()
        self.scheduled_job_ids: Set[str] = set()

    def sync_jobs_from_db(self) -> None:
        """Query DB for active cron jobs and synchronize AsyncIOScheduler tasks."""
        session = _get_db_session(self.project_dir)
        try:
            db_jobs = session.query(CronJobModel).filter_by(enabled=True).all()
            current_active_ids: Set[str] = set()

            for job in db_jobs:
                job_dict = job.to_dict()
                job_id = job.id
                current_active_ids.add(job_id)
                aps_job_id = f"cron_db_{job_id}"

                if aps_job_id not in self.scheduled_job_ids:
                    try:
                        trigger = CronTrigger.from_crontab(job.cron_expression)
                        self.scheduler.add_job(
                            execute_job,
                            trigger=trigger,
                            args=[job_dict, self.rpc_url],
                            id=aps_job_id,
                            name=job.name,
                            replace_existing=True,
                        )
                        self.scheduled_job_ids.add(aps_job_id)
                        logger.info(
                            "Scheduled DB cron job '%s' (ID: %s, type: %s, schedule: '%s')",
                            job.name,
                            job_id,
                            job.job_type,
                            job.cron_expression,
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to parse cron trigger for job %s: %s", job_id, exc
                        )

            # Remove obsolete jobs no longer enabled or present in DB
            to_remove = set()
            for aps_job_id in self.scheduled_job_ids:
                raw_id = aps_job_id.replace("cron_db_", "")
                if raw_id not in current_active_ids:
                    try:
                        self.scheduler.remove_job(aps_job_id)
                        logger.info("Removed DB cron job ID: %s from scheduler", raw_id)
                    except Exception:
                        pass
                    to_remove.add(aps_job_id)
            self.scheduled_job_ids -= to_remove

        finally:
            session.close()

    async def start(self) -> None:
        """Start scheduler, register DB jobs, and write PID file."""
        write_pid_file(self.pid_path)

        def cleanup_handler(*args: Any) -> None:
            remove_pid_file(self.pid_path)

        atexit.register(cleanup_handler)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop = asyncio.get_running_loop()
                loop.add_signal_handler(sig, cleanup_handler)
            except (NotImplementedError, RuntimeError):
                pass

        # Schedule periodic DB sync
        self.scheduler.add_job(
            self.sync_jobs_from_db,
            trigger=IntervalTrigger(seconds=DEFAULT_DB_SYNC_INTERVAL_SEC),
            id="job_db_sync",
            name="SQLite DB Job Sync",
            replace_existing=True,
        )

        self.scheduler.start()
        self.sync_jobs_from_db()
        logger.info("Heartbeat daemon running with AsyncIOScheduler backend.")

        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutting down Heartbeat daemon...")
            self.scheduler.shutdown(wait=False)
            remove_pid_file(self.pid_path)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="OMP Background Service Heartbeat & Cron Runner",
        usage="python3 -m mypai_tools.heartbeat daemon|once [options]",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["daemon", "once"],
        help="Execution mode: 'daemon' (run continuously) or 'once' (execute single pass and exit)",
    )
    parser.add_argument(
        "--project-dir",
        default="",
        help="Project directory path (default: current directory)",
    )
    parser.add_argument(
        "--rpc-url",
        default=DEFAULT_RPC_URL,
        help=f"OMP RPC service endpoint URL (default: {DEFAULT_RPC_URL})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )
    parsed = parser.parse_args(args)
    if not parsed.mode:
        parser.print_help(sys.stderr)
        sys.exit(1)
    return parsed


async def main_async(cli_args: argparse.Namespace) -> int:
    """Async main entrypoint."""
    if cli_args.verbose:
        logger.setLevel(logging.DEBUG)

    project_dir = cli_args.project_dir
    session = _get_db_session(project_dir)

    try:
        db_jobs = session.query(CronJobModel).filter_by(enabled=True).all()
        jobs_list = [j.to_dict() for j in db_jobs]
    finally:
        session.close()

    if cli_args.mode == "once":
        logger.info(
            "Executing single pass (once) for %d active DB job(s)...", len(jobs_list)
        )
        for job in jobs_list:
            res = await execute_job(job, default_rpc_url=cli_args.rpc_url)
            logger.info("Single pass result for '%s': %s", job.get("name"), res.get("status"))
        return 0

    daemon = HeartbeatDaemon(
        project_dir=project_dir,
        rpc_url=cli_args.rpc_url,
    )
    await daemon.start()
    return 0


def main() -> None:
    """CLI script entrypoint."""
    parsed = parse_args()
    try:
        sys.exit(asyncio.run(main_async(parsed)))
    except KeyboardInterrupt:
        logger.info("Heartbeat process interrupted. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
