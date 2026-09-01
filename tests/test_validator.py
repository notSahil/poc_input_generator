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
