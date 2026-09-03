"""Integration tests for InputFileEngine."""

from pathlib import Path
import pandas as pd
import pytest
from core.engine import InputFileEngine
from core.models import RunResult


class TestInputFileEngine:
    def test_end_to_end_engine_run(self, mock_environment):
        engine = InputFileEngine("Test Report")
        result: RunResult = engine.run()

        assert result.success is True
        assert result.report_name == "Test Report"
        assert result.total_source_records == 3
        assert result.valid_source_records == 3
        assert result.delta_records == 2  # SITE-001 and SITE-002 changed
        assert result.field_changes_count == 2

        # Verify output files exist
        assert (result.run_dir / "final_input_file.csv").exists()
        assert (result.run_dir / "rollback_file.csv").exists()
        assert (result.run_dir / "field_level_changes.csv").exists()
        assert (result.run_dir / "success_records.csv").exists()
        assert (result.run_dir / "error_records.csv").exists()
        assert (result.run_dir / "skipped_records.csv").exists()
        assert (result.run_dir / "validation_report.csv").exists()
        assert (result.run_dir / "run_summary.txt").exists()

        # Check final_input_file.csv content
        final_df = pd.read_csv(result.run_dir / "final_input_file.csv", dtype=str)
        assert len(final_df) == 2
        assert "Id" in final_df.columns
        assert "Site Reference" in final_df.columns
        assert set(final_df["Site Reference"]) == {"SITE-001", "SITE-002"}

        # Check rollback_file.csv content (mirror payload with pre-change values)
        rollback_df = pd.read_csv(result.run_dir / "rollback_file.csv", dtype=str)
        assert len(rollback_df) == 2
        assert "Id" in rollback_df.columns
        assert "Site Reference" in rollback_df.columns
        assert set(rollback_df["Site Reference"]) == {"SITE-001", "SITE-002"}

        # Check field_level_changes.csv
        changes_df = pd.read_csv(result.run_dir / "field_level_changes.csv", dtype=str)
        assert len(changes_df) == 2
        changed_fields = set(changes_df["API Field"])
        assert "Target_Date__c" in changed_fields
        assert "Name" in changed_fields

        # Check validation_report.csv
        val_df = pd.read_csv(result.run_dir / "validation_report.csv", dtype=str)
        assert len(val_df) == 3  # 3 total source rows evaluated
        assert set(val_df["Final_Status"]) == {"SUCCESS", "SKIPPED"}

    def test_first_occurrence_wins_deduplication(self):
        engine = InputFileEngine("Master Site Listing")
        result = engine.run(skip_validation=True)

        assert result.success is True
        final_df = pd.read_csv(result.run_dir / "final_input_file.csv", dtype=str)
        dup_df = pd.read_csv(result.run_dir / "duplicate_primary_keys.csv", dtype=str)

        # First occurrence of 10006 was processed and included
        assert "10006" in final_df["TM Cell ID"].values

        # Second occurrence of 10006 was quarantined
        assert len(dup_df) == 1
        assert dup_df.iloc[0]["Primary_Key"] == "10006"
        assert dup_df.iloc[0]["Status"] == "DUPLICATE_SKIPPED"



