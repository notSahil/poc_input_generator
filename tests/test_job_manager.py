"""Unit tests for salesforce/job_manager.py."""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from salesforce.bulk_uploader import BulkUploadResult
from salesforce.job_manager import (
    clear_job_progress,
    get_job_progress,
    is_job_active,
    start_background_ingest,
)


def test_job_manager_lifecycle(tmp_path):
    # Setup dummy payload files
    bt_file = tmp_path / "final_input_file_BT_Project.csv"
    pd.DataFrame([{"Id": "a1e1", "Ran_Priority__c": "Cisco"}]).to_csv(bt_file, index=False)

    proj_file = tmp_path / "final_input_file_Project.csv"
    pd.DataFrame([{"Id": "a0i1", "HE_MEAS_Status__c": "Done"}]).to_csv(proj_file, index=False)

    # Mock push_delta_via_composite
    def mock_push(*args, **kwargs):
        return BulkUploadResult(
            total_records=1,
            successful_records=1,
            failed_records=0,
            job_id="MOCK_REST_JOB",
            all_succeeded=True,
        )

    with patch("salesforce.composite_uploader.push_delta_via_composite", side_effect=mock_push):
        start_background_ingest(
            run_dir=tmp_path,
            report_name="Apollo 10G",
            is_rollback=False,
            engine="composite",
        )

        # Wait for thread to finish
        for _ in range(50):
            prog = get_job_progress(tmp_path)
            if prog and prog.get("status") == "COMPLETED":
                break
            time.sleep(0.1)

        prog = get_job_progress(tmp_path)
        assert prog is not None
        assert prog["status"] == "COMPLETED"
        assert prog["processed_records_overall"] == 2
        assert prog["successful_records_overall"] == 2
        assert is_job_active(tmp_path) is False

        # Test clear
        clear_job_progress(tmp_path)
        assert get_job_progress(tmp_path) is None


def test_job_manager_rollback_lifecycle(tmp_path):
    rb_bt = tmp_path / "rollback_file_BT_Project.csv"
    pd.DataFrame([{"Id": "a1e1", "Ran_Priority__c": "Old_Cisco"}]).to_csv(rb_bt, index=False)

    rb_proj = tmp_path / "rollback_file_Project.csv"
    pd.DataFrame([{"Id": "a0i1", "HE_MEAS_Status__c": "Pending"}]).to_csv(rb_proj, index=False)

    def mock_push(*args, **kwargs):
        assert kwargs.get("is_rollback") is True
        return BulkUploadResult(
            total_records=1,
            successful_records=1,
            failed_records=0,
            job_id="MOCK_REST_RB_JOB",
            all_succeeded=True,
        )

    with patch("salesforce.composite_uploader.push_delta_via_composite", side_effect=mock_push):
        start_background_ingest(
            run_dir=tmp_path,
            report_name="Apollo 10G",
            is_rollback=True,
            engine="composite",
        )

        for _ in range(50):
            prog = get_job_progress(tmp_path)
            if prog and prog.get("status") == "COMPLETED":
                break
            time.sleep(0.1)

        prog = get_job_progress(tmp_path)
        assert prog is not None
        assert prog["status"] == "COMPLETED"
        assert prog["is_rollback"] is True
        assert prog["processed_records_overall"] == 2
        assert prog["successful_records_overall"] == 2

        # Allow thread to finish exit
        for _ in range(20):
            if not is_job_active(tmp_path):
                break
            time.sleep(0.05)
        assert is_job_active(tmp_path) is False

        clear_job_progress(tmp_path)
        assert get_job_progress(tmp_path) is None


def test_job_manager_adhoc_lifecycle(tmp_path):
    final_file = tmp_path / "final_input_file.csv"
    pd.DataFrame([{"Id": "a0p1", "Site_on_Master_Site_List__c": "Yes"}]).to_csv(final_file, index=False)

    def mock_push(*args, **kwargs):
        assert kwargs.get("object_name") == "sitetracker__Site__c"
        return BulkUploadResult(
            total_records=1,
            successful_records=1,
            failed_records=0,
            job_id="MOCK_ADHOC_REST_JOB",
            all_succeeded=True,
        )

    with patch("salesforce.composite_uploader.push_delta_via_composite", side_effect=mock_push):
        start_background_ingest(
            run_dir=tmp_path,
            report_name="Ad-Hoc Ingest",
            target_object="sitetracker__Site__c",
            is_rollback=False,
            engine="composite",
        )

        for _ in range(50):
            prog = get_job_progress(tmp_path)
            if prog and prog.get("status") == "COMPLETED":
                break
            time.sleep(0.1)

        prog = get_job_progress(tmp_path)
        assert prog is not None
        assert prog["status"] == "COMPLETED"
        assert prog["processed_records_overall"] == 1
        assert prog["successful_records_overall"] == 1

        # Allow thread to finish exit
        for _ in range(20):
            if not is_job_active(tmp_path):
                break
            time.sleep(0.05)
        assert is_job_active(tmp_path) is False

        clear_job_progress(tmp_path)
        assert get_job_progress(tmp_path) is None


