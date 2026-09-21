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


def test_clean_payload_rollback_converts_empty_to_hash_na():
    """Verify that rollback payload automatically converts empty fields to #N/A for Bulk API 2.0 field clearing."""
    raw_df = pd.DataFrame([
        {
            "Id": "a12345678901234567",
            "Status__c": "Approved",
            "Date_Field__c": "",
            "Empty_Field__c": None,
        }
    ])

    records = clean_payload_for_salesforce(raw_df, is_rollback=True)
    assert len(records) == 1
    rec = records[0]
    assert rec["Status__c"] == "Approved"
    assert rec["Date_Field__c"] == "#N/A"
    assert rec["Empty_Field__c"] == "#N/A"



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
    setattr(mock_sf.bulk2, "sitetracker__Site__c", mock_bulk_obj)
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
    setattr(mock_sf.bulk2, "sitetracker__Site__c", mock_bulk_obj)
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


def test_push_delta_batch_size_and_multi_chunk_aggregation(tmp_path):
    """Verify batch_size is passed to Bulk API and multiple chunk jobs are aggregated correctly."""
    test_csv = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": f"a1e{i:05d}", "Status__c": "Active"} for i in range(50)
    ])
    df.to_csv(test_csv, index=False)

    mock_sf = MagicMock()
    mock_bulk_obj = MagicMock()
    # Simulate two 25-record chunks
    mock_bulk_obj.update.side_effect = [
        [{"numberRecordsTotal": 25, "numberRecordsProcessed": 25, "numberRecordsFailed": 0, "job_id": "JOB_CHUNK_1"}],
        [{"numberRecordsTotal": 25, "numberRecordsProcessed": 25, "numberRecordsFailed": 0, "job_id": "JOB_CHUNK_2"}],
    ]
    setattr(mock_sf.bulk2, "Site__c", mock_bulk_obj)
    setattr(mock_sf.bulk2, "sitetracker__Site__c", mock_bulk_obj)

    cb_calls = []
    with patch("salesforce.bulk_uploader.get_sf_connection", return_value=mock_sf):
        res = push_delta_to_sitetracker(
            test_csv,
            object_name="Site__c",
            operation="update",
            batch_size=25,
            progress_callback=lambda p: cb_calls.append(p)
        )

        assert res.total_records == 50
        assert res.successful_records == 50
        assert res.failed_records == 0
        assert res.all_succeeded is True
        assert "JOB_CHUNK_1" in res.job_id
        assert "JOB_CHUNK_2" in res.job_id
        # Verify chunked execution: 2 chunk calls of 25 records each
        assert mock_bulk_obj.update.call_count == 2
        # Verify progress callback invoked for both chunks
        assert len(cb_calls) == 2
        assert cb_calls[0]["current_chunk"] == 1
        assert cb_calls[1]["current_chunk"] == 2
        assert cb_calls[1]["processed_records"] == 50


def test_push_delta_resilient_error_parsing_with_commas(tmp_path):
    """Verify that unquoted commas in Salesforce trigger error messages do not crash CSV parsing."""
    test_csv = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([{"Id": "a123", "Status__c": "Val"}])
    df.to_csv(test_csv, index=False)

    mock_sf = MagicMock()
    mock_bulk_obj = MagicMock()
    mock_bulk_obj.update.return_value = [
        {"numberRecordsTotal": 1, "numberRecordsProcessed": 1, "numberRecordsFailed": 1, "job_id": "JOB_FAIL_1"}
    ]
    # Simulate a raw CSV from Salesforce with multiline/unquoted commas in error message
    mock_bulk_obj.get_failed_records.return_value = (
        "sf__Id,sf__Error\n"
        "a123,CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY:BTProjectTrigger: System.LimitException: sitetracker:Too many DML statements: 151:--\n"
    )
    setattr(mock_sf.bulk2, "Site__c", mock_bulk_obj)
    setattr(mock_sf.bulk2, "sitetracker__Site__c", mock_bulk_obj)

    with patch("salesforce.bulk_uploader.get_sf_connection", return_value=mock_sf):
        res = push_delta_to_sitetracker(test_csv, object_name="Site__c", operation="update", batch_size=25)

        assert res.total_records == 1
        assert res.failed_records == 1
        assert res.all_succeeded is False
        assert len(res.failures) == 1
        assert "Too many DML statements" in res.failures[0]["sf__Error"]


