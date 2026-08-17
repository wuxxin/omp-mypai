#!/usr/bin/env python3
"""OMP Ingestion Spooler Pipeline.

Monitors an inbox drop folder (~/Recordings/Inbox), applies quiescence gating,
SHA256 content hashing, sidecar metadata parsing, local STT transcription,
and automated Hindsight retention.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# Default configurations overridable via environment variables
DEFAULT_INBOX_DIR = os.getenv("SPOOLER_INBOX", str(Path.home() / "Recordings" / "Inbox"))
DEFAULT_STT_URL = os.getenv("STT_URL", "http://localhost:50090/v1/audio/transcriptions")
DEFAULT_HINDSIGHT_URL = os.getenv("HINDSIGHT_URL", "http://localhost:8888")
DEFAULT_BANK_ID = os.getenv("HINDSIGHT_BANK_ID", os.getenv("OMP_PROFILE", "mypai"))
DEFAULT_QUIESCENCE_SECONDS = 10.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_STATE_FILE = str(Path.home() / ".omp" / "spooler_processed_hashes.json")

MEDIA_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".mov", ".flac"}
IGNORED_SUFFIXES = {".tmp", ".part", ".crdownload", ".download"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mypai_input_spooler")


def compute_content_hash(file_path: Path) -> str:
    """Compute SHA256 over file size + head 8MB.

    Args:
        file_path: Path to the target file.

    Returns:
        str: Hexadecimal digest of the computed SHA256 hash.
    """
    stat = file_path.stat()
    h = hashlib.sha256()
    h.update(f"{stat.st_size}\n".encode())
    with open(file_path, "rb") as f:
        head = f.read(8 * 1024 * 1024)
        h.update(head)
    return h.hexdigest()


def parse_sidecar(file_path: Path) -> tuple[dict[str, str], Path | None]:
    """Parse key: value lines from sidecar markdown file.

    Checks for candidate sidecar files:
    1. <file_path>.md (e.g. recording.mp4.md)
    2. <stem>.md (e.g. recording.md)

    Args:
        file_path: Path to primary file being processed.

    Returns:
        Tuple[Dict[str, str], Path | None]: Parsed metadata dictionary and sidecar path if found.
    """
    candidate_paths = [
        file_path.with_suffix(file_path.suffix + ".md"),
        file_path.with_suffix(".md"),
    ]

    sidecar_path: Path | None = None
    for candidate in candidate_paths:
        if candidate.is_file() and candidate != file_path:
            sidecar_path = candidate
            break

    metadata: dict[str, str] = {}
    if sidecar_path is None:
        return metadata, None

    try:
        content = sidecar_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith(("---", "#")):
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key_clean = key.strip().lower()
                val_clean = val.strip().strip("'\"")
                if key_clean and val_clean:
                    metadata[key_clean] = val_clean
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse sidecar metadata from %s: %s", sidecar_path, exc)

    return metadata, sidecar_path


def load_processed_hashes(state_file: Path) -> set[str]:
    """Load previously processed file hashes from JSON state file.

    Args:
        state_file: Path to state file.

    Returns:
        Set[str]: Set of processed hash strings.
    """
    if not state_file.is_file():
        return set()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load processed state from %s: %s", state_file, exc)
    return set()


def save_processed_hashes(state_file: Path, hashes: set[str]) -> None:
    """Save processed file hashes to JSON state file.

    Args:
        state_file: Path to state file.
        hashes: Set of processed hash strings.
    """
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(sorted(hashes), indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to save processed state to %s: %s", state_file, exc)


async def async_wait_for_quiescence(
    file_path: Path,
    quiescence_sec: float = DEFAULT_QUIESCENCE_SECONDS,
    check_interval: float = 1.0,
) -> bool:
    """Wait until target file size remains unchanged for quiescence_sec seconds.

    Args:
        file_path: Path to the target file.
        quiescence_sec: Time in seconds file size must remain constant.
        check_interval: Polling check interval in seconds.

    Returns:
        bool: True if file achieved quiescence, False if file vanished or encountered OSError.
    """
    if not file_path.exists():
        return False

    last_size = -1
    stable_start = time.time()

    while time.time() - stable_start < quiescence_sec:
        if not file_path.exists():
            return False
        try:
            cur_size = file_path.stat().st_size
        except OSError:
            return False

        if cur_size != last_size:
            last_size = cur_size
            stable_start = time.time()

        await asyncio.sleep(check_interval)

    return True


class InputSpooler:
    """Input Spooler Ingestion Pipeline manager."""

    def __init__(
        self,
        inbox: Path = Path(DEFAULT_INBOX_DIR),
        stt_url: str = DEFAULT_STT_URL,
        hindsight_url: str = DEFAULT_HINDSIGHT_URL,
        bank_id: str = DEFAULT_BANK_ID,
        quiescence_sec: float = DEFAULT_QUIESCENCE_SECONDS,
        state_file: Path = Path(DEFAULT_STATE_FILE),
    ) -> None:
        """Initialize the InputSpooler instance.

        Args:
            inbox: Inbox directory path.
            stt_url: Local STT service transcription URL.
            hindsight_url: Hindsight API base URL.
            bank_id: Hindsight bank identifier.
            quiescence_sec: Quiescence stability window in seconds.
            state_file: Path to processed hashes state file.
        """
        self.inbox = inbox
        self.stt_url = stt_url
        self.hindsight_url = hindsight_url
        self.bank_id = bank_id
        self.quiescence_sec = quiescence_sec
        self.state_file = state_file

        self.inbox.mkdir(parents=True, exist_ok=True)
        self.processed_hashes: set[str] = load_processed_hashes(self.state_file)

    async def transcribe_audio(self, file_path: Path) -> str:
        """Transcribe an audio/video file using local Speech-to-Text service.

        Args:
            file_path: Path to media file.

        Returns:
            str: Transcribed text output or empty string on error.
        """
        logger.info("Transcribing media file '%s' via STT (%s)...", file_path.name, self.stt_url)
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                with open(file_path, "rb") as audio_file:  # noqa: ASYNC230
                    files = {"file": (file_path.name, audio_file, "application/octet-stream")}
                    data = {"model": "whisper-1"}
                    response = await client.post(self.stt_url, files=files, data=data)

                if response.status_code == 200:
                    try:
                        res_json = response.json()
                        transcript = res_json.get("text", "").strip()
                        logger.info(
                            "STT transcription for '%s' successful (%d chars).",
                            file_path.name,
                            len(transcript),
                        )
                        return transcript
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to decode STT JSON response: %s", exc)
                        return ""
                else:
                    logger.warning(
                        "STT service returned HTTP %d: %s",
                        response.status_code,
                        response.text,
                    )
                    return ""
        except Exception as exc:  # noqa: BLE001
            logger.error("STT transcription exception for '%s': %s", file_path.name, exc)
            return ""

    async def retain_hindsight(
        self,
        title: str,
        item_type: str,
        item_hash: str,
        filename: str,
        transcript: str,
    ) -> dict[str, Any]:
        """Post ingested item summary and transcript into Hindsight memory bank.

        Args:
            title: Title of the ingested item.
            item_type: Type of the ingested item.
            item_hash: SHA256 hash digest.
            filename: Original file name.
            transcript: STT transcript or registration message.

        Returns:
            Dict[str, Any]: Hindsight API response details.
        """
        content_body = (
            f"Content Ingestion [{item_type.upper()}] '{title}': "
            f"{transcript if transcript else 'File registered.'}"
        )

        tags = ["spooler", "ingestion", item_hash, item_type]
        metadata = {
            "source": "spooler",
            "filename": filename,
            "file_hash": item_hash,
            "title": title,
            "type": item_type,
        }

        primary_url = f"{self.hindsight_url.rstrip('/')}/v1/default/banks/{self.bank_id}/retain"
        fallback_url = f"{self.hindsight_url.rstrip('/')}/v1/default/banks/{self.bank_id}/memories"

        logger.info(
            "Retaining ingested item '%s' (hash: %s) to Hindsight bank '%s'...",
            title,
            item_hash[:12],
            self.bank_id,
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Try primary /retain endpoint
            try:
                res = await client.post(
                    primary_url,
                    json={"content": content_body, "tags": tags, "metadata": metadata},
                    headers={"Content-Type": "application/json"},
                )
                if res.status_code in (200, 201, 202):
                    logger.info(
                        "Hindsight retention successful via /retain (HTTP %d).",
                        res.status_code,
                    )
                    try:
                        data = res.json()
                    except Exception:  # noqa: BLE001
                        data = {"raw": res.text}
                    return {
                        "status": "success",
                        "http_code": res.status_code,
                        "data": data,
                    }
            except Exception as exc:  # noqa: BLE001
                logger.debug("Primary /retain call failed: %s", exc)

            # 2. Try fallback /memories endpoint (Hindsight v1 items schema)
            try:
                res = await client.post(
                    fallback_url,
                    json={
                        "items": [
                            {
                                "content": content_body,
                                "document_id": f"spooler-{item_hash}",
                                "tags": tags,
                                "metadata": metadata,
                            }
                        ],
                        "async": True,
                    },
                    headers={"Content-Type": "application/json"},
                )
                res.raise_for_status()
                try:
                    data = res.json()
                except Exception:  # noqa: BLE001
                    data = {"raw": res.text}
                logger.info(
                    "Hindsight retention successful via /memories (HTTP %d).",
                    res.status_code,
                )
                return {"status": "success", "http_code": res.status_code, "data": data}
            except Exception as exc:  # noqa: BLE001
                logger.error("Hindsight retention exception for '%s': %s", title, exc)
                return {"status": "error", "error": str(exc)}

    async def process_file(self, file_path: Path) -> bool:
        """Process a candidate inbox file through the ingestion pipeline.

        Args:
            file_path: Target file path in inbox directory.

        Returns:
            bool: True if item was successfully ingested, False otherwise.
        """
        if not file_path.is_file():
            return False

        filename_lower = file_path.name.lower()
        if filename_lower.startswith(".") or file_path.suffix.lower() == ".md":
            return False

        if file_path.suffix.lower() in IGNORED_SUFFIXES:
            return False

        logger.info("Evaluating inbox file for quiescence gating: %s", file_path.name)
        quiescent = await async_wait_for_quiescence(
            file_path=file_path, quiescence_sec=self.quiescence_sec
        )
        if not quiescent:
            logger.warning("File '%s' failed quiescence check or was removed.", file_path.name)
            return False

        item_hash = compute_content_hash(file_path)
        if item_hash in self.processed_hashes:
            logger.debug(
                "Skipping already processed file '%s' (hash: %s).",
                file_path.name,
                item_hash[:12],
            )
            return False

        logger.info("Ingesting new file '%s' (SHA256: %s)", file_path.name, item_hash)

        # Parse sidecar metadata if available
        sidecar_meta, sidecar_path = parse_sidecar(file_path)
        title = sidecar_meta.get("title", file_path.stem)
        default_type = "audio" if file_path.suffix.lower() in MEDIA_EXTENSIONS else "document"
        item_type = sidecar_meta.get("type", default_type)

        if sidecar_path:
            logger.info(
                "Parsed sidecar '%s' for '%s': title='%s', type='%s'",
                sidecar_path.name,
                file_path.name,
                title,
                item_type,
            )

        # Transcribe audio/video files if media type
        transcript = ""
        if file_path.suffix.lower() in MEDIA_EXTENSIONS:
            transcript = await self.transcribe_audio(file_path)

        # Retain into Hindsight memory bank
        await self.retain_hindsight(
            title=title,
            item_type=item_type,
            item_hash=item_hash,
            filename=file_path.name,
            transcript=transcript,
        )

        # Notify mypai_daemon via REST API
        await self.notify_daemon(
            title=title,
            filename=file_path.name,
            transcript=transcript,
            item_hash=item_hash,
        )

        # Mark processed and save state
        self.processed_hashes.add(item_hash)
        save_processed_hashes(self.state_file, self.processed_hashes)
        logger.info("Successfully ingested '%s' into spooler pipeline.", file_path.name)
        return True

    async def notify_daemon(
        self, title: str, filename: str, transcript: str, item_hash: str
    ) -> None:
        """Send HTTP notification prompt to mypai_daemon REST API."""
        daemon_url = os.getenv("MYPAI_AGENT_URL", "http://127.0.0.1:52080")
        endpoint = f"{daemon_url.rstrip('/')}/api/v1/session/prompt"
        snippet = transcript[:200] if transcript else "File drop registered."
        prompt_text = f"🎙️ New inbox item processed ({filename}): '{title}'. Content: {snippet}"

        payload = {
            "prompt": prompt_text,
            "mode": "prompt",
            "source": "spooler",
            "context": {"filename": filename, "hash": item_hash, "title": title},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(endpoint, json=payload)
                if res.status_code == 200:
                    logger.info("Notified mypai_daemon of spooler ingestion for '%s'.", filename)
                else:
                    logger.warning("mypai_daemon notification returned HTTP %d", res.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to notify mypai_daemon: %s", exc)

    async def scan_inbox(self) -> int:
        """Scan inbox directory once and process all eligible files.

        Returns:
            int: Number of files newly ingested during this scan.
        """
        logger.info("Scanning inbox directory: %s", self.inbox)
        ingested_count = 0
        if not self.inbox.exists():
            return 0

        files = sorted(self.inbox.iterdir())
        for item in files:
            if item.is_file():
                success = await self.process_file(item)
                if success:
                    ingested_count += 1

        return ingested_count

    async def run_once(self) -> int:
        """Execute a single scan pass over the inbox folder and exit.

        Returns:
            int: Number of files processed.
        """
        logger.info("Executing Spooler single scan pass (--once)...")
        count = await self.scan_inbox()
        logger.info("Single pass complete. Ingested %d item(s).", count)
        return count

    async def run_watch(self, poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS) -> None:
        """Execute continuous monitoring loop over the inbox folder.

        Args:
            poll_interval: Interval between directory polling scans in seconds.
        """
        logger.info(
            "Starting Spooler Continuous Monitoring Loop (--daemon) on %s (interval=%.1fs)...",
            self.inbox,
            poll_interval,
        )
        try:
            while True:
                await self.scan_inbox()
                await asyncio.sleep(poll_interval)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Spooler daemon loop stopped.")


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        args: Optional raw command line arguments.

    Returns:
        argparse.Namespace: Parsed CLI options.
    """
    parser = argparse.ArgumentParser(
        description="OMP Spooler Ingestion Pipeline",
        usage="python3 -m mypai_tools.input_spooler daemon|once [options]",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["daemon", "once"],
        help="Execution mode: 'daemon' (run continuous monitoring loop) or 'once' (execute single scan pass and exit)",
    )
    parser.add_argument(
        "--inbox",
        default=DEFAULT_INBOX_DIR,
        help=f"Path to the inbox drop folder (default: {DEFAULT_INBOX_DIR})",
    )
    parser.add_argument(
        "--stt-url",
        default=DEFAULT_STT_URL,
        help=f"Local Speech-to-Text transcription URL (default: {DEFAULT_STT_URL})",
    )
    parser.add_argument(
        "--hindsight-url",
        default=DEFAULT_HINDSIGHT_URL,
        help=f"Hindsight API base URL (default: {DEFAULT_HINDSIGHT_URL})",
    )
    parser.add_argument(
        "--bank-id",
        default=DEFAULT_BANK_ID,
        help=f"Hindsight memory bank ID (default: {DEFAULT_BANK_ID})",
    )
    parser.add_argument(
        "--quiescence-sec",
        type=float,
        default=DEFAULT_QUIESCENCE_SECONDS,
        help=f"Quiescence gating wait time in seconds (default: {DEFAULT_QUIESCENCE_SECONDS})",
    )
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help=f"Path to processed hashes JSON state file (default: {DEFAULT_STATE_FILE})",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("OMP_PROFILE", "mypai"),
        help="Target OMP profile name (default: mypai)",
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
    """Async main entrypoint.

    Args:
        cli_args: Parsed CLI namespace.

    Returns:
        int: Process exit code.
    """
    if cli_args.profile:
        os.environ["OMP_PROFILE"] = cli_args.profile

    if cli_args.verbose:
        logger.setLevel(logging.DEBUG)

    ingestor = InputSpooler(
        inbox=Path(cli_args.inbox).expanduser(),
        stt_url=cli_args.stt_url,
        hindsight_url=cli_args.hindsight_url,
        bank_id=cli_args.bank_id,
        quiescence_sec=cli_args.quiescence_sec,
        state_file=Path(cli_args.state_file).expanduser(),
    )

    if cli_args.mode == "once":
        await ingestor.run_once()
        return 0

    await ingestor.run_watch()
    return 0


def main() -> None:
    """CLI script entrypoint."""
    parsed = parse_args()
    try:
        sys.exit(asyncio.run(main_async(parsed)))
    except KeyboardInterrupt:
        logger.info("Spooler process interrupted by user. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
