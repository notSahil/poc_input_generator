"""Unit tests for Run History discovery."""

from pathlib import Path
from ui.run_history import parse_run_summary, scan_all_runs, scan_guided_runs, scan_manual_runs


def test_parse_run_summary(tmp_path):
    summary_file = tmp_path / "run_summary.txt"
    summary_file.write_text(
        "Report Name: Test\n"
        "Total source records:    10\n"
        "  ✅ SUCCESS (uploaded): 4\n"
        "  🚫 ERRORS (rejected):  2\n"
        "  ⏭️  SKIPPED:            4\n"
        "  🔀 DUPLICATE PKs:      1\n",
        encoding="utf-8"
    )
    metrics = parse_run_summary(summary_file)
    assert metrics["total"] == "10"
    assert metrics["updates"] == "4"
    assert metrics["errors"] == "2"
    assert metrics["skipped"] == "4"
    assert metrics["duplicates"] == "1"


def test_scan_all_runs():
    runs = scan_all_runs()
    assert isinstance(runs, list)
    if runs:
        r = runs[0]
        assert "report" in r
        assert "date" in r
        assert "run_dir" in r
        assert "metrics" in r


def test_render_download_with_confirmation_missing_file(tmp_path):
    from ui.components import render_download_with_confirmation
    class MockContainer:
        pass
    # Should safely return without error when file does not exist
    missing = tmp_path / "nonexistent.csv"
    render_download_with_confirmation(MockContainer(), "Test", missing)


def test_parse_run_summary_manual_format(tmp_path):
    summary_file = tmp_path / "run_summary.txt"
    summary_file.write_text(
        "Ad-Hoc Ingestion Execution Summary\n"
        "Total Source Rows:       50\n"
        "Rows With Changes:       15\n"
        "Validation Errors:       2\n"
        "Skipped (Not in SF):     5\n"
        "Duplicate Primary Keys:  3\n",
        encoding="utf-8"
    )
    metrics = parse_run_summary(summary_file)
    assert metrics["total"] == "50"
    assert metrics["updates"] == "15"
    assert metrics["errors"] == "2"
    assert metrics["skipped"] == "5"
    assert metrics["duplicates"] == "3"


def test_scan_all_runs_discovers_manual_runs(tmp_path, monkeypatch):
    from config import settings
    # Create fake manual run
    manual_dir = tmp_path / "manual_runs" / "sitetracker__Site__c" / "2026-09-12" / "run_22-30-00"
    manual_dir.mkdir(parents=True, exist_ok=True)
    summary_file = manual_dir / "run_summary.txt"
    summary_file.write_text("Total Source Rows: 25\nRows With Changes: 10\n", encoding="utf-8")

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    runs = scan_all_runs()
    assert any(r["report"] == "Ad-Hoc: sitetracker__Site__c" for r in runs)
    matching = next(r for r in runs if r["report"] == "Ad-Hoc: sitetracker__Site__c")
    assert matching["metrics"]["total"] == "25"
    assert matching["metrics"]["updates"] == "10"


def test_scan_guided_runs():
    runs = scan_guided_runs()
    assert isinstance(runs, list)
    for r in runs:
        assert r["type"] == "Guided Report"


def test_scan_manual_runs_filter(tmp_path, monkeypatch):
    from config import settings
    # Create fake manual runs for two objects
    site_dir = tmp_path / "manual_runs" / "sitetracker__Site__c" / "2026-09-12" / "run_10-00-00"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "run_summary.txt").write_text("Total Source Rows: 10\n", encoding="utf-8")

    proj_dir = tmp_path / "manual_runs" / "BT_Project__c" / "2026-09-12" / "run_11-00-00"
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "run_summary.txt").write_text("Total Source Rows: 20\n", encoding="utf-8")

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    # Filter for Site only
    site_runs = scan_manual_runs(object_filter="sitetracker__Site__c")
    assert len(site_runs) == 1
    assert site_runs[0]["object_name"] == "sitetracker__Site__c"

    # Filter for Project only
    proj_runs = scan_manual_runs(object_filter="BT_Project__c")
    assert len(proj_runs) == 1
    assert proj_runs[0]["object_name"] == "BT_Project__c"

    # All Objects
    all_manual = scan_manual_runs(object_filter="All Objects")
    assert len(all_manual) == 2


def test_render_run_details_scope(tmp_path, monkeypatch):
    """Verify _render_run_details accesses r_dir and renders without UnboundLocalError."""
    import json
    from unittest.mock import MagicMock, patch
    from ui.run_history import _render_run_details

    run_dir = tmp_path / "test_run"
    run_dir.mkdir()
    (run_dir / "ingest_progress.json").write_text(json.dumps({
        "status": "COMPLETED",
        "successful_records_overall": 100,
        "failed_records_overall": 0,
        "total_records_overall": 100
    }), encoding="utf-8")

    chosen_run = {
        "report": "Test Report",
        "date": "2026-09-20",
        "time": "10:00:00",
        "run_id": "test_run_123",
        "run_dir": run_dir,
        "metrics": {"total": "100", "updates": "50", "errors": "0", "skipped": "50", "duplicates": "0"}
    }

    mock_st = MagicMock()
    mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()]

    with patch("ui.run_history.st", mock_st), \
         patch("ui.run_history.render_download_with_confirmation"):
        _render_run_details(chosen_run, key_prefix="test")
        # Should complete cleanly without UnboundLocalError
        assert mock_st.subheader.called


