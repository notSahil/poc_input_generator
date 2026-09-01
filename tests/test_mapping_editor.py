"""Unit tests for MappingEditor."""

from pathlib import Path
import pytest
from core.mapping_editor import MappingEditor


class TestMappingEditor:
    def test_load_and_list_reports(self, mock_environment):
        editor = MappingEditor()
        df = editor.load()
        assert not df.empty
        reports = editor.get_reports()
        assert "Test Report" in reports

    def test_add_and_save_row(self, mock_environment):
        editor = MappingEditor()
        editor.load()

        new_row = {
            "Report Name": "New Report",
            "Object Name": "Project",
            "Source File Column Name": "Project Ref",
            "Sitetracker Field Name": "Proj_Ref__c",
            "API Name": "Proj_Ref__c",
            "Data Type": "text",
            "Primary Key?": "Yes"
        }
        editor.add_row(new_row)
        backup_path = editor.save(reason="test_add")

        assert backup_path.exists()
        history = editor.list_history()
        assert len(history) >= 1

        # Reload editor and check new row exists
        editor2 = MappingEditor()
        df2 = editor2.load()
        assert "New Report" in editor2.get_reports()

    def test_restore_version(self, mock_environment):
        editor = MappingEditor()
        editor.load()

        # Make a backup
        backup_path = editor.save(reason="baseline")

        # Mutate data
        editor.add_row({
            "Report Name": "Temporary Report",
            "Object Name": "Temp",
            "Source File Column Name": "A",
            "Sitetracker Field Name": "B",
            "API Name": "C",
            "Data Type": "text",
            "Primary Key?": "No"
        })
        editor.save(reason="mutated")
        assert "Temporary Report" in editor.get_reports()

        # Restore from baseline backup
        editor.restore_version(backup_path)
        assert "Temporary Report" not in editor.get_reports()
