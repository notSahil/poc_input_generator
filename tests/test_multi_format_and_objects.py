"""Unit tests for universal spreadsheet reader, multi-format pipeline, and multi-object payload isolation."""

from pathlib import Path
import pandas as pd
import pytest

from core.normalizer import DataNormalizer
from core.validator import InputValidator
from core.engine import InputFileEngine
from salesforce.bulk_uploader import clean_payload_for_salesforce


def test_read_spreadsheet_csv_utf8(tmp_path: Path):
    """Test reading a standard UTF-8 CSV file."""
    csv_file = tmp_path / "test_utf8.csv"
    csv_file.write_text("Col1,Col2\nVal1,Val2\n", encoding="utf-8")

    df = DataNormalizer.read_spreadsheet(csv_file)
    assert list(df.columns) == ["Col1", "Col2"]
    assert len(df) == 1
    assert df.iloc[0]["Col1"] == "Val1"


def test_read_spreadsheet_csv_latin1(tmp_path: Path):
    """Test reading a legacy Latin-1 encoded CSV with special characters."""
    csv_file = tmp_path / "test_latin1.csv"
    # 0x96 is the Windows-1252 en-dash that breaks UTF-8 decoders
    content = b"Site Name,Notes\nTest Site,Special \x96 Dash\n"
    csv_file.write_bytes(content)

    df = DataNormalizer.read_spreadsheet(csv_file)
    assert list(df.columns) == ["Site Name", "Notes"]
    assert len(df) == 1
    assert "Special" in df.iloc[0]["Notes"]


def test_read_spreadsheet_excel(tmp_path: Path):
    """Test reading an Excel .xlsx file."""
    xlsx_file = tmp_path / "test.xlsx"
    pd.DataFrame([{"A": "1", "B": "2"}]).to_excel(xlsx_file, index=False)

    df = DataNormalizer.read_spreadsheet(xlsx_file)
    assert list(df.columns) == ["A", "B"]
    assert len(df) == 1
    assert df.iloc[0]["A"] == "1"


def test_clean_payload_multi_object_isolation():
    """Verify clean_payload_for_salesforce isolates fields belonging to specific target objects."""
    # Simulate a payload that contains fields from BOTH BT Project and Project
    mixed_df = pd.DataFrame([
        {
            "Id": "a1e4J000000CKmRQAW",
            "Project Ref": "PX71-1234",
            "Ran_Priority__c": "High",
            "Order_Placed__c": "2024-05-10",
            "WES_PSID__c": "BTWD1000",          # Belongs to Project
            "HE_MEAS_Status__c": "Completed",    # Belongs to Project
        }
    ])

    # 1. When target is BT_Project__c, Project fields must be dropped
    bt_payload = clean_payload_for_salesforce(
        mixed_df,
        report_name="Apollo 10G",
        target_object="BT Project"
    )
    assert len(bt_payload) == 1
    rec_bt = bt_payload[0]
    assert rec_bt["Id"] == "a1e4J000000CKmRQAW"
    assert "Ran_Priority__c" in rec_bt
    assert "Order_Placed__c" in rec_bt
    assert "WES_PSID__c" not in rec_bt
    assert "HE_MEAS_Status__c" not in rec_bt
    assert "Project Ref" not in rec_bt

    # 2. When target is Project, BT Project fields must be dropped
    proj_payload = clean_payload_for_salesforce(
        mixed_df,
        report_name="Apollo 10G",
        target_object="Project"
    )
    assert len(proj_payload) == 1
    rec_proj = proj_payload[0]
    assert rec_proj["Id"] == "a1e4J000000CKmRQAW"
    assert "WES_PSID__c" in rec_proj
    assert "HE_MEAS_Status__c" in rec_proj
    assert "Ran_Priority__c" not in rec_proj
    assert "Order_Placed__c" not in rec_proj


def test_apollo_multi_object_files_generated():
    """Verify that Apollo 10G engine run creates both standard files and dedicated per-object payloads."""
    engine = InputFileEngine("Apollo 10G")
    result = engine.run(skip_validation=False)

    assert result.success is True
    run_dir = result.run_dir

    # Standard 5 output contracts
    assert (run_dir / "final_input_file.csv").exists()
    assert (run_dir / "rollback_file.csv").exists()
    assert (run_dir / "field_level_changes.csv").exists()
    assert (run_dir / "run_summary.txt").exists()

    # Dedicated per-object payloads
    bt_file = run_dir / "final_input_file_BT_Project.csv"
    proj_file = run_dir / "final_input_file_Project.csv"

    assert bt_file.exists(), "BT Project dedicated payload was not created"
    assert proj_file.exists(), "Project dedicated payload was not created"

    df_bt = pd.read_csv(bt_file)
    df_proj = pd.read_csv(proj_file)

    # Validate BT Project payload schema
    assert "Id" in df_bt.columns
    assert "Ran_Priority__c" in df_bt.columns
    assert "WES_PSID__c" not in df_bt.columns
    # Ensure ID starts with a1e
    assert df_bt["Id"].dropna().iloc[0].startswith("a1e")

    # Validate Project payload schema
    assert "Id" in df_proj.columns
    assert "WES_PSID__c" in df_proj.columns
    assert "Ran_Priority__c" not in df_proj.columns
    # Ensure ID starts with a0i
    assert df_proj["Id"].dropna().iloc[0].startswith("a0i")
