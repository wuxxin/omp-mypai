# MyPAI Daemon CLI Command Usage (`cli-usage.md`)

## Executive Summary

`mypai_daemon` can be launched continuously as a background process or executed single-pass via the command line interface.

---

## 1. Daemon Launch Commands

```bash
# Continuous background daemon mode (default port 52080)
python3 -m mypai_tools.daemon [--project-dir /path/to/project] [--port 52080]

# Execute single-pass for all active cron jobs and exit
python3 -m mypai_tools.daemon --once [--project-dir /path/to/project]
```

### Command Flags
- `--project-dir`: Target workspace directory path. Defaults to current working directory (`$PWD`).
- `--port`: HTTP REST and WebSocket server port. Defaults to `52080`.
- `--once`: Executes pending cron jobs once and exits immediately without running the continuous web server or scheduler.

---

## 2. Cron Job Import & Export Commands

```bash
# Import cron jobs from specified JSON file path into project SQLite DB
python3 -m mypai_tools.daemon import /path/to/jobs.json [--project-dir /path/to/project]

# Export all registered jobs from project SQLite DB to JSON file path
python3 -m mypai_tools.daemon export /path/to/jobs_export.json [--project-dir /path/to/project]
```

---

## 3. Test Suite Execution Command

```bash
# Execute hermetic Pytest test suite
pytest submodules/omp-mypai/tools/tests/ -v
```
