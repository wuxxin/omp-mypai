#!/usr/bin/env python3
"""Main Entrypoint for MyPAI Daemon."""

import argparse
import asyncio
import json
import logging
import os
import sys

import uvicorn

from mypai_tools.daemon.api.app import app
from mypai_tools.daemon.api.ws import ws_manager
from mypai_tools.daemon.queue import EventQueue
from mypai_tools.daemon.scheduler import CronScheduler
from mypai_tools.daemon.session_manager import OMPSessionManager
from mypai_tools.signal_client import SignalClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mypai_daemon")


async def queue_worker_loop(
    queue: EventQueue, session_mgr: OMPSessionManager
) -> None:
    """Background task pulling items from EventQueue and executing turns in OMP."""
    logger.info("Started Queue Worker Loop.")
    while True:
        try:
            item = await queue.get_next()
            task_id = item["task_id"]
            prompt = item["prompt"]
            mode = item["mode"]
            source = item["source"]

            logger.info(
                "Processing turn '%s' (mode: %s, source: %s)...",
                task_id,
                mode,
                source,
            )
            await ws_manager.broadcast(
                {"event": "turn_started", "task_id": task_id, "mode": mode, "source": source}
            )

            res = await session_mgr.execute_turn(
                prompt=prompt, mode=mode, context=item.get("context")
            )
            queue.mark_completed(task_id, res)

            await ws_manager.broadcast(
                {
                    "event": "turn_completed",
                    "task_id": task_id,
                    "result": res,
                }
            )
        except asyncio.CancelledError:
            logger.info("Queue Worker Loop cancelled.")
            break
        except Exception as exc:  # noqa: BLE001
            logger.error("Queue Worker Loop error: %s", exc)
            await asyncio.sleep(1.0)


class AccessLogFilter(logging.Filter):
    """Filter out GET /api/v1/session/status logs unless verbose is enabled."""

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self.verbose = verbose

    def filter(self, record: logging.LogRecord) -> bool:
        return self.verbose or "/api/v1/session/status" not in record.getMessage()


