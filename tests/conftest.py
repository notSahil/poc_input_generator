"""Shared pytest fixtures."""

import os
import shutil
import sys
from pathlib import Path
import pytest
import yaml

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def test_mapping_file():
    return FIXTURES_DIR / "test_mapping.xlsx"


@pytest.fixture
def test_source_file():
    return FIXTURES_DIR / "test_source.xlsx"


@pytest.fixture
def test_sitetracker_file():
    return FIXTURES_DIR / "test_sitetracker.csv"


@pytest.fixture
def mock_environment(tmp_path, monkeypatch):
    """Set up an isolated data and config sandbox environment for tests."""
    data_dir = tmp_path / "data"
    config_dir = tmp_path / "config" / "reports"
    common_dir = data_dir / "common"

    data_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    common_dir.mkdir(parents=True)

    # Copy mapping file
    shutil.copy2(FIXTURES_DIR / "test_mapping.xlsx", common_dir / "Mapping_file.xlsx")

    # Create test report directory structure
    report_dir = data_dir / "Test_Report"
    source_dir = report_dir / "input" / "source"
    st_dir = report_dir / "input" / "sitetracker"
    runs_dir = report_dir / "runs"
    archive_dir = report_dir / "archive"

    source_dir.mkdir(parents=True)
    st_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)

    # Copy source and sitetracker input files
    shutil.copy2(FIXTURES_DIR / "test_source.xlsx", source_dir / "source.xlsx")
    shutil.copy2(FIXTURES_DIR / "test_sitetracker.csv", st_dir / "sitetracker.csv")

    # Create YAML config
    report_config = {
        "report": {
            "name": "Test Report",
            "sf_id_column": "Id"
        },
        "folders": {
            "work_dir": "Test_Report",
            "source_dir": "input/source",
            "sitetracker_dir": "input/sitetracker",
            "runs_dir": "runs",
            "archive_dir": "archive"
        },
        "date": {
            "format": "UK",
            "dayfirst": True,
            "allow_empty": True
        },
        "text_case_columns": [],
        "behavior": {
            "archive_after_success": False
        }
    }

    with open(config_dir / "test_report.yml", "w", encoding="utf-8") as f:
        yaml.dump(report_config, f)

    # Patch settings
    import config.settings as s
    monkeypatch.setattr(s, "DATA_DIR", data_dir)
    monkeypatch.setattr(s, "COMMON_DIR", common_dir)
    monkeypatch.setattr(s, "MAPPING_FILE", common_dir / "Mapping_file.xlsx")
    monkeypatch.setattr(s, "MAPPING_HISTORY_DIR", common_dir / "mapping_history")
    monkeypatch.setattr(s, "CONFIG_DIR", config_dir)

    return {
        "tmp_path": tmp_path,
        "data_dir": data_dir,
        "config_dir": config_dir,
        "report_dir": report_dir,
    }
