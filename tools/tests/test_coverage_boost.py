"""Additional unit tests boosting coverage across input_spooler, signal_client, cron_mcp, and daemon main."""

from pathlib import Path
from unittest.mock import patch

import pytest
from mypai_tools import cron_mcp
from mypai_tools.daemon.main import main as daemon_main
from mypai_tools.input_spooler import (
    compute_content_hash,
    load_processed_hashes,
    parse_sidecar,
    save_processed_hashes,
)
from mypai_tools.signal_client import SignalClient


def test_input_spooler_helpers(tmp_path: Path) -> None:
    # 1. Content Hash & Processed Hashes Persistence
    test_file = tmp_path / "test_drop.txt"
    test_file.write_text("Hello Spooler Test", encoding="utf-8")

    h = compute_content_hash(test_file)
    assert len(h) == 64  # SHA256 hex string

    state_file = tmp_path / "processed_hashes.json"
    save_processed_hashes(state_file, {h})
    loaded = load_processed_hashes(state_file)
    assert h in loaded

    # 2. Sidecar Parser (.md format)
    sidecar_file = tmp_path / "test_drop.txt.md"
    sidecar_file.write_text("title: Custom Title\ntype: audio\n", encoding="utf-8")

    meta, sidecar_path = parse_sidecar(test_file)
    assert meta["title"] == "Custom Title"
    assert meta["type"] == "audio"
    assert sidecar_path == sidecar_file


def test_signal_client_attachments_and_errors(tmp_path: Path) -> None:
    client = SignalClient(account="+15550001111", allowed_sender="+15559992222")

    att_file = tmp_path / "sample.png"
    att_file.write_bytes(b"\x89PNG\r\n\x1a\nTestImageData")

    with patch.object(client, "_http_request", return_value={"status": "sent"}) as mock_req:
        res = client.send_message(
            recipient="+15559992222",
            text="Here is attachment",
            attachments=[str(att_file)],
        )
        assert res == {"status": "sent"}
        call_kwargs = mock_req.call_args[1]
        assert "base64_attachments" in call_kwargs["data"]
        assert len(call_kwargs["data"]["base64_attachments"]) == 1


def test_daemon_main_once_flag(tmp_path: Path) -> None:
    with patch("sys.argv", ["daemon", "once", "--project-dir", str(tmp_path)]):
        with pytest.raises(SystemExit) as exc_info:
            daemon_main()
        assert exc_info.value.code == 0


def test_access_log_filter() -> None:
    import logging

    from mypai_tools.daemon.main import AccessLogFilter

    filter_non_verbose = AccessLogFilter(verbose=False)
    filter_verbose = AccessLogFilter(verbose=True)

    record_status = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1 - "GET /api/v1/session/status HTTP/1.1" 200 OK',
        args=(),
        exc_info=None,
    )

    record_other = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='127.0.0.1 - "POST /api/v1/session/prompt HTTP/1.1" 200 OK',
        args=(),
        exc_info=None,
    )

    # In non-verbose mode: status route is silenced, other routes pass
    assert filter_non_verbose.filter(record_status) is False
    assert filter_non_verbose.filter(record_other) is True

    # In verbose mode: all routes pass
    assert filter_verbose.filter(record_status) is True
    assert filter_verbose.filter(record_other) is True


def test_cron_mcp_all_tools_http_branch(tmp_path: Path) -> None:
    proj_dir = str(tmp_path)
    fake_job = {
        "id": "mock_id",
        "name": "T1",
        "cron": "0 0 * * *",
        "kind": "omp",
        "action": "prompt",
        "enabled": True,
    }

    with patch.object(cron_mcp, "_daemon_http_request", return_value=[fake_job]):
        res_list = cron_mcp.cron_list_jobs(project_dir=proj_dir)
        assert res_list == [fake_job]

    fake_dict_resp = {"status": "ok", "job": fake_job}
    with patch.object(cron_mcp, "_daemon_http_request", return_value=fake_dict_resp):
        res_mod = cron_mcp.cron_modify_job(job_id="mock_id", name="T1 Mod", project_dir=proj_dir)
        assert res_mod == fake_dict_resp

        res_dis = cron_mcp.cron_disable_job(job_id="mock_id", project_dir=proj_dir)
        assert res_dis == fake_dict_resp

        res_en = cron_mcp.cron_enable_job(job_id="mock_id", project_dir=proj_dir)
        assert res_en == fake_dict_resp

        res_rm = cron_mcp.cron_remove_job(job_id="mock_id", project_dir=proj_dir)
        assert res_rm == fake_dict_resp

        res_en_all = cron_mcp.cron_enable_all_jobs(project_dir=proj_dir)
        assert res_en_all == fake_dict_resp

        res_dis_all = cron_mcp.cron_disable_all_jobs(project_dir=proj_dir)
        assert res_dis_all == fake_dict_resp

        res_stat = cron_mcp.cron_get_status(project_dir=proj_dir)
        assert res_stat == fake_dict_resp


def test_daemon_import_export_cli(tmp_path: Path) -> None:
    proj_dir = str(tmp_path)
    import_file = tmp_path / "jobs_import.json"
    import_file.write_text('[{"name": "CLI_Cron", "description": "Test Title", "cron": "0 * * * *"}]', encoding="utf-8")

    with patch("mypai_tools.cron_mcp._daemon_http_request", return_value={"error": "offline"}):
        # Test import subcommand (first import creates new job with generated ID)
        with patch("sys.argv", ["mypai_daemon", "import", str(import_file), "--project-dir", proj_dir]):
            with pytest.raises(SystemExit) as exc_info:
                daemon_main()
            assert exc_info.value.code == 0

        # Test export subcommand
        export_file = tmp_path / "jobs_export.json"
        with patch("sys.argv", ["mypai_daemon", "export", str(export_file), "--project-dir", proj_dir]):
            with pytest.raises(SystemExit) as exc_info:
                daemon_main()
            assert exc_info.value.code == 0
        assert export_file.exists()

        # Re-importing exported file (with assigned IDs) updates existing job, avoiding duplicates
        with patch("sys.argv", ["mypai_daemon", "import", str(export_file), "--project-dir", proj_dir]):
            with pytest.raises(SystemExit) as exc_info:
                daemon_main()
            assert exc_info.value.code == 0

        # Verify only 1 job exists in database
        from mypai_tools.persistence import CronJobModel, get_db_session
        db = get_db_session(proj_dir)
        try:
            jobs = db.query(CronJobModel).all()
            assert len(jobs) == 1
            assert jobs[0].name == "CLI_Cron"
            assert jobs[0].description == "Test Title"
        finally:
            db.close()


