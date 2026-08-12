# MyPAI Daemon CLI Command Usage (`cli-usage.md`)

## Executive Summary

`mypai_daemon` can be launched continuously as a background process or executed single-pass via the command line interface.

---

## 1. Daemon Launch Commands & Environment Configuration

`mypai_daemon` loads configuration from environment variables defined in `omp.env`:

```env
MYPAI_SESSION_NAME="mypai-main"         # Fixed session name reused across restarts
SIGNAL_ACCOUNT="+15550001111"           # Local Signal phone profile
SIGNAL_ALLOWED_SENDER="+15559992222"    # Whitelisted Signal sender phone number
```

```bash
# Continuous background daemon server mode (default port 52080)
python3 -m mypai_tools.daemon serve [--agent-dir /path/to/project] [--port 52080]

# Execute single-pass for all active cron jobs and exit
python3 -m mypai_tools.daemon once [--agent-dir /path/to/project]
```

### Mandatory Subcommands
- `serve`: Launches continuous HTTP REST/WebSocket server and APScheduler worker daemon. Accepts `--port` (default `52080`).
- `once`: Executes pending active cron jobs once and exits immediately.
- `import <file_path>`: Imports cron tasks from specified JSON file into SQLite DB.
- `export <file_path>`: Exports registered cron tasks from SQLite DB to specified JSON file.

### Common Flags
- `--agent-dir`: Target workspace directory path (sets & exports `MYPAI_AGENT_DIR`). Defaults to current working directory (`$PWD`).
- `--verbose` / `-v`: Enables verbose DEBUG logging.

---

## 2. Cron Job Import & Export Commands

```bash
# Import cron jobs from specified JSON file path into project SQLite DB
python3 -m mypai_tools.daemon import /path/to/jobs.json [--agent-dir /path/to/project]

# Export all registered jobs from project SQLite DB to JSON file path
python3 -m mypai_tools.daemon export /path/to/jobs_export.json [--agent-dir /path/to/project]
```

---

## 3. Test Suite Execution Command

```bash
# Execute hermetic Pytest test suite
pytest submodules/omp-mypai/tools/tests/ -v
```
