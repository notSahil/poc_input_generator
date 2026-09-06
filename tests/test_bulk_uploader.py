"""Unit tests for salesforce/bulk_uploader.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from salesforce.bulk_uploader import (
    BulkUploadResult,
    clean_payload_for_salesforce,
    push_delta_to_sitetracker,
)


def test_clean_payload_for_salesforce():
    raw_df = pd.DataFrame([
        {
            "Id": "a12345678901234567",
            "Project Ref": "PROJ-001",  # Source column (should be dropped)
            "Project_Reference__c": "PROJ-001",
            "Order_Placed__c": "2026-09-01",
            "Date_of_Master_Site_Listing__c": "22/11/2025"
        }
    ])

    records = clean_payload_for_salesforce(raw_df, report_name="Master Site Listing")
    assert len(records) == 1
    rec = records[0]
    assert "Id" in rec
    assert "Date_of_Master_Site_Listing__c" in rec
    assert rec["Date_of_Master_Site_Listing__c"] == "2025-11-22"  # UK date converted to ISO
    assert "Project Ref" not in rec


def test_clean_payload_preserves_hash_na_for_null_wipe():
    """Verify that #N/A strings are preserved across text and date fields for Bulk API 2.0 null clearance."""
    raw_df = pd.DataFrame([
        {
            "Id": "a12345678901234567",
            "Status__c": "#N/A",
            "Target_Date__c": "#N/A",
            "Empty_Field__c": ""
        }
    ])

    records = clean_payload_for_salesforce(raw_df)
    assert len(records) == 1
    rec = records[0]
    assert rec["Status__c"] == "#N/A"
    assert rec["Target_Date__c"] == "#N/A"
    assert rec["Empty_Field__c"] is None



def test_push_delta_empty_csv(tmp_path):
    empty_csv = tmp_path / "empty_input.csv"
    pd.DataFrame().to_csv(empty_csv, index=False)

    result = push_delta_to_sitetracker(empty_csv, object_name="Site__c")
    assert result.total_records == 0
    assert result.all_succeeded is True
    assert result.job_id == "N/A_EMPTY"


def test_push_delta_success(tmp_path):
    test_csv = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": "a12345678901234567", "Status__c": "Completed"},
        {"Id": "a12345678901234568", "Status__c": "In Progress"}
    ])
    df.to_csv(test_csv, index=False)

    mock_sf = MagicMock()
    mock_bulk_obj = MagicMock()
    mock_bulk_obj.update.return_value = [{
        "numberRecordsTotal": 2,
        "numberRecordsProcessed": 2,
        "numberRecordsFailed": 0,
        "job_id": "75000000001fake"
    }]
    setattr(mock_sf.bulk2, "Site__c", mock_bulk_obj)

    with patch("salesforce.bulk_uploader.get_sf_connection", return_value=mock_sf):
        res = push_delta_to_sitetracker(test_csv, object_name="Site__c", operation="update")

        assert res.total_records == 2
        assert res.successful_records == 2
        assert res.failed_records == 0
        assert res.all_succeeded is True
        assert res.job_id == "75000000001fake"
        assert res.failures_csv_path is None


def test_push_delta_with_failures(tmp_path):
    test_csv = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": "a12345678901234567", "Status__c": "BadValue"}
    ])
    df.to_csv(test_csv, index=False)

    mock_sf = MagicMock()
    mock_bulk_obj = MagicMock()
    mock_bulk_obj.update.return_value = [{
        "numberRecordsTotal": 1,
        "numberRecordsProcessed": 1,
        "numberRecordsFailed": 1,
        "job_id": "75000000002fake"
    }]
    mock_bulk_obj.get_failed_records.return_value = "sf__Id,sf__Error,Status__c\na12345678901234567,INVALID_OR_NULL_FIELD,BadValue\n"
    setattr(mock_sf.bulk2, "Site__c", mock_bulk_obj)

    with patch("salesforce.bulk_uploader.get_sf_connection", return_value=mock_sf):
        res = push_delta_to_sitetracker(test_csv, object_name="Site__c", operation="update")

        assert res.total_records == 1
        assert res.successful_records == 0
        assert res.failed_records == 1
        assert res.all_succeeded is False
        assert res.job_id == "75000000002fake"
        assert res.failures_csv_path is not None
        assert res.failures_csv_path.exists()
        assert len(res.failures) == 1
