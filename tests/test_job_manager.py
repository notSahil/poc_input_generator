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
