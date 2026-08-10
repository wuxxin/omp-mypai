#!/usr/bin/env python3
"""Unit tests for Heartbeat Daemon, Executors, SQLite DB, and cron_mcp FastMCP Server."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from mypai_tools.cron_mcp import (
    cron_add_job,
    cron_export_jobs,
    cron_import_jobs,
    cron_list_jobs,
    cron_modify_job,
    cron_pause_job,
    cron_remove_job,
    cron_resume_job,
)
from mypai_tools.db import (
    _get_db_session,
    normalize_cron_expression,
    substitute_env_vars,
)
from mypai_tools.executors.http_executor import execute_http_job
from mypai_tools.executors.python_executor import execute_python_job
from mypai_tools.executors.rpc_executor import execute_rpc_job
from mypai_tools.executors.shell_executor import build_full_command, execute_shell_job
from mypai_tools.heartbeat import execute_job
from mypai_tools.models import CronJobModel


class TestCronDbAndMacroSubstitution(unittest.TestCase):
    """Test crontab normalization and #[VARNAME] macro substitution."""

    def test_normalize_cron_expression(self) -> None:
        """Test standard 5-field cron normalization."""
        expr = "0 8 * * 0"
        normalized = normalize_cron_expression(expr)
        self.assertIsNotNone(normalized)
        parts = normalized.split()
        self.assertEqual(len(parts), 5)

    def test_substitute_env_vars_process_env(self) -> None:
        """Test #[VARNAME] expansion using os.environ."""
        with patch.dict(os.environ, {"TEST_MYPAI_VAR": "secret_value_123"}):
            raw_text = "Connecting to #[TEST_MYPAI_VAR]..."
            res = substitute_env_vars(raw_text)
            self.assertEqual(res, "Connecting to secret_value_123...")

    def test_substitute_env_vars_internal_vars(self) -> None:
        """Test #[_RETURNCODE], #[_STDOUT], #[_RESULT] macro expansion."""
        raw_text = "Exit code #[_RETURNCODE]: #[_STDOUT] (Result: #[_RESULT])"
        extra = {
            "_RETURNCODE": 0,
            "_STDOUT": "System OK",
            "_RESULT": {"status": "success"},
        }
        res = substitute_env_vars(raw_text, extra_vars=extra)
        self.assertEqual(
            res, 'Exit code 0: System OK (Result: {"status": "success"})'
        )

    def test_substitute_env_vars_nested_structures(self) -> None:
        """Test recursive macro substitution in dicts and lists."""
        with patch.dict(os.environ, {"MY_HOST": "localhost"}):
            payload = {
                "url": "http://#[MY_HOST]:8080/api",
                "params": ["#[MY_HOST]", "status"],
            }
            res = substitute_env_vars(payload)
            self.assertEqual(res["url"], "http://localhost:8080/api")
            self.assertEqual(res["params"], ["localhost", "status"])


class TestShellExecutor(unittest.IsolatedAsyncioTestCase):
    """Test Shell Job Executor command building, subprocess env inheritance, and macro formatting."""

    def test_build_full_command(self) -> None:
        """Test building full shell command with positional args and flag kwargs."""
        cmd = build_full_command(
            "python3",
            args_val=["-m", "mypai_tools.input_spooler"],
            kwargs_val={"inbox": "~/Inbox", "quiescence-sec": 10, "verbose": True},
        )
        self.assertIn("python3", cmd)
        self.assertIn("-m", cmd)
        self.assertIn("mypai_tools.input_spooler", cmd)
        self.assertIn("--inbox", cmd)
        self.assertIn("--quiescence-sec 10", cmd)
        self.assertIn("--verbose", cmd)

    async def test_execute_shell_job_success(self) -> None:
        """Test executing shell job with #[_RETURNCODE] and #[_STDOUT] in output_prompt."""
        job = {
            "name": "Shell Test Job",
            "type": "shell",
            "action": "echo",
            "args": ["Hello Unit Test"],
            "output_prompt": "Output (code #[_RETURNCODE]): #[_STDOUT]",
        }
        res = await execute_shell_job(job)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("Output (code 0): Hello Unit Test", res["output"])


class TestPythonExecutor(unittest.IsolatedAsyncioTestCase):
    """Test Python Job Executor lambda evaluation, args/kwargs, and #[_RESULT] formatting."""

    async def test_execute_python_lambda(self) -> None:
        """Test executing Python lambda expression."""
        job = {
            "name": "Python Lambda Test",
            "type": "python",
            "action": "lambda args, kwargs: {'status': 'ok', 'count': len(args), 'env': kwargs.get('env')}",
            "args": ["a", "b", "c"],
            "kwargs": {"env": "test"},
            "output_prompt": "Lambda Result: #[_RESULT]",
        }
        res = await execute_python_job(job)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], {"status": "ok", "count": 3, "env": "test"})
        self.assertIn(
            'Lambda Result: {"status": "ok", "count": 3, "env": "test"}',
            res["output"],
        )