def main() -> None:
    """Parse CLI flags and execute mypai_daemon subcommand."""
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "--agent-dir",
        "--project-dir",
        dest="project_dir",
        type=str,
        default=os.getenv("MYPAI_AGENT_DIR", ""),
        help="Target agent directory path (MYPAI_AGENT_DIR)",
    )
    parent_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose DEBUG logging (includes /api/v1/session/status polling logs)",
    )

    parser = argparse.ArgumentParser(
        parents=[parent_parser],
        description="MyPAI Daemon: Central Coordinator, OMP RPC Session Manager & Gateway.",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="Mandatory CLI subcommand: serve, once, import, or export",
    )

    # Subcommand: serve
    serve_parser = subparsers.add_parser(
        "serve",
        parents=[parent_parser],
        help="Run persistent background HTTP REST/WebSocket daemon server",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=52080,
        help="HTTP REST & WebSocket port (default: 52080)",
    )
    serve_parser.add_argument(
        "--session-name",
        type=str,
        default=os.getenv("MYPAI_SESSION_NAME", "mypai-main"),
        help="Fixed session name for OMP (default: mypai-main)",
    )

    # Subcommand: once
    subparsers.add_parser(
        "once",
        parents=[parent_parser],
        help="Run single-pass execution for active cron jobs and exit",
    )

    # Subcommand: import
    import_parser = subparsers.add_parser(
        "import",
        parents=[parent_parser],
        help="Import cron jobs from a JSON file into project SQLite DB",
    )
    import_parser.add_argument("file_path", type=str, help="Path to input JSON file")

    # Subcommand: export
    export_parser = subparsers.add_parser(
        "export",
        parents=[parent_parser],
        help="Export all registered cron jobs from project SQLite DB to a JSON file",
    )
    export_parser.add_argument("file_path", type=str, help="Path to output JSON file")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Attach filter to uvicorn.access logger to silence status polling unless verbose
    logging.getLogger("uvicorn.access").addFilter(AccessLogFilter(verbose=args.verbose))

    if args.command == "import":
        import uuid
        from datetime import datetime, timezone
        from mypai_tools.persistence import CronJobModel, get_db_session

        abs_path = os.path.abspath(os.path.expanduser(args.file_path))
        if not os.path.isfile(abs_path):
            logger.error("Import file '%s' not found.", abs_path)
            sys.exit(1)

        db = get_db_session(args.project_dir)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            jobs_list = data.get("jobs", data) if isinstance(data, dict) else data
            if not isinstance(jobs_list, list):
                logger.error("Expected list of jobs in %s", abs_path)
                sys.exit(1)

            imported_count = 0
            updated_count = 0
            existing_jobs = db.query(CronJobModel).all()
            id_map = {j.id: j for j in existing_jobs}
            name_map = {j.name: j for j in existing_jobs}

            for item in jobs_list:
                if not (isinstance(item, dict) and item.get("name") and item.get("cron")):
                    continue
                item_id = item.get("id")
                item_name = item.get("name")
                existing = id_map.get(item_id) if item_id else name_map.get(item_name)

                if existing:
                    for k in ("description", "cron", "kind", "action", "url", "result_prompt", "result_error_prompt", "result_action", "result_channel", "enabled"):
                        if k in item:
                            setattr(existing, k, item[k])
                    if "args" in item:
                        existing.args = json.dumps(item["args"]) if isinstance(item["args"], (dict, list)) else str(item["args"] or "")
                    if "kwargs" in item:
                        existing.kwargs = json.dumps(item["kwargs"]) if isinstance(item["kwargs"], (dict, list)) else str(item["kwargs"] or "")
                    existing.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    updated_count += 1
                else:
                    new_id = item_id or str(uuid.uuid4())[:8]
                    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    args_str = json.dumps(item.get("args")) if isinstance(item.get("args"), (dict, list)) else str(item.get("args") or "")
                    kwargs_str = json.dumps(item.get("kwargs")) if isinstance(item.get("kwargs"), (dict, list)) else str(item.get("kwargs") or "")
                    job_obj = CronJobModel(
                        id=new_id,
                        name=item_name,
                        description=item.get("description", ""),
                        cron=item["cron"],
                        kind=item.get("kind", "omp"),
                        action=item.get("action", "prompt"),
                        url=item.get("url", ""),
                        args=args_str,
                        kwargs=kwargs_str,
                        result_prompt=item.get("result_prompt", ""),
                        result_error_prompt=item.get("result_error_prompt", ""),
                        result_action=item.get("result_action", "ignore"),
                        result_channel=item.get("result_channel", ""),
                        enabled=item.get("enabled", True),
                        created_at=now_iso,
                        updated_at=now_iso,
                    )
                    db.add(job_obj)
                    imported_count += 1
            db.commit()
            logger.info("Cron jobs import complete for '%s': %d created, %d updated.", args.file_path, imported_count, updated_count)
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("Error importing cron jobs: %s", exc)
            sys.exit(1)
        finally:
            db.close()

    if args.command == "export":
        from mypai_tools.persistence import CronJobModel, get_db_session

        abs_path = os.path.abspath(os.path.expanduser(args.file_path))
        db = get_db_session(args.project_dir)
        try:
            jobs = [j.to_dict() for j in db.query(CronJobModel).all()]
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                json.dump({"jobs": jobs}, f, indent=2)
            logger.info("Successfully exported %d cron jobs to '%s'.", len(jobs), abs_path)
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error exporting cron jobs: %s", exc)
            sys.exit(1)
        finally:
            db.close()

    queue = EventQueue()
    scheduler = CronScheduler(
        project_dir=args.project_dir, daemon_queue=queue
    )

    if args.command == "once":
        logger.info("Running single pass execution...")
        scheduler.sync_jobs_from_db()
        sys.exit(0)

    # Subcommand: serve
    session_name = getattr(args, "session_name", "mypai-main")

    session_mgr = OMPSessionManager(
        project_dir=args.project_dir, session_name=session_name
    )
    signal_client = SignalClient()

    # Attach components to FastAPI app state
    app.state.daemon_queue = queue
    app.state.session_manager = session_mgr
    app.state.scheduler = scheduler
    app.state.signal_client = signal_client

    # Start Queue Worker Loop & Uvicorn Server
    async def run_server() -> None:
        scheduler.start()
        scheduler.sync_jobs_from_db()

        worker_task = asyncio.create_task(queue_worker_loop(queue, session_mgr))
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=args.port,
            log_level="debug" if args.verbose else "info",
        )
        server = uvicorn.Server(config)

        loop = asyncio.get_running_loop()
        import signal

        def handle_shutdown(sig_name: str) -> None:
            logger.info("Received signal %s. Initiating graceful shutdown...", sig_name)
            asyncio.create_task(ws_manager.broadcast({"event": "daemon_stopping"}))
            server.should_exit = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig.name: handle_shutdown(s))
            except (NotImplementedError, RuntimeError):
                pass

        try:
            await server.serve()
        finally:
            logger.info("Cleaning up daemon resources...")
            worker_task.cancel()
            scheduler.shutdown()
            if session_mgr.rpc_client:
                try:
                    session_mgr.rpc_client.stop()
                except Exception:  # noqa: BLE001, S110
                    pass

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("mypai_daemon stopped by user.")


if __name__ == "__main__":
    main()
