"""Unit tests for Run History discovery."""

from pathlib import Path
from ui.run_history import parse_run_summary, scan_all_runs


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