class TestHttpAndRpcExecutors(unittest.IsolatedAsyncioTestCase):
    """Test HTTP and RPC job executors."""

    @patch("httpx.AsyncClient.request")
    async def test_execute_http_job(self, mock_request) -> None:
        """Test HTTP job payload and header extraction."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "reflected"}
        mock_request.return_value = mock_resp

        job = {
            "name": "HTTP Test Job",
            "type": "http",
            "action": "POST",
            "url": "http://localhost:8888/v1/reflect",
            "kwargs": {
                "query": "test reflection",
                "headers": {"Authorization": "Bearer token123"},
            },
        }
        res = await execute_http_job(job)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["http_code"], 200)
        self.assertIn("reflected", res["output"])

    async def test_execute_rpc_job_prompt_extraction(self) -> None:
        """Test RPC prompt extraction from kwargs.prompt."""
        job = {
            "name": "RPC Test Job",
            "type": "rpc",
            "action": "prompt",
            "kwargs": {"prompt": "Perform work sweep audit"},
        }
        # mock_client context
        with patch("mypai_tools.executors.rpc_executor.RpcClient") as mock_rpc_class:
            mock_client = MagicMock()
            mock_rpc_class.return_value.__enter__.return_value = mock_client
            mock_res = MagicMock()
            mock_res.require_assistant_text.return_value = "Audit complete."
            mock_client.prompt_and_wait.return_value = mock_res

            res = await execute_rpc_job(job)
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["output"], "Audit complete.")
            mock_client.prompt_and_wait.assert_called_once_with(
                "Perform work sweep audit", timeout=120.0
            )


class TestFastMcpCronTools(unittest.TestCase):
    """Test FastMCP cron_mcp CRUD tool operations and project DB persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="mypai_cron_test_")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cron_add_list_modify_remove_lifecycle(self) -> None:
        """Test full CRUD lifecycle of cron tasks via FastMCP tool wrappers."""
        # 1. Add job
        add_res = cron_add_job(
            name="Unit Test Schedule Job",
            cron_expression="0 8 * * 0",
            type="rpc",
            action="prompt",
            kwargs={"prompt": "Sunday morning audit"},
            project_dir=self.temp_dir,
        )
        self.assertIn(
            add_res["status"], ("scheduled", "scheduled_heartbeat_offline")
        )
        job_data = add_res["job"]
        job_id = job_data["id"]

        # 2. List jobs
        jobs = cron_list_jobs(project_dir=self.temp_dir)
        self.assertTrue(any(j["id"] == job_id for j in jobs))

        # 3. Pause job
        pause_res = cron_pause_job(job_id=job_id, project_dir=self.temp_dir)
        self.assertEqual(pause_res["status"], "paused")
        self.assertFalse(pause_res["job"]["enabled"])

        # 4. Resume job
        resume_res = cron_resume_job(job_id=job_id, project_dir=self.temp_dir)
        self.assertEqual(resume_res["status"], "resumed")
        self.assertTrue(resume_res["job"]["enabled"])

        # 5. Modify job
        mod_res = cron_modify_job(
            job_id=job_id,
            name="Modified Schedule Job",
            output_prompt="Output context header:",
            project_dir=self.temp_dir,
        )
        self.assertEqual(mod_res["status"], "modified")
        self.assertEqual(mod_res["job"]["name"], "Modified Schedule Job")
        self.assertEqual(mod_res["job"]["output_prompt"], "Output context header:")

        # 6. Delete job
        rem_res = cron_remove_job(job_id=job_id, project_dir=self.temp_dir)
        self.assertEqual(rem_res["status"], "cancelled")

        # Verify job no longer in list
        post_jobs = cron_list_jobs(project_dir=self.temp_dir)
        self.assertFalse(any(j["id"] == job_id for j in post_jobs))

    def test_cron_export_and_import_roundtrip(self) -> None:
        """Test exporting cron jobs to JSON file and re-importing into SQLite DB."""
        # Add job
        cron_add_job(
            name="Export Test Job",
            cron_expression="*/15 * * * *",
            type="shell",
            action="echo",
            args=["export test"],
            project_dir=self.temp_dir,
        )

        json_file = os.path.join(self.temp_dir, "jobs_export.json")
        export_res = cron_export_jobs(json_file, project_dir=self.temp_dir)
        self.assertEqual(export_res["status"], "exported")
        self.assertTrue(os.path.isfile(json_file))

        # Verify JSON contents
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("jobs", data)
        self.assertTrue(any(j["name"] == "Export Test Job" for j in data["jobs"]))

        # Import into fresh directory
        fresh_dir = tempfile.mkdtemp(prefix="mypai_cron_fresh_")
        try:
            import_res = cron_import_jobs(json_file, project_dir=fresh_dir)
            self.assertEqual(import_res["status"], "imported")
            self.assertGreaterEqual(import_res["imported_count"], 1)

            fresh_jobs = cron_list_jobs(project_dir=fresh_dir)
            self.assertTrue(any(j["name"] == "Export Test Job" for j in fresh_jobs))
        finally:
            import shutil

            shutil.rmtree(fresh_dir, ignore_errors=True)


class TestHeartbeatTelemetryUpdate(unittest.IsolatedAsyncioTestCase):
    """Test execute_job telemetry recording in SQLite DB."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="mypai_telemetry_test_")

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_execute_job_telemetry_recording(self) -> None:
        """Test executing job updates last_start, last_stop, last_runtime, last_returncode, total_calls."""
        add_res = cron_add_job(
            name="Telemetry Test Job",
            cron_expression="* * * * *",
            type="python",
            action="lambda args, kwargs: 42",
            project_dir=self.temp_dir,
        )
        job_data = add_res["job"]

        # Execute job
        res = await execute_job(job_data, project_dir=self.temp_dir)
        self.assertEqual(res["status"], "success")

        # Verify DB telemetry
        session = _get_db_session(self.temp_dir)
        try:
            db_job = (
                session.query(CronJobModel).filter_by(id=job_data["id"]).first()
            )
            self.assertIsNotNone(db_job)
            self.assertTrue(bool(db_job.last_start))
            self.assertTrue(bool(db_job.last_stop))
            self.assertGreater(db_job.last_runtime, 0.0)
            self.assertEqual(db_job.last_returncode, 0)
            self.assertEqual(db_job.total_calls, 1)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
