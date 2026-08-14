#!/usr/bin/env python3
"""Main Entrypoint for MyPAI Daemon."""

import argparse
import asyncio
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


async def queue_worker_loop(queue: EventQueue, session_mgr: OMPSessionManager) -> None:
    """Background task pulling items from EventQueue and executing turns in OMP."""
    logger.info("Started Queue Worker Loop.")
    while True:
        try:
            item = await queue.get_next()
            task_id = item["task_id"]
            prompt = item["prompt"]
            mode = item["mode"]
            source = item["source"]

            # Connection triage & session reconciliation prior to turn handoff
            session_mgr.triage_connection()

            logger.info(
                "Processing turn '%s' (mode: %s, source: %s, rpc_state: %s)...",
                task_id,
                mode,
                source,
                session_mgr.connection_state,
            )
            await ws_manager.broadcast(
                {
                    "event": "turn_started",
                    "task_id": task_id,
                    "mode": mode,
                    "source": source,
                    "rpc_state": session_mgr.connection_state,
                }
            )

            res = await session_mgr.execute_turn(
                prompt=prompt, mode=mode, context=item.get("context"), task_id=task_id
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
    """Filter out 200 OK polling logs for session status, session stats, and cron status unless verbose is enabled."""

    SILENT_ENDPOINTS = (
        "v1/session/status",
        "v1/session/stats",
        "v1/cron/status",
    )

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self.verbose = verbose

    def filter(self, record: logging.LogRecord) -> bool:
        if self.verbose:
            return True
        msg = record.getMessage()
        return not (
            any(endpoint in msg for endpoint in self.SILENT_ENDPOINTS)
            and (" 200 " in msg or " 200 OK" in msg or msg.endswith(" 200"))
        )


def main() -> None:
    """Parse CLI flags and execute mypai_daemon subcommand."""
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "--agent-dir",
        dest="agent_dir",
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
        help="Run background daemon REST API server and queue worker",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MYPAI_PORT", "52080")),
        help="REST API server port (default: 52080)",
    )

    # Subcommand: once
    subparsers.add_parser(
        "once",
        parents=[parent_parser],
        help="Execute pending scheduled tasks once and exit",
    )

    # Subcommand: import
    import_parser = subparsers.add_parser(
        "import",
        parents=[parent_parser],
        help="Import cron jobs from a YAML or JSON file into SQLite database",
    )
    import_parser.add_argument(
        "file_path", type=str, help="Path to input YAML or JSON file containing jobs"
    )

    # Subcommand: export
    export_parser = subparsers.add_parser(
        "export",
        parents=[parent_parser],
        help="Export registered cron jobs to a YAML or JSON file (defaults to YAML)",
    )
    export_parser.add_argument(
        "file_path",
        nargs="?",
        default="jobs.yaml",
        type=str,
        help="Path to output file (default: jobs.yaml)",
    )
    export_parser.add_argument(
        "--format",
        "-f",
        choices=["yaml", "yml", "json"],
        default=None,
        help="Output format: yaml (default) or json",
    )

    args = parser.parse_args()

    if args.agent_dir:
        os.environ["MYPAI_AGENT_DIR"] = args.agent_dir

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Attach filter to uvicorn.access logger to silence status polling unless verbose
    logging.getLogger("uvicorn.access").addFilter(AccessLogFilter(verbose=args.verbose))

    if args.command == "import":
        from mypai_tools.persistence import get_db_session, import_jobs_to_db
        from mypai_tools.tools import load_jobs_file

        db = get_db_session(args.agent_dir)
        try:
            jobs_list = load_jobs_file(args.file_path)
            imported_count, updated_count = import_jobs_to_db(db, jobs_list)
            logger.info(
                "Cron jobs import complete for '%s': %d created, %d updated.",
                args.file_path,
                imported_count,
                updated_count,
            )
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("Error importing cron jobs: %s", exc)
            sys.exit(1)
        finally:
            db.close()

    if args.command == "export":
        from mypai_tools.persistence import export_jobs_from_db, get_db_session
        from mypai_tools.tools import dump_jobs_file

        db = get_db_session(args.agent_dir)
        try:
            jobs = export_jobs_from_db(db)
            output_file = dump_jobs_file(args.file_path, jobs, fmt=args.format)
            logger.info(
                "Successfully exported %d cron jobs to '%s'.", len(jobs), output_file
            )
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error exporting cron jobs: %s", exc)
            sys.exit(1)
        finally:
            db.close()

    queue = EventQueue()
    scheduler = CronScheduler(agent_dir=args.agent_dir, daemon_queue=queue)

    if args.command == "once":
        logger.info("Running single pass execution...")
        scheduler.sync_jobs_from_db()
        sys.exit(0)

    # Subcommand: serve
    session_mgr = OMPSessionManager(agent_dir=args.agent_dir)
    signal_client = SignalClient()

    # Attach components to FastAPI app state
    app.state.agent_dir = args.agent_dir
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
