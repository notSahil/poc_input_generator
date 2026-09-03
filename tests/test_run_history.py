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
