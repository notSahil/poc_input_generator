"""Unit tests for Post-Update Live Salesforce Validation & Discrepancy Engine."""

from pathlib import Path
import pandas as pd
import pytest

from core.post_validator import evaluate_field_match, reconcile_post_update


class TestFieldMatchingLogic:
    """Tests semantic equivalence between expected and live values."""

    def test_exact_text_match(self):
        status, notes = evaluate_field_match("Site Alpha", "Site Alpha", old_val="Old Site")
        assert status == "VERIFIED_MATCH"
        assert notes == ""

    def test_text_whitespace_and_dash_normalization(self):
        status, notes = evaluate_field_match("Project – Phase 1 ", "Project - Phase 1", old_val="")
        assert status == "VERIFIED_MATCH"

    def test_uk_date_vs_iso_date_match(self):
        status, notes = evaluate_field_match("15/08/2026", "2026-08-15", old_val="2026-01-01")
        assert status == "VERIFIED_MATCH"

    def test_numeric_float_integer_match(self):
        status, notes = evaluate_field_match("100", "100.0", old_val="50", data_type="number")
        assert status == "VERIFIED_MATCH"

    def test_boolean_semantic_match(self):
        status, notes = evaluate_field_match("Yes", "true", old_val="false", data_type="boolean")
        assert status == "VERIFIED_MATCH"

    def test_null_wipe_success(self):
        status, notes = evaluate_field_match("#N/A", "", old_val="Previous Note")
        assert status == "VERIFIED_MATCH"

    def test_null_wipe_failure(self):
        status, notes = evaluate_field_match("#N/A", "Still Has Value", old_val="Previous Note")
        assert status == "NULL_WIPE_FAILED"
        assert "Expected field clear" in notes

    def test_trigger_mutation_detection(self):
        # Value changed in Salesforce, but differs from what we submitted
        status, notes = evaluate_field_match(
            expected_val="Completed",
            live_val="Under Review",
            old_val="Planned",
        )
        assert status == "TRIGGER_MUTATION"
        assert "altered from expected" in notes.lower()

    def test_unmodified_stale_detection(self):
        # Value remained identical to the old pre-update value
        status, notes = evaluate_field_match(
            expected_val="Updated Site Name",
            live_val="Old Site Name",
            old_val="Old Site Name",
        )
        assert status == "UNMODIFIED_STALE"
        assert "remained at pre-update value" in notes


class TestReconcilePostUpdate:
    """Tests end-to-end reconciliation and report file generation."""

    def test_reconciliation_generates_reports(self, tmp_path: Path):
        run_dir = tmp_path / "test_run"
        run_dir.mkdir()

        final_input_df = pd.DataFrame([
            {"Id": "001xx000003AAA1", "Project Reference": "PRJ-001", "Status__c": "Completed", "Milestone__c": "Done"},
            {"Id": "001xx000003AAA2", "Project Reference": "PRJ-002", "Status__c": "Approved", "Milestone__c": "Active"},
        ])

        live_df = pd.DataFrame([
            # Record 1: Status__c matches, Milestone__c was mutated by trigger to 'In Review'
            {"Id": "001xx000003AAA1", "Status__c": "Completed", "Milestone__c": "In Review"},
            # Record 2: 100% match
            {"Id": "001xx000003AAA2", "Status__c": "Approved", "Milestone__c": "Active"},
        ])

        field_changes_df = pd.DataFrame([
            {
                "Id": "001xx000003AAA1",
                "API Field": "Milestone__c",
                "Old Value": "Pending",
                "New Value": "Done",
                "Source Column": "Milestone",
            }
        ])

        result = reconcile_post_update(
            run_dir=run_dir,
            object_name="sitetracker__Project__c",
            live_df=live_df,
            final_input_df=final_input_df,
            field_changes_df=field_changes_df,
            pk_column="Project Reference",
        )

        assert result.total_records_audited == 2
        assert result.total_fields_checked == 4
        assert result.verified_fields_count == 3
        assert result.trigger_mutation_count == 1
        assert not result.all_verified

        # Verify output files were created
        assert (run_dir / "post_update_validation_report.csv").exists()
        assert (run_dir / "post_update_discrepancies.csv").exists()

        # Check discrepancies file content
        disc_df = pd.read_csv(run_dir / "post_update_discrepancies.csv")
        assert len(disc_df) == 1
        assert disc_df.iloc[0]["Record_Id"] == "001xx000003AAA1"
        assert disc_df.iloc[0]["API_Field"] == "Milestone__c"
        assert disc_df.iloc[0]["Status"] == "TRIGGER_MUTATION"

    def test_record_not_found_handling(self, tmp_path: Path):
        run_dir = tmp_path / "test_run_missing"
        run_dir.mkdir()

        final_input_df = pd.DataFrame([
            {"Id": "001xx000003GHOST", "Project Reference": "PRJ-999", "Status__c": "Active"},
        ])
        live_df = pd.DataFrame(columns=["Id", "Status__c"])

        result = reconcile_post_update(
            run_dir=run_dir,
            object_name="sitetracker__Site__c",
            live_df=live_df,
            final_input_df=final_input_df,
        )

        assert result.not_found_count == 1
        assert not result.all_verified
        rep_df = pd.read_csv(run_dir / "post_update_validation_report.csv")
        assert rep_df.iloc[0]["Status"] == "RECORD_NOT_FOUND"
