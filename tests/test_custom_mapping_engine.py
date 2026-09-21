"""Unit and integration tests for custom mapping overrides in MappingLoader, InputValidator, and InputFileEngine."""

from __future__ import annotations

from pathlib import Path
import pandas as pd
import pytest

from core.engine import InputFileEngine
from core.mapping_loader import MappingLoader
from core.validator import InputValidator


@pytest.fixture
def sample_custom_mapping():
    return pd.DataFrame([
        {
            "Report Name": "Apollo 10G",
            "Object Name": "BT Project",
            "Source File Column Name": "Custom Project Ref",
            "Sitetracker Field Name": "Project Reference",
            "API Name": "Project_Reference__c",
            "Data Type": "text",
            "Primary Key?": "YES",
        },
        {
            "Report Name": "Apollo 10G",
            "Object Name": "BT Project",
            "Source File Column Name": "Custom Vendor",
            "Sitetracker Field Name": "Ran Priority",
            "API Name": "Ran_Priority__c",
            "Data Type": "text",
            "Primary Key?": "NO",
        },
    ])


def test_mapping_loader_with_custom_df(sample_custom_mapping):
    loader = MappingLoader(report_name="Apollo 10G", custom_df=sample_custom_mapping)
    df = loader.load()

    assert len(df) == 2
    assert loader.primary_keys() == ("Custom Project Ref", "Project Reference")
    assert loader.objects() == ["BT Project"]
    field_map = loader.field_mapping()
    assert len(field_map) == 2
    assert field_map[0][0] == "Custom Project Ref"
    assert field_map[1][0] == "Custom Vendor"


def test_mapping_loader_default_fallback_without_custom_df():
    # When custom_df is None, loads standard Excel mapping
    loader = MappingLoader(report_name="Apollo 10G")
    df = loader.load()
    assert not df.empty
    assert "Source File Column Name" in df.columns


def test_validator_with_custom_mapping(tmp_path, sample_custom_mapping, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    work_dir = tmp_path / "Apollo_10G"
    src_dir = work_dir / "input" / "source"
    st_dir = work_dir / "input" / "sitetracker"
    src_dir.mkdir(parents=True)
    st_dir.mkdir(parents=True)

    # Create source spreadsheet with the custom columns
    pd.DataFrame([{
        "Custom Project Ref": "PR-001",
        "Custom Vendor": "Cisco",
    }]).to_csv(src_dir / "custom_source.csv", index=False)

    # Create sitetracker baseline
    pd.DataFrame([{
        "Id": "a1e123",
        "Project Reference": "PR-001",
        "Ran Priority": "Huawei",
    }]).to_csv(st_dir / "Apollo_10G_sitetracker_live.csv", index=False)

    validator = InputValidator("Apollo 10G", custom_mapping_df=sample_custom_mapping)
    result = validator.validate_all()

    assert result.is_valid is True
    assert len(result.errors) == 0


def test_engine_run_with_custom_mapping(tmp_path, sample_custom_mapping, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    work_dir = tmp_path / "Apollo_10G"
    src_dir = work_dir / "input" / "source"
    st_dir = work_dir / "input" / "sitetracker"
    runs_dir = work_dir / "runs"
    archive_dir = work_dir / "archive"
    src_dir.mkdir(parents=True)
    st_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)

    # Source has modified vendor
    pd.DataFrame([{
        "Custom Project Ref": "PR-001",
        "Custom Vendor": "Nokia",
    }]).to_csv(src_dir / "custom_source.csv", index=False)

    # Baseline has original vendor
    pd.DataFrame([{
        "Id": "a1e000000000001AAA",
        "Project Reference": "PR-001",
        "Ran Priority": "Cisco",
    }]).to_csv(st_dir / "Apollo_10G_sitetracker_live.csv", index=False)

    engine = InputFileEngine("Apollo 10G", custom_mapping_df=sample_custom_mapping)
    res = engine.run()

    assert res.total_source_records == 1
    assert res.delta_records == 1
    final_input_csv = res.run_dir / "final_input_file.csv"
    assert final_input_csv.exists()

    final_df = pd.read_csv(final_input_csv)
    assert "Ran_Priority__c" in final_df.columns
    assert final_df.iloc[0]["Ran_Priority__c"] == "Nokia"
