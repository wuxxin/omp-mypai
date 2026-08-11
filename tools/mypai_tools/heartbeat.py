#!/usr/bin/env python3
"""OMP Background Service Heartbeat & Cron Runner.

Implements an AsyncIOScheduler background daemon connected to the per-project
SQLite database ($HOME/.omp/cron/cron-<project_hash>.db).
Manages heartbeat.pid lifecycle, periodic DB job sync, inlined attribute execution telemetry,
CLI JSON import/export, and simplified job execution (rpc, http, shell, python).
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
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from mypai_tools.db import (
    get_db_session,
    get_heartbeat_pid_path,
    get_project_db_path,
    normalize_cron_expression,
    substitute_vars,
)
from mypai_tools.executors import (
    execute_http_job,
    execute_python_job,
    execute_rpc_job,
    execute_shell_job,
)
from mypai_tools.models import CronJobModel

DEFAULT_RPC_URL = os.getenv("OMP_RPC_URL", "http://localhost:51080/v1/rpc")
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
    job: dict[str, Any], default_rpc_url: str = DEFAULT_RPC_URL, project_dir: str = ""
) -> dict[str, Any]:
    """Execute job using inlined attributes and update telemetry stats in DB."""
    job = substitute_vars(job)
    kind = str(job.get("kind", "omp")).lower()
    job_id = job.get("id", "unknown")
    name = job.get("name", "Unnamed Job")

    start_iso = datetime.now(timezone.utc).isoformat()
    start_time = time.time()
    logger.info("Executing job '%s' (ID: %s, kind: %s)...", name, job_id, kind)

    result: dict[str, Any] = {"job_id": job_id, "name": name, "kind": kind}
    returncode = 0
    output_summary = ""

    try:
        if kind == "omp":
            res = await execute_rpc_job(job, default_rpc_url=default_rpc_url)
        elif kind == "http":
            res = await execute_http_job(job)
        elif kind == "shell":
            res = await execute_shell_job(job)
        elif kind == "python":
            res = await execute_python_job(job)
        else:
            raise ValueError(f"Unsupported job kind '{kind}'")

        result.update(res)
        returncode = res.get("return_code", 0)
        output_summary = res.get("output") or res.get("error") or ""

    except Exception as exc:  # noqa: BLE001
        logger.error("Execution error for job '%s': %s", name, exc)
        returncode = 1
        output_summary = str(exc)
        result.update(
            {
                "status": "error",
                "return_code": 1,
                "output": "",
                "error": output_summary,
                "object": None,
            }
        )

    end_time = time.time()
    end_iso = datetime.now(timezone.utc).isoformat()
    duration_sec = round(end_time - start_time, 3)

    result["duration_sec"] = duration_sec

    # Update execution telemetry in DB and disable if one-shot ('now')
    session = get_db_session(project_dir)
    try:
        db_job = session.query(CronJobModel).filter_by(id=job_id).first()
        if db_job:
            cron_clean = str(db_job.cron or "").strip().lower()
            if cron_clean == "now":
                db_job.enabled = False

            db_job.last_start = start_iso
            db_job.last_stop = end_iso
            db_job.last_runtime = duration_sec
            db_job.last_returncode = returncode
            db_job.last_output = output_summary[:2048]
            db_job.total_calls = (db_job.total_calls or 0) + 1
            session.commit()
    except Exception as db_exc:  # noqa: BLE001
        logger.warning("Failed to update telemetry for job %s: %s", job_id, db_exc)
        session.rollback()
    finally:
        session.close()

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
        self.scheduled_job_ids: set[str] = set()

    def sync_jobs_from_db(self) -> None:
        """Query DB for active cron jobs and synchronize AsyncIOScheduler tasks."""
        session = get_db_session(self.project_dir)
        try:
            db_jobs = session.query(CronJobModel).filter_by(enabled=True).all()
            current_active_ids: set[str] = set()

            for job in db_jobs:
                job_dict = job.to_dict()
                job_id = job.id
                current_active_ids.add(job_id)
                aps_job_id = f"cron_db_{job_id}"

                if aps_job_id not in self.scheduled_job_ids:
                    try:
                        cron_str = str(job.cron or "").strip().lower()
                        if cron_str == "now":
                            trigger = DateTrigger(run_date=datetime.now(timezone.utc))
                            misfire_grace = 3600
                        else:
                            normalized_expr = normalize_cron_expression(job.cron)
                            trigger = CronTrigger.from_crontab(normalized_expr)
                            misfire_grace = None

                        self.scheduler.add_job(
                            execute_job,
                            trigger=trigger,
                            args=[job_dict, self.rpc_url, self.project_dir],
                            id=aps_job_id,
                            name=job.name,
                            replace_existing=True,
                            misfire_grace_time=misfire_grace,
                        )
                        self.scheduled_job_ids.add(aps_job_id)
                        logger.info(
                            "Scheduled DB cron job '%s' (ID: %s, type: %s, cron: '%s')",
                            job.name,
                            job_id,
                            job.type,
                            job.cron,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Failed to parse cron trigger for job %s: %s", job_id, exc
                        )

            # Remove obsolete jobs no longer active or present in DB
            to_remove = set()
            for aps_job_id in self.scheduled_job_ids:
                raw_id = aps_job_id.replace("cron_db_", "")
                if raw_id not in current_active_ids:
                    try:
                        self.scheduler.remove_job(aps_job_id)
                        logger.info("Removed DB cron job ID: %s from scheduler", raw_id)
                    except Exception:  # noqa: BLE001, S110
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


def export_jobs_to_json(file_path: str, project_dir: str = "") -> None:
    """Export all registered cron jobs from project DB to specified JSON file path."""
    if not file_path:
        logger.error("Export target JSON file path is required.")
        sys.exit(1)

    abs_path = os.path.abspath(os.path.expanduser(file_path))
    session = get_db_session(project_dir)
    try:
        db_jobs = session.query(CronJobModel).all()
        jobs_list = [j.to_dict() for j in db_jobs]
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump({"jobs": jobs_list}, f, indent=2)
        logger.info("Exported %d job(s) to %s", len(jobs_list), abs_path)
    finally:
        session.close()


def import_jobs_from_json(file_path: str, project_dir: str = "") -> None:
    """Import cron jobs from specified JSON file path into project DB."""
    if not file_path:
        logger.error("Import JSON file path is required.")
        sys.exit(1)

    abs_path = os.path.abspath(os.path.expanduser(file_path))

    if not os.path.isfile(abs_path):
        logger.error("Import file '%s' not found.", abs_path)
        sys.exit(1)

    with open(abs_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs_data = data.get("jobs", data) if isinstance(data, dict) else data
    if not isinstance(jobs_data, list):
        logger.error("Invalid JSON format: expected list of jobs under 'jobs' key.")
        sys.exit(1)

    session = get_db_session(project_dir)
    imported_count = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        for item in jobs_data:
            job_id = item.get("id") or item.get("name", "job")[:8]

            args_val = item.get("args", "")
            if isinstance(args_val, (dict, list)):
                args_val = json.dumps(args_val)

            kwargs_val = item.get("kwargs", {})
            if isinstance(kwargs_val, str) and kwargs_val.strip().startswith("{"):
                try:
                    kwargs_val = json.loads(kwargs_val)
                except Exception:  # noqa: BLE001
                    kwargs_val = {}
            if isinstance(kwargs_val, (dict, list)):
                kwargs_val = json.dumps(kwargs_val)

            kind_val = item.get("kind", "omp")
            action_val = item.get("action", "prompt")
            res_prompt_val = item.get("result_prompt", "")
            res_err_prompt_val = item.get("result_error_prompt", "")
            cron_val = item.get("cron")
            if not cron_val:
                logger.error(
                    "Job '%s' (ID: %s) missing required 'cron' field.",
                    item.get("name"),
                    job_id,
                )
                continue
            res_channel_val = item.get("result_channel", "")

            existing = session.query(CronJobModel).filter_by(id=job_id).first()
            if existing:
                existing.name = item.get("name", existing.name)
                existing.cron = cron_val
                existing.result_prompt = res_prompt_val
                existing.result_error_prompt = res_err_prompt_val
                existing.result_channel = res_channel_val
                existing.kind = kind_val
                existing.action = action_val
                existing.url = item.get("url", existing.url)
                existing.args = args_val
                existing.kwargs = kwargs_val
                existing.result_action = item.get(
                    "result_action", existing.result_action
                )
                existing.enabled = item.get("enabled", existing.enabled)
                existing.updated_at = now_iso
            else:
                job = CronJobModel(
                    id=job_id,
                    name=item.get("name", "Imported Job"),
                    cron=cron_val,
                    result_prompt=res_prompt_val,
                    result_error_prompt=res_err_prompt_val,
                    result_channel=res_channel_val,
                    kind=kind_val,
                    action=action_val,
                    url=item.get("url", ""),
                    args=args_val,
                    kwargs=kwargs_val,
                    result_action=item.get("result_action", "ignore"),
                    enabled=item.get("enabled", True),
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                session.add(job)
            imported_count += 1

        session.commit()
        logger.info("Successfully imported %d job(s) from %s", imported_count, abs_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to import jobs: %s", exc)
        session.rollback()
        sys.exit(1)
    finally:
        session.close()


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments matching heartbeat.md spec."""
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "--project-dir",
        default="",
        help="Project directory path (default: current workspace)",
    )
    parent_parser.add_argument(
        "--rpc-url",
        default=DEFAULT_RPC_URL,
        help=f"OMP RPC service endpoint URL (default: {DEFAULT_RPC_URL})",
    )
    parent_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )

    parser = argparse.ArgumentParser(
        description="OMP Background Service Heartbeat & Cron Runner",
        parents=[parent_parser],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 -m mypai_tools.heartbeat daemon [--project-dir /path/to/project]
  python3 -m mypai_tools.heartbeat once [--project-dir /path/to/project]
  python3 -m mypai_tools.heartbeat import /path/to/jobs.json [--project-dir /path/to/project]
  python3 -m mypai_tools.heartbeat export /path/to/jobs_export.json [--project-dir /path/to/project]
""",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Execution subcommand")

    # 1. daemon subcommand
    subparsers.add_parser(
        "daemon",
        parents=[parent_parser],
        help="Run background heartbeat daemon continuously",
    )

    # 2. once subcommand
    subparsers.add_parser(
        "once",
        parents=[parent_parser],
        help="Execute single pass for active jobs and exit",
    )

    # 3. import subcommand
    sub_import = subparsers.add_parser(
        "import",
        parents=[parent_parser],
        help="Import cron jobs from specified JSON file path",
    )
    sub_import.add_argument(
        "file",
        help="Path to JSON file containing cron jobs to import",
    )

    # 4. export subcommand
    sub_export = subparsers.add_parser(
        "export",
        parents=[parent_parser],
        help="Export all registered cron jobs to specified JSON file path",
    )
    sub_export.add_argument(
        "file",
        help="Destination JSON file path",
    )

    parsed = parser.parse_args(args)

    if not parsed.subcommand:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return parsed


async def main_async(cli_args: argparse.Namespace) -> int:
    """Async main entrypoint."""
    if cli_args.verbose:
        logger.setLevel(logging.DEBUG)

    project_dir = cli_args.project_dir
    subcommand = cli_args.subcommand

    if subcommand == "export":
        export_jobs_to_json(cli_args.file, project_dir=project_dir)
        return 0

    if subcommand == "import":
        import_jobs_from_json(cli_args.file, project_dir=project_dir)
        return 0

    session = get_db_session(project_dir)
    try:
        db_jobs = session.query(CronJobModel).filter_by(enabled=True).all()
        jobs_list = [j.to_dict() for j in db_jobs]
    finally:
        session.close()

    if subcommand == "once":
        logger.info(
            "Executing single pass (once) for %d active DB job(s)...", len(jobs_list)
        )
        for job in jobs_list:
            res = await execute_job(
                job, default_rpc_url=cli_args.rpc_url, project_dir=project_dir
            )
            logger.info(
                "Single pass result for '%s': %s", job.get("name"), res.get("status")
            )
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