def test_render_run_details_with_post_audit_files(tmp_path):
    """Verify _render_run_details renders download options for post-audit files."""
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from ui.run_history import _render_run_details

    run_dir = tmp_path / "guided_audit_run"
    run_dir.mkdir()
    (run_dir / "salesforce_success_records.csv").write_text("Record_Id,Primary_Key\na01001,PK1\n", encoding="utf-8")
    (run_dir / "salesforce_error_records.csv").write_text("Record_Id,Primary_Key,Error\na01002,PK2,LOCKED\n", encoding="utf-8")
    (run_dir / "post_update_validation_report.csv").write_text(
        "Record_Id,Primary_Key,Field_Name,Submitted_Value,Live_Salesforce_Value,Status\n"
        "a01001,PK1,Status__c,Approved,Approved,VERIFIED_MATCH\n",
        encoding="utf-8"
    )
    (run_dir / "post_update_discrepancies.csv").write_text(
        "Record_Id,Primary_Key,Field_Name,Submitted_Value,Live_Salesforce_Value,Status\n",
        encoding="utf-8"
    )

    chosen_run = {
        "report": "Apollo 10G",
        "date": "2026-09-21",
        "time": "11:00:00",
        "run_id": "guided_123",
        "raw_run_id": "guided_123",
        "run_dir": run_dir,
        "metrics": {"total": "10", "updates": "5", "errors": "0", "skipped": "5", "duplicates": "0"}
    }

    mock_st = MagicMock()
    mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n)]

    rendered_files = []
    def mock_render_dl(container, label, file_path, **kwargs):
        rendered_files.append(Path(file_path).name)

    with patch("ui.run_history.st", mock_st), \
         patch("ui.run_history.render_download_with_confirmation", side_effect=mock_render_dl):
        _render_run_details(chosen_run, key_prefix="guided")

        assert "salesforce_success_records.csv" in rendered_files
        assert "salesforce_error_records.csv" in rendered_files
        assert "post_update_validation_report.csv" in rendered_files
        assert "post_update_discrepancies.csv" in rendered_files


def test_render_manual_run_details_with_post_audit_files(tmp_path):
    """Verify _render_manual_run_details renders download options and metrics for post-audit files."""
    import pandas as pd
    from unittest.mock import MagicMock, patch
    from ui.run_history import _render_manual_run_details

    run_dir = tmp_path / "manual_audit_run"
    run_dir.mkdir()
    (run_dir / "salesforce_success_records.csv").write_text("Record_Id,Primary_Key\na01001,Site-001\n", encoding="utf-8")
    (run_dir / "salesforce_error_records.csv").write_text("Record_Id,Primary_Key,Error\na01002,Site-002,ERR\n", encoding="utf-8")
    (run_dir / "post_update_validation_report.csv").write_text(
        "Record_Id,Primary_Key,Field_Name,Submitted_Value,Live_Salesforce_Value,Status\n"
        "a01001,Site-001,Name,Alpha,Alpha,VERIFIED_MATCH\n",
        encoding="utf-8"
    )

    chosen_run = {
        "report": "Ad-Hoc: sitetracker__Site__c",
        "object_name": "sitetracker__Site__c",
        "date": "2026-09-21",
        "time": "11:00:00",
        "run_id": "manual_123",
        "raw_run_id": "manual_123",
        "run_dir": run_dir,
        "metrics": {"total": "5", "updates": "2", "errors": "0", "skipped": "3", "duplicates": "0"},
        "user_name": "test_operator",
        "org_name": "Test Org",
        "operation": "Update",
        "source_filename": "source.csv",
        "source_pk": "Site ID",
        "target_pk": "Name",
        "formatted_date": "21 Sep 2026",
        "formatted_time": "11:00:00 IST",
    }

    mock_st = MagicMock()
    mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n)]

    rendered_files = []
    def mock_render_dl(container, label, file_path, **kwargs):
        rendered_files.append(Path(file_path).name)

    with patch("ui.run_history.st", mock_st), \
         patch("ui.run_history.render_download_with_confirmation", side_effect=mock_render_dl):
        _render_manual_run_details(chosen_run, key_prefix="manual")

        assert "salesforce_success_records.csv" in rendered_files
        assert "salesforce_error_records.csv" in rendered_files
        assert "post_update_validation_report.csv" in rendered_files