def test_push_delta_preserves_all_failures_with_unescaped_quotes(tmp_path):
    """Verify that failures with unescaped internal quotes are not dropped."""
    test_csv = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": "a0i8e000000NzWCAA0", "WES_PSID__c": "BW-SAFE-004"},
        {"Id": "a0iTe000008aH5mIAE", "WES_PSID__c": "BTWD-TOOLONG-999"},
    ])
    df.to_csv(test_csv, index=False)

    mock_sf = MagicMock()
    mock_bulk_obj = MagicMock()
    mock_bulk_obj.update.return_value = [
        {"numberRecordsTotal": 2, "numberRecordsProcessed": 2, "numberRecordsFailed": 2, "job_id": "JOB_FAIL_QUOTES"}
    ]
    # Simulate raw CSV where row 1 has unescaped quotes in validation formula
    mock_bulk_obj.get_failed_records.return_value = (
        'sf__Id,sf__Error,WES_PSID__c,Id\n'
        'a0i8e000000NzWCAA0,"FIELD_CUSTOM_VALIDATION_EXCEPTION:Formula "Actual_Date_Cant_Updated" Invalid:--",BW-SAFE-004,a0i8e000000NzWCAA0\n'
        'a0iTe000008aH5mIAE,"STRING_TOO_LONG: Value too long",BTWD-TOOLONG-999,a0iTe000008aH5mIAE\n'
    )
    setattr(mock_sf.bulk2, "Project", mock_bulk_obj)
    setattr(mock_sf.bulk2, "sitetracker__Project__c", mock_bulk_obj)

    with patch("salesforce.bulk_uploader.get_sf_connection", return_value=mock_sf):
        res = push_delta_to_sitetracker(test_csv, object_name="Project", operation="update", batch_size=25)

        assert res.total_records == 2
        assert res.failed_records == 2
        assert res.all_succeeded is False
        assert len(res.failures) == 2
        assert res.failures[0]["sf__Id"] == "a0i8e000000NzWCAA0"
        assert "Actual_Date_Cant_Updated" in res.failures[0]["sf__Error"]
        assert res.failures[1]["sf__Id"] == "a0iTe000008aH5mIAE"


def test_push_delta_preserves_multiline_apex_failures(tmp_path):
    """Verify that multiline Apex stack traces are stitched and not dropped as phantom rows."""
    test_csv = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": "a1e4J000000RTohQAG", "Status__c": "Active"},
        {"Id": "a1e8e000000kjz7AAA", "Status__c": "Active"},
    ])
    df.to_csv(test_csv, index=False)

    mock_sf = MagicMock()
    mock_bulk_obj = MagicMock()
    mock_bulk_obj.update.return_value = [
        {"numberRecordsTotal": 2, "numberRecordsProcessed": 2, "numberRecordsFailed": 2, "job_id": "JOB_FAIL_MULTILINE"}
    ]
    # Simulate multiline stack trace without quotes
    mock_bulk_obj.get_failed_records.return_value = (
        "sf__Id,sf__Error,Status__c,Id\n"
        "a1e4J000000RTohQAG,CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY:BTProjectTrigger: execution of AfterUpdate\n"
        "caused by: System.DmlException: Insert failed.\n"
        "Class.BT_Project_Trigger_Handler: line 84:--,Active,a1e4J000000RTohQAG\n"
        "a1e8e000000kjz7AAA,Normal error message,Active,a1e8e000000kjz7AAA\n"
    )
    setattr(mock_sf.bulk2, "BT_Project", mock_bulk_obj)
    setattr(mock_sf.bulk2, "BT_Project__c", mock_bulk_obj)

    with patch("salesforce.bulk_uploader.get_sf_connection", return_value=mock_sf):
        res = push_delta_to_sitetracker(test_csv, object_name="BT_Project", operation="update", batch_size=25)

        assert res.total_records == 2
        assert res.failed_records == 2
        assert res.all_succeeded is False
        assert len(res.failures) == 2
        assert res.failures[0]["sf__Id"] == "a1e4J000000RTohQAG"
        assert "execution of AfterUpdate" in res.failures[0]["sf__Error"]
        assert "System.DmlException" in res.failures[0]["sf__Error"]
        assert res.failures[1]["sf__Id"] == "a1e8e000000kjz7AAA"


