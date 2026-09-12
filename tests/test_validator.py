"""Unit tests for InputValidator."""

from pathlib import Path
import pytest
from core.validator import InputValidator


class TestInputValidator:
    def test_valid_inputs_pass(self, mock_environment):
        validator = InputValidator("Test Report")
        result = validator.validate_all()
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_missing_source_file_fails(self, mock_environment):
        # Delete source file
        source_dir = mock_environment["data_dir"] / "Test_Report" / "input" / "source"
        for f in source_dir.glob("*"):
            f.unlink()

        validator = InputValidator("Test Report")
        result = validator.validate_all()
        assert result.is_valid is False
        assert any("No files found in Source directory" in e for e in result.errors)

    def test_multiple_files_fails(self, mock_environment):
        source_dir = mock_environment["data_dir"] / "Test_Report" / "input" / "source"
        (source_dir / "second_file.xlsx").write_text("dummy")

        validator = InputValidator("Test Report")
        result = validator.validate_all()
        assert result.is_valid is False
        assert any("must contain exactly 1 file" in e for e in result.errors)

    def test_subdirectories_ignored(self, mock_environment):
        source_dir = mock_environment["data_dir"] / "Test_Report" / "input" / "source"
        archive_dir = source_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / "old_archived_file.xlsx").write_text("dummy")

        validator = InputValidator("Test Report")
        result = validator.validate_all()
        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_source_file_with_api_names_passes(self, mock_environment):
        """Verify that a source file using Salesforce API field names (like rollback_file.csv) passes validation."""
        import pandas as pd
        source_dir = mock_environment["data_dir"] / "Test_Report" / "input" / "source"
        for f in source_dir.glob("*"):
            f.unlink()

        # Write CSV with API names instead of source column names
        df = pd.DataFrame([
            {"Id": "a1e000000000001", "Site Reference": "SITE-001", "Target_Date__c": "2026-09-12", "Name": "Updated Site"}
        ])
        df.to_csv(source_dir / "rollback_file.csv", index=False)

        validator = InputValidator("Test Report")
        result = validator.validate_all()
        assert result.is_valid is True
        assert len(result.errors) == 0

