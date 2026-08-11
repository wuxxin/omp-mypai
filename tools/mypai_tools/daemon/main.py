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


def main() -> None:
    """Parse CLI flags and launch mypai_daemon."""
    parser = argparse.ArgumentParser(
        description="MyPAI Daemon: Central Coordinator, OMP RPC Session Manager & Gateway."
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=os.getenv("MYPAI_PROJECT_DIR", os.getcwd()),
        help="Target workspace directory path",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=52080,
        help="HTTP REST & WebSocket port (default: 52080)",
    )
    parser.add_argument(
        "--session-name",
        type=str,
        default=os.getenv("MYPAI_SESSION_NAME", "mypai-main"),
        help="Fixed session name for OMP (default: mypai-main)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single pass for active cron jobs and exit",
    )
    args = parser.parse_args()

    # Instantiate Core Components
    queue = EventQueue()
    session_mgr = OMPSessionManager(
        project_dir=args.project_dir, session_name=args.session_name
    )
    scheduler = CronScheduler(
        project_dir=args.project_dir, daemon_queue=queue
    )
    signal_client = SignalClient()

    if args.once:
        logger.info("Running single pass execution...")
        scheduler.sync_jobs_from_db()
        sys.exit(0)

    # Attach components to FastAPI app state
    app.state.daemon_queue = queue
    app.state.session_manager = session_mgr
    app.state.scheduler = scheduler
    app.state.signal_client = signal_client

    # Launch Cron Scheduler
    scheduler.start()
    scheduler.sync_jobs_from_db()

    # Start Queue Worker Loop & Uvicorn Server
    async def run_server() -> None:
        worker_task = asyncio.create_task(queue_worker_loop(queue, session_mgr))
        config = uvicorn.Config(
            app, host="0.0.0.0", port=args.port, log_level="info"
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
                except Exception:  # noqa: BLE001
                    pass

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("mypai_daemon stopped by user.")


if __name__ == "__main__":
    main()
