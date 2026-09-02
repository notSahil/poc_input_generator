"""End-to-end integration tests for the automated Sitetracker data pipeline."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from core.engine import InputFileEngine
from salesforce.bulk_uploader import push_delta_to_sitetracker
from salesforce.data_fetcher import build_soql_for_report, fetch_sitetracker_data
from salesforce.sf_client import get_sf_connection


def test_token_auto_refresh():
    """Verify that an expired token with a refresh_token is automatically refreshed."""
    expired_token = {
        "access_token": "expired_access_token",
        "refresh_token": "valid_refresh_token",
        "instance_url": "https://testorg.my.salesforce.com",
        "saved_at": 1000.0  # Expired
    }
    refreshed_token = {
        "access_token": "fresh_new_access_token",
        "refresh_token": "valid_refresh_token",
        "instance_url": "https://testorg.my.salesforce.com"
    }

    mock_sf_instance = MagicMock()

    with patch("salesforce.sf_client.load_token", side_effect=[expired_token, refreshed_token]), \
         patch("salesforce.sf_client.is_token_valid", return_value=False), \
         patch("salesforce.sf_client.refresh_access_token", return_value=refreshed_token) as mock_refresh, \
         patch("salesforce.sf_client.Salesforce", return_value=mock_sf_instance) as mock_sf_cls:

        sf = get_sf_connection()

        mock_refresh.assert_called_once_with("valid_refresh_token")
        mock_sf_cls.assert_called_once_with(
            instance_url="https://testorg.my.salesforce.com",
            session_id="fresh_new_access_token"
        )
        assert sf == mock_sf_instance


def test_full_pipeline_flow(tmp_path, monkeypatch):
    """
    Test complete lifecycle:
    1. Dynamic SOQL generation
    2. Live Data Fetch to input/sitetracker/
    3. InputFileEngine delta comparison (produces strict 5 output files)
    4. Bulk API 2.0 Upload
    5. Execution audit log verification (bulk_upload_audit.json)
    """
    report_name = "Apollo 10G"

    # Step 1: Verify SOQL generation
    soql, obj, api_map = build_soql_for_report(report_name)
    assert "Project_Reference__c" in soql
    assert "Id" in soql

    # Step 2: Setup directories
    base_dir = tmp_path / "Apollo_10G"
    src_dir = base_dir / "input/source"
    st_dir = base_dir / "input/sitetracker"
    runs_dir = base_dir / "runs"
    archive_dir = base_dir / "archive"

    src_dir.mkdir(parents=True)
    st_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)
    archive_dir.mkdir(parents=True)

    # Monkeypatch settings.DATA_DIR to point to tmp_path
    from config import settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    # Load mapping to populate all required columns
    from core.mapping_loader import MappingLoader
    mapping = MappingLoader(settings.MAPPING_FILE, report_name)
    mapping.load()
    field_map = mapping.field_mapping()

    # Mock live sitetracker fetch records covering all mapped API fields
    mock_records = []
    src_rows = []

    # Record 1: has exactly 1 delta on WES PSID
    rec1 = {"Id": "a00100000000001AAA", "attributes": {"type": "Project__c"}}
    src1 = {}
    for sc, stc, apic, dtype in field_map:
        val = "01/01/2026" if dtype == "date" else "SAME_VAL"
        rec1[apic] = "2026-01-01" if dtype == "date" else val
        src1[sc] = val
    rec1["Project_Reference__c"] = "APOLLO-101"
    src1["Project Ref"] = "APOLLO-101"
    rec1["WES_PSID__c"] = "OLD_PSID_VAL"
    src1["WES PSID"] = "NEW_PSID_VAL"  # 1 field delta
    mock_records.append(rec1)
    src_rows.append(src1)

    # Record 2: identical / no deltas
    rec2 = {"Id": "a00100000000002AAA", "attributes": {"type": "Project__c"}}
    src2 = {}
    for sc, stc, apic, dtype in field_map:
        val = "01/01/2026" if dtype == "date" else "SAME_VAL"
        rec2[apic] = "2026-01-01" if dtype == "date" else val
        src2[sc] = val
    rec2["Project_Reference__c"] = "APOLLO-102"
    src2["Project Ref"] = "APOLLO-102"
    mock_records.append(rec2)
    src_rows.append(src2)

    mock_sf = MagicMock()
    mock_sf.query_all.return_value = {"records": mock_records, "totalSize": 2, "done": True}

    with patch("salesforce.data_fetcher.get_sf_connection", return_value=mock_sf):
        st_csv = fetch_sitetracker_data(report_name, output_dir=st_dir)
        assert st_csv.exists()

    # Step 3: Create source Excel file
    src_data = pd.DataFrame(src_rows)
    src_excel = src_dir / "apollo_source.xlsx"
    src_data.to_excel(src_excel, index=False)

    # Step 4: Run InputFileEngine
    engine = InputFileEngine(report_name)
    result = engine.run()

    assert result.success is True
    assert result.delta_records == 1
    assert result.field_changes_count == 1

    # Verify strict 5-file output contract
    run_dir = result.run_dir
    assert (run_dir / "final_input_file.csv").exists()
    assert (run_dir / "field_level_changes.csv").exists()
    assert (run_dir / "run_summary.txt").exists()

    final_csv = run_dir / "final_input_file.csv"
    final_df = pd.read_csv(final_csv, dtype=str)
    assert len(final_df) == 1
    assert final_df.iloc[0]["Id"] == "a00100000000001AAA"

    # Step 5: Mock Bulk API 2.0 Upload
    mock_bulk = MagicMock()
    mock_bulk.update.return_value = [{
        "numberRecordsTotal": 1,
        "numberRecordsProcessed": 1,
        "numberRecordsFailed": 0,
        "job_id": "75099999999E2ETEST"
    }]
    setattr(mock_sf.bulk2, "BT_Project__c", mock_bulk)

    with patch("salesforce.bulk_uploader.get_sf_connection", return_value=mock_sf):
        bulk_res = push_delta_to_sitetracker(
            csv_path=final_csv,
            object_name="BT_Project__c",
            report_name=report_name,
            operation="update"
        )

        assert bulk_res.all_succeeded is True
        assert bulk_res.successful_records == 1
        assert bulk_res.job_id == "75099999999E2ETEST"

    # Step 6: Verify audit log was created
    audit_file = run_dir / "bulk_upload_audit.json"
    assert audit_file.exists()
    audit_content = json.loads(audit_file.read_text(encoding="utf-8"))
    assert audit_content["all_succeeded"] is True
    assert audit_content["job_id"] == "75099999999E2ETEST"
    assert audit_content["total_records"] == 1