def test_push_delta_chunk_retry_and_reauth_on_session_expiry(tmp_path):
    """Verify that if a chunk fails with expired session/auth error, it re-authenticates and retries successfully."""
    from simple_salesforce.exceptions import SalesforceExpiredSession

    test_csv = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([{"Id": "a123", "Status__c": "Active"}])
    df.to_csv(test_csv, index=False)

    mock_sf_1 = MagicMock()
    mock_bulk_1 = MagicMock()
    mock_bulk_1.update.side_effect = SalesforceExpiredSession(
        url="https://sf.com",
        status=401,
        resource_name="Site__c",
        content=b"Session expired"
    )
    setattr(mock_sf_1.bulk2, "Site__c", mock_bulk_1)
    setattr(mock_sf_1.bulk2, "sitetracker__Site__c", mock_bulk_1)

    mock_sf_2 = MagicMock()
    mock_bulk_2 = MagicMock()
    mock_bulk_2.update.return_value = [
        {"numberRecordsTotal": 1, "numberRecordsProcessed": 1, "numberRecordsFailed": 0, "job_id": "RETRY_SUCCESS_JOB"}
    ]
    setattr(mock_sf_2.bulk2, "Site__c", mock_bulk_2)
    setattr(mock_sf_2.bulk2, "sitetracker__Site__c", mock_bulk_2)

    with patch("salesforce.bulk_uploader.get_sf_connection", side_effect=[mock_sf_1, mock_sf_2]) as mock_get_conn, \
         patch("time.sleep") as mock_sleep:
        res = push_delta_to_sitetracker(test_csv, object_name="Site__c", operation="update", batch_size=25)

        # Verified that connection was fetched initially, and re-authenticated on chunk failure
        assert mock_get_conn.call_count == 2
        assert mock_sleep.call_count == 1
        assert res.total_records == 1
        assert res.successful_records == 1
        assert res.failed_records == 0
        assert res.all_succeeded is True
        assert res.job_id == "RETRY_SUCCESS_JOB"


def test_push_delta_chunk_permanent_failure_captures_error(tmp_path):
    """Verify that if all retry attempts fail for a chunk, it captures the error in failures_list and does not query get_failed_records for fake IDs."""
    test_csv = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([{"Id": "a123", "Status__c": "Active"}])
    df.to_csv(test_csv, index=False)

    mock_sf = MagicMock()
    mock_bulk_obj = MagicMock()
    mock_bulk_obj.update.side_effect = ConnectionResetError("Connection closed by peer")
    setattr(mock_sf.bulk2, "Site__c", mock_bulk_obj)
    setattr(mock_sf.bulk2, "sitetracker__Site__c", mock_bulk_obj)

    with patch("salesforce.bulk_uploader.get_sf_connection", return_value=mock_sf), \
         patch("time.sleep"):
        res = push_delta_to_sitetracker(test_csv, object_name="Site__c", operation="update", batch_size=25)

        assert res.total_records == 1
        assert res.successful_records == 0
        assert res.failed_records == 1
        assert res.all_succeeded is False
        assert "FAILED_CHUNK_1" in res.job_id
        assert len(res.failures) == 1
        assert res.failures[0]["sf__Id"] == "a123"
        assert "CHUNK_SUBMISSION_ERROR" in res.failures[0]["sf__Error"]
        # Make sure get_failed_records was NOT called on FAILED_CHUNK_1
        mock_bulk_obj.get_failed_records.assert_not_called()
        # Failures CSV should exist
        assert res.failures_csv_path is not None
        assert res.failures_csv_path.exists()



