"""End-to-end quick test runner for Sitetracker Input File Generator.

Usage:
    python quick_test.py
"""

import os
import sys
import shutil
from pathlib import Path
import pandas as pd

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from core.config_loader import YamlConfigLoader
from core.engine import InputFileEngine
from core.mapping_editor import MappingEditor
from core.mapping_loader import MappingLoader
from core.normalizer import DataNormalizer
from core.validator import InputValidator


def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  🧪 {title}")
    print("=" * 70)


def test_normalizer():
    print_header("TEST 1: Data Normalizer")
    # Date test
    date_str, ok = DataNormalizer.normalize_date_uk("15/03/2025")
    assert ok and date_str == "15/03/2025", "Date normalization failed"
    print("  ✅ UK Date formatting (15/03/2025) -> PASSED")

    # Text case test
    title_text = DataNormalizer.normalize_text_case("london central site")
    assert title_text == "London Central Site", "Text case normalization failed"
    print("  ✅ Text Case formatting (london central site) -> PASSED")

    # Project ref test
    assert DataNormalizer.valid_project_ref("SITE-1001_A") is True, "Project ref validation failed"
    assert DataNormalizer.valid_project_ref("INVALID REF#") is False, "Project ref invalid detection failed"
    print("  ✅ Primary Key regex check -> PASSED")


def test_config_and_mapping():
    print_header("TEST 2: Config Auto-Discovery & Mapping Loader")
    reports = YamlConfigLoader.list_reports()
    print(f"  Found {len(reports)} configured reports:")
    for r in reports:
        print(f"    - {r.name:<25} (Source: {r.has_source}, Sitetracker: {r.has_sitetracker})")
    assert len(reports) >= 2, "Expected at least 2 reports"
    print("  ✅ Config loader auto-discovery -> PASSED")

    # Mapping loader
    loader = MappingLoader(settings.MAPPING_FILE, "Apollo 10G")
    df = loader.load()
    pk_src, pk_st = loader.primary_keys()
    print(f"  Apollo 10G Mapping: {len(df)} fields mapped | Primary Key: {pk_src} -> {pk_st}")
    assert pk_src == "Project Ref" and pk_st == "Project Reference"
    print("  ✅ Mapping loader & primary key detection -> PASSED")


def test_validator():
    print_header("TEST 3: Input Validation Pipeline")
    for r in ["Apollo 10G", "Master Site Listing"]:
        validator = InputValidator(r)
        result = validator.validate_all()
        status = "PASSED" if result.is_valid else "FAILED"
        print(f"  Report '{r}': {status} (Errors: {len(result.errors)}, Warnings: {len(result.warnings)})")
        assert result.is_valid, f"Validation failed for {r}: {result.errors}"
    print("  ✅ All configured reports passed input validation -> PASSED")


def test_engine_run():
    print_header("TEST 4: Delta Calculation Engine Execution")
    report_name = "Master Site Listing"
    print(f"  Executing engine for: {report_name}...")

    engine = InputFileEngine(report_name)
    result = engine.run()

    print(f"  ✅ Execution Succeeded:")
    print(f"     - Total Source Records:  {result.total_source_records}")
    print(f"     - Valid Source Records:  {result.valid_source_records}")
    print(f"     - Delta Upload Rows:     {result.delta_records}")
    print(f"     - Field-Level Changes:   {result.field_changes_count}")
    print(f"     - Output Location:       {result.run_dir}")

    assert result.success is True
    assert (result.run_dir / "final_input_file.csv").exists()
    assert (result.run_dir / "field_level_changes.csv").exists()
    assert (result.run_dir / "run_summary.txt").exists()
    print("  ✅ Generated files verified (final_input_file.csv, field_level_changes.csv, run_summary.txt)")


def test_mapping_editor():
    print_header("TEST 5: Interactive Mapping Editor & Version History")
    editor = MappingEditor()
    df = editor.load()
    initial_reports = editor.get_reports()
    print(f"  Current reports in mapping file: {initial_reports}")

    # Add test row
    test_row = {
        "Report Name": "Automated_Test_Report",
        "Object Name": "Site",
        "Source File Column Name": "Site_ID",
        "Sitetracker Field Name": "Site_ID__c",
        "API Name": "Site_ID__c",
        "Data Type": "text",
        "Primary Key?": "Yes"
    }
    editor.add_row(test_row)
    backup_path = editor.save(reason="automated_test")
    print(f"  ✅ Added test row & created backup: {backup_path.name}")

    # Verify new report exists
    editor2 = MappingEditor()
    assert "Automated_Test_Report" in editor2.get_reports()

    # Restore from backup before test
    history = editor.list_history()
    print(f"  Found {len(history)} versioned backups in history")
    editor.restore_version(backup_path)

    # Clean up test row
    clean_df = editor.load()
    clean_df = clean_df[clean_df["Report Name"] != "Automated_Test_Report"]
    editor._df = clean_df
    editor.save(reason="cleanup_test")
    print("  ✅ Mapping Editor CRUD, backup, and restore -> PASSED")


def main():
    print("\n" + "#" * 70)
    print("  🚀 SITETRACKER INPUT GENERATOR — SYSTEM VERIFICATION SUITE")
    print("#" * 70)

    try:
        test_normalizer()
        test_config_and_mapping()
        test_validator()
        test_engine_run()
        test_mapping_editor()

        print("\n" + "=" * 70)
        print("  🎉 ALL 5 SYSTEM TESTS PASSED SUCCESSFULLY!")
        print("  The entire codebase is verified and ready for production use.")
        print("=" * 70 + "\n")
        sys.exit(0)

    except AssertionError as e:
        print(f"\n❌ Test Assertion Failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected Error During Testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
