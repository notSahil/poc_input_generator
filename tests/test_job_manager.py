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
        assert is_job_active(tmp_path) is False

        clear_job_progress(tmp_path)
        assert get_job_progress(tmp_path) is None


