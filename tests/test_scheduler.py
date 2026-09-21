"""Unit tests for core/scheduler.py (timezone math, scheduling, task execution, and circuit breaker)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import zoneinfo

from core.exceptions import SchedulerError
from core.job_store import (
    acquire_lock,
    create_schedule,
    get_schedule,
    init_db,
    update_schedule,
)
from core.engine import InputFileEngine
from core.models import RunResult
from core.scheduler import (
    compute_next_run,
    execute_scheduled_task,
    get_uk_timezone,
    run_due_tasks,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    test_db = tmp_path / "test_sched.db"
    init_db(test_db)
    return test_db


# ==============================================================================
# 1. TIMEZONE & NEXT RUN CALCULATION TESTS
# ==============================================================================

def test_compute_next_run_hourly():
    tz = zoneinfo.ZoneInfo("Europe/London")
    # From 08:10, next minute 30 is 08:30
    from_time = datetime(2026, 9, 15, 8, 10, 0, tzinfo=tz)
    res = compute_next_run(schedule_type="recurring", frequency="hourly", run_at_time="30", from_time=from_time, tz=tz)
    assert res == datetime(2026, 9, 15, 8, 30, 0, tzinfo=tz)

    # From 08:45, next minute 30 is 09:30
    from_time2 = datetime(2026, 9, 15, 8, 45, 0, tzinfo=tz)
    res2 = compute_next_run(schedule_type="recurring", frequency="hourly", run_at_time="30", from_time=from_time2, tz=tz)
    assert res2 == datetime(2026, 9, 15, 9, 30, 0, tzinfo=tz)


def test_compute_next_run_daily():
    tz = zoneinfo.ZoneInfo("Europe/London")
    # From 07:00, daily at 08:30 is today at 08:30
    from_time = datetime(2026, 9, 15, 7, 0, 0, tzinfo=tz)
    res = compute_next_run(schedule_type="recurring", frequency="daily", run_at_time="08:30", from_time=from_time, tz=tz)
    assert res == datetime(2026, 9, 15, 8, 30, 0, tzinfo=tz)

    # From 10:00, daily at 08:30 is tomorrow at 08:30
    from_time2 = datetime(2026, 9, 15, 10, 0, 0, tzinfo=tz)
    res2 = compute_next_run(schedule_type="recurring", frequency="daily", run_at_time="08:30", from_time=from_time2, tz=tz)
    assert res2 == datetime(2026, 9, 16, 8, 30, 0, tzinfo=tz)


def test_compute_next_run_weekly():
    tz = zoneinfo.ZoneInfo("Europe/London")
    # 2026-09-15 is a Tuesday (weekday=1)
    # Next Monday (0) at 09:00 should be 2026-09-21
    from_time = datetime(2026, 9, 15, 12, 0, 0, tzinfo=tz)
    res = compute_next_run(
        schedule_type="recurring",
        frequency="weekly",
        run_at_time="09:00",
        run_on_day="MON",
        from_time=from_time,
        tz=tz,
    )
    assert res == datetime(2026, 9, 21, 9, 0, 0, tzinfo=tz)


def test_compute_next_run_monthly_clamping():
    tz = zoneinfo.ZoneInfo("Europe/London")
    # In January, requesting 31st at 10:00 when baseline is Jan 15 -> Jan 31
    from_time = datetime(2026, 1, 15, 8, 0, 0, tzinfo=tz)
    res = compute_next_run(
        schedule_type="recurring",
        frequency="monthly",
        run_at_time="10:00",
        run_on_day="31",
        from_time=from_time,
        tz=tz,
    )
    assert res == datetime(2026, 1, 31, 10, 0, 0, tzinfo=tz)

    # In February (non-leap year 2026), requesting 31st should clamp to Feb 28
    from_time_feb = datetime(2026, 2, 10, 8, 0, 0, tzinfo=tz)
    res_feb = compute_next_run(
        schedule_type="recurring",
        frequency="monthly",
        run_at_time="10:00",
        run_on_day="31",
        from_time=from_time_feb,
        tz=tz,
    )
    assert res_feb == datetime(2026, 2, 28, 10, 0, 0, tzinfo=tz)


def test_compute_next_run_one_off():
    tz = zoneinfo.ZoneInfo("Europe/London")
    from_time = datetime(2026, 9, 15, 12, 0, 0, tzinfo=tz)

    # Future date
    future_iso = "2026-09-18T14:30:00"
    res = compute_next_run(
        schedule_type="one_off",
        one_off_datetime=future_iso,
        from_time=from_time,
        tz=tz,
    )
    assert res == datetime(2026, 9, 18, 14, 30, 0, tzinfo=tz)

    # Past date
    past_iso = "2026-09-10T14:30:00"
    res_past = compute_next_run(
        schedule_type="one_off",
        one_off_datetime=past_iso,
        from_time=from_time,
        tz=tz,
    )
    assert res_past is None


# ==============================================================================
# 2. EXECUTION & CIRCUIT BREAKER TESTS
# ==============================================================================

def test_execute_scheduled_task_concurrency_skip(db_path: Path):
    """When a resource is locked, execution skips gracefully with SKIPPED status."""
    sched_id = create_schedule(
        name="Locked Test",
        report_name="Apollo 10G",
        profile="sandbox",
        schedule_type="recurring",
        next_run_at=datetime.now(timezone.utc).isoformat(),
        db_path=db_path,
    )

    # Manually lock the resource
    res_key = "Apollo 10G:sandbox:scheduled"
    acquire_lock(res_key, "other_job_id", db_path=db_path)

    res = execute_scheduled_task(sched_id, db_path=db_path)
    assert res["status"] == "SKIPPED"
    assert res["reason"] == "Resource locked"


def test_execute_scheduled_task_no_source_file(db_path: Path, monkeypatch, tmp_path: Path):
    """When no source file exists in the directory, records SKIPPED without failing."""
    sched_id = create_schedule(
        name="Missing Source Test",
        report_name="Apollo 10G",
        profile="sandbox",
        schedule_type="recurring",
        next_run_at=datetime.now(timezone.utc).isoformat(),
        db_path=db_path,
    )

    # Mock empty source dir
    empty_source_dir = tmp_path / "empty_source"
    empty_source_dir.mkdir(parents=True)

    fake_cfg = {
        "folders": {
            "work_dir": str(tmp_path),
            "source_dir": "empty_source",
        }
    }

    with patch("core.config_loader.YamlConfigLoader.load", return_value=fake_cfg):
        res = execute_scheduled_task(sched_id, db_path=db_path)
        assert res["status"] == "SKIPPED"
        assert res["reason"] == "No source file"


def test_execute_scheduled_task_success(db_path: Path, monkeypatch, tmp_path: Path):
    """Mock happy path: live SOQL fetch and engine run completes successfully."""
    sched_id = create_schedule(
        name="Happy Path Run",
        report_name="Apollo 10G",
        profile="sandbox",
        schedule_type="recurring",
        next_run_at=datetime.now(timezone.utc).isoformat(),
        db_path=db_path,
    )

    # Create dummy source dir with file
    src_dir = tmp_path / "source"
    src_dir.mkdir(parents=True)
    (src_dir / "input.xlsx").write_text("dummy")

    fake_cfg = {
        "folders": {
            "work_dir": str(tmp_path),
            "source_dir": "source",
            "sitetracker_dir": "sitetracker",
            "runs_dir": "runs",
            "archive_dir": "archive",
        }
    }

    mock_run_result = RunResult(
        success=True,
        report_name="Apollo 10G",
        run_dir=tmp_path / "run_1",
        total_source_records=10,
        delta_records=3,
        error_records=0,
        skipped_records=7,
    )

    with patch("core.config_loader.YamlConfigLoader.load", return_value=fake_cfg):
        with patch("core.scheduler.fetch_sitetracker_data", return_value=Path("/tmp/st.csv")):
            with patch.object(InputFileEngine, "run", return_value=mock_run_result):
                res = execute_scheduled_task(sched_id, db_path=db_path)
                assert res["status"] == "SUCCESS"
                assert res["total_records"] == 10
                assert res["successful_records"] == 3

    # Verify schedule recorded last run
    updated = get_schedule(sched_id, db_path=db_path)
    assert updated["last_run_status"] == "SUCCESS"
    assert updated["total_runs"] == 1
    assert updated["consecutive_failures"] == 0


def test_one_off_schedule_auto_deactivates(db_path: Path, tmp_path: Path):
    """One-off schedules must auto-deactivate after execution."""
    future_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    sched_id = create_schedule(
        name="One-off Auto Deactivate",
        report_name="Apollo 10G",
        profile="sandbox",
        schedule_type="one_off",
        one_off_datetime=future_time,
        next_run_at=future_time,
        db_path=db_path,
    )

    src_dir = tmp_path / "source"
    src_dir.mkdir(parents=True)
    (src_dir / "input.xlsx").write_text("dummy")

    fake_cfg = {
        "folders": {
            "work_dir": str(tmp_path),
            "source_dir": "source",
            "sitetracker_dir": "sitetracker",
            "runs_dir": "runs",
            "archive_dir": "archive",
        }
    }


    mock_run_result = RunResult(
        success=True,
        report_name="Apollo 10G",
        run_dir=tmp_path / "run_1",
        total_source_records=5,
        delta_records=1,
    )

    with patch("core.config_loader.YamlConfigLoader.load", return_value=fake_cfg):
        with patch("core.scheduler.fetch_sitetracker_data"):
            with patch.object(InputFileEngine, "run", return_value=mock_run_result):
                execute_scheduled_task(sched_id, db_path=db_path)

    sched = get_schedule(sched_id, db_path=db_path)
    assert sched["is_active"] == 0  # Auto-deactivated!
    assert sched["last_run_status"] == "SUCCESS"


def test_circuit_breaker_auto_pauses(db_path: Path):
    """Schedules with consecutive failures >= max_retries must be auto-paused."""
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    sched_id = create_schedule(
        name="Failing Schedule",
        report_name="Apollo 10G",
        profile="sandbox",
        schedule_type="recurring",
        next_run_at=past_time,
        max_retries=3,
        db_path=db_path,
    )
    # Set consecutive_failures to 3
    update_schedule(sched_id, consecutive_failures=3, db_path=db_path)

    results = run_due_tasks(db_path=db_path)
    assert len(results) == 1
    assert results[0]["status"] == "CIRCUIT_BROKEN"

    # Schedule should now be paused
    sched = get_schedule(sched_id, db_path=db_path)
    assert sched["is_active"] == 0
