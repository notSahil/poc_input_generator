"""Unit tests for salesforce/composite_uploader.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from salesforce.composite_uploader import push_delta_via_composite


def test_push_delta_via_composite_success(tmp_path):
    csv_file = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": f"a1e{i:03d}", "Ran_Priority__c": "Cisco"} for i in range(10)
    ])
    df.to_csv(csv_file, index=False)

    mock_sf = MagicMock()
    # REST composite returns one response item per record in payload
    mock_sf.restful.side_effect = lambda path, method, json, **kwargs: [
        {"id": r["Id"], "success": True, "errors": []} for r in json["records"]
    ]

    progress_events = []
    def cb(event):
        progress_events.append(event)

    with patch("salesforce.composite_uploader.get_sf_connection", return_value=mock_sf):
        res = push_delta_via_composite(
            csv_path=csv_file,
            object_name="BT Project",
            report_name="Apollo 10G",
            batch_size=5,
            progress_callback=cb,
        )

        assert res.total_records == 10
        assert res.successful_records == 10
        assert res.failed_records == 0
        assert res.all_succeeded is True
        # 2 chunks * 2 events per chunk (in_flight + completed_chunk) = 4 events
        assert len(progress_events) == 4
        assert progress_events[0]["stage"] == "in_flight"
        assert progress_events[0]["chunk_start"] == 1
        assert progress_events[0]["chunk_end"] == 5
        assert progress_events[1]["stage"] == "completed_chunk"
        assert progress_events[2]["stage"] == "in_flight"
        assert progress_events[3]["stage"] == "completed_chunk"
        assert mock_sf.restful.call_count == 2


def test_push_delta_via_composite_partial_failures(tmp_path):
    csv_file = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": "a1e001", "Ran_Priority__c": "Cisco"},
        {"Id": "a1e002", "Ran_Priority__c": "Invalid"},
    ])
    df.to_csv(csv_file, index=False)

    mock_sf = MagicMock()
    mock_sf.restful.return_value = [
        {"id": "a1e001", "success": True, "errors": []},
        {"id": "a1e002", "success": False, "errors": [{"statusCode": "FIELD_CUSTOM_VALIDATION_EXCEPTION", "message": "Document required", "fields": ["Ran_Priority__c"]}]},
    ]

    with patch("salesforce.composite_uploader.get_sf_connection", return_value=mock_sf):
        res = push_delta_via_composite(
            csv_path=csv_file,
            object_name="BT Project",
            report_name="Apollo 10G",
        )

        assert res.total_records == 2
        assert res.successful_records == 1
        assert res.failed_records == 1
        assert res.all_succeeded is False
        assert len(res.failures) == 1
        assert "Document required" in res.failures[0]["sf__Error"]
        assert res.failures_csv_path is not None
        assert res.failures_csv_path.exists()