def test_simplify_salesforce_error():
    from salesforce.job_manager import simplify_salesforce_error

    err_pk = "INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST: Ran Priority: bad value for restricted picklist field: Nokia 5G Ultra Upgrade"
    assert "Restricted Picklist: 'Nokia 5G Ultra Upgrade'" in simplify_salesforce_error(err_pk)

    err_future = "FIELD_CUSTOM_VALIDATION_EXCEPTION: Actualized date (Order Placed) cannot be in the future"
    assert "Future Date Not Allowed" in simplify_salesforce_error(err_future)

    err_lock = 'FIELD_CUSTOM_VALIDATION_EXCEPTION: Validation Formula "Actual_Date_Cant_Updated_When_Approved" Invalid'
    assert "Milestone Locked" in simplify_salesforce_error(err_lock)

    err_doc = "FIELD_CUSTOM_VALIDATION_EXCEPTION: This activity requires a document to be uploaded before you can set the Actual Date"
    assert "Missing Attachment" in simplify_salesforce_error(err_doc)

    err_retry = "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY: Too many retries of batch save in the presence of Apex triggers with failures"
    assert "Batch Rollback" in simplify_salesforce_error(err_retry)

    # Test float nan, None, and empty handling
    assert simplify_salesforce_error(float("nan")) == "Salesforce update rejected"
    assert simplify_salesforce_error(None) == "Salesforce update rejected"
    assert simplify_salesforce_error("") == "Salesforce update rejected"
    assert simplify_salesforce_error("nan") == "Salesforce update rejected"


def test_job_manager_enriches_sanitized_failures(tmp_path):
    """Verify that failure CSVs with unescaped internal quotes are sanitized and enriched without dropping rows."""
    proj_file = tmp_path / "final_input_file_Project.csv"
    pd.DataFrame([{"Id": "a0i8e000000NzWCAA0", "WES_PSID__c": "BW-SAFE-004"}]).to_csv(proj_file, index=False)

    failures_csv = tmp_path / "bulk_upload_failures.csv"
    # Write a raw failure CSV containing unescaped internal quotes
    malformed_csv_content = (
        'sf__Id,sf__Error,WES_PSID__c,Id\n'
        'a0i8e000000NzWCAA0,"FIELD_CUSTOM_VALIDATION_EXCEPTION:Formula "Actual_Date_Cant_Updated_When_Approved" Invalid:--",BW-SAFE-004,a0i8e000000NzWCAA0\n'
        'a0iTe000008aH5mIAE,"STRING_TOO_LONG: Value too long",BTWD-TOOLONG-999,a0iTe000008aH5mIAE\n'
    )
    failures_csv.write_text(malformed_csv_content)

    def mock_bulk_push(*args, **kwargs):
        return BulkUploadResult(
            total_records=2,
            successful_records=0,
            failed_records=2,
            job_id="MOCK_BULK_JOB",
            all_succeeded=False,
            failures_csv_path=failures_csv,
            failures=[
                {"sf__Id": "a0i8e000000NzWCAA0", "sf__Error": 'FIELD_CUSTOM_VALIDATION_EXCEPTION:Formula "Actual_Date_Cant_Updated_When_Approved" Invalid:--'},
                {"sf__Id": "a0iTe000008aH5mIAE", "sf__Error": "STRING_TOO_LONG: Value too long"},
            ],
        )

    with patch("salesforce.bulk_uploader.push_delta_to_sitetracker", side_effect=mock_bulk_push):
        start_background_ingest(
            run_dir=tmp_path,
            report_name="Apollo 10G",
            is_rollback=False,
            engine="bulk2",
            target_object="Project",
        )

        for _ in range(50):
            prog = get_job_progress(tmp_path)
            if prog and prog.get("status") in ("COMPLETED", "COMPLETED_WITH_ERRORS"):
                break
            time.sleep(0.1)

        prog = get_job_progress(tmp_path)
        assert prog is not None
        assert prog["failed_records_overall"] == 2

        # Verify enriched per-object failure file
        per_obj_csv = tmp_path / "bulk_upload_failures_Project.csv"
        assert per_obj_csv.exists()
        df_per_obj = pd.read_csv(per_obj_csv)
        # BOTH records must be preserved (zero silent drops)
        assert len(df_per_obj) == 2
        assert "Simplified_Cause" in df_per_obj.columns
        assert df_per_obj.iloc[0]["sf__Id"] == "a0i8e000000NzWCAA0"
        assert "Milestone Locked" in df_per_obj.iloc[0]["Simplified_Cause"]
        assert df_per_obj.iloc[1]["sf__Id"] == "a0iTe000008aH5mIAE"
        assert "Text Too Long" in df_per_obj.iloc[1]["Simplified_Cause"]




