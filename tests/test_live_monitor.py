"""Unit tests for active job detection, telemetry banner, and live monitor."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.job_store import create_job, get_active_jobs, init_db, mark_job_running
from ui.components import render_active_job_banner


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    test_db = tmp_path / "test_monitor.db"
    init_db(test_db)
    return test_db


def test_no_active_jobs_returns_false(db_path: Path, monkeypatch):
    """When no jobs are running, render_active_job_banner returns False."""
    monkeypatch.setattr("config.settings.JOBS_DB_PATH", db_path)
    go_mock = MagicMock()
    assert render_active_job_banner(go_mock) is False


def test_active_job_detected_and_rendered(db_path: Path, tmp_path: Path, monkeypatch):
    """When a job is RUNNING and active on disk, banner renders and returns True."""
    monkeypatch.setattr("config.settings.JOBS_DB_PATH", db_path)
    run_dir = tmp_path / "run_test"
    run_dir.mkdir(parents=True)

    job_id = create_job(
        run_dir=run_dir,
        report_name="Apollo 10G",
        profile="sandbox",
        target_object="BT_Project__c",
        total_records=100,
        db_path=db_path,
    )
    mark_job_running(job_id, db_path=db_path)

    active_jobs = get_active_jobs(db_path=db_path)
    assert len(active_jobs) == 1
    assert active_jobs[0]["id"] == job_id
    assert active_jobs[0]["report_name"] == "Apollo 10G"

    go_mock = MagicMock()
    with patch("salesforce.job_manager.is_job_active", return_value=True):
        with patch("salesforce.job_manager.get_job_progress", return_value={
            "status": "RUNNING",
            "current_chunk": 2,
            "total_chunks": 5,
            "processed_records_overall": 40,
            "total_records_overall": 100,
            "current_object": "BT_Project__c",
        }):
            rendered = render_active_job_banner(go_mock)
            assert rendered is True


def test_stale_job_not_rendered(db_path: Path, tmp_path: Path, monkeypatch):
    """If a job is in DB as RUNNING but is_job_active returns False (stale/crashed), banner ignores it."""
    monkeypatch.setattr("config.settings.JOBS_DB_PATH", db_path)
    run_dir = tmp_path / "run_dead"
    run_dir.mkdir(parents=True)

    job_id = create_job(
        run_dir=run_dir,
        report_name="Apollo 10G",
        db_path=db_path,
    )
    mark_job_running(job_id, db_path=db_path)

    go_mock = MagicMock()
    with patch("salesforce.job_manager.is_job_active", return_value=False):
        rendered = render_active_job_banner(go_mock)
        assert rendered is False


def test_live_monitor_module_compiles():
    """Verify ui/live_monitor.py imports without syntax or module errors."""
    import ui.live_monitor
    assert hasattr(ui.live_monitor, "render")
