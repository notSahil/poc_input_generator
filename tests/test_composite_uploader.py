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


def test_composite_uploader_omits_unchanged_fields(tmp_path):
    """Verify that empty/None fields are OMITTED from the JSON payload
    to prevent Salesforce from wiping existing values (ADR 27)."""
    # Simulate pd.DataFrame column alignment: Row 1 has Field_A, Row 2 has Field_B.
    # After CSV round-trip, each row has an empty cell for the other's field.
    csv_file = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": "a1e001", "Field_A__c": "val_a", "Field_B__c": ""},
        {"Id": "a1e002", "Field_A__c": "", "Field_B__c": "val_b"},
    ])
    df.to_csv(csv_file, index=False)

    mock_sf = MagicMock()
    captured_payloads = []
    def capture_restful(path, method, json, **kwargs):
        captured_payloads.append(json)
        return [{"id": r["Id"], "success": True, "errors": []} for r in json["records"]]
    mock_sf.restful.side_effect = capture_restful

    with patch("salesforce.composite_uploader.get_sf_connection", return_value=mock_sf):
        push_delta_via_composite(
            csv_path=csv_file, object_name="BT Project", report_name=None,
        )

    sent_records = captured_payloads[0]["records"]

    # Record 1: must have Field_A__c, must NOT have Field_B__c
    rec1 = sent_records[0]
    assert rec1["Id"] == "a1e001"
    assert rec1["Field_A__c"] == "val_a"
    assert "Field_B__c" not in rec1, "Empty field should be omitted, not sent as null"

    # Record 2: must have Field_B__c, must NOT have Field_A__c
    rec2 = sent_records[1]
    assert rec2["Id"] == "a1e002"
    assert rec2["Field_B__c"] == "val_b"
    assert "Field_A__c" not in rec2, "Empty field should be omitted, not sent as null"


def test_composite_uploader_respects_explicit_null_wipes(tmp_path):
    """Verify that #N/A values are correctly sent as null (JSON null)
    to explicitly clear fields in Salesforce."""
    csv_file = tmp_path / "final_input_file.csv"
    df = pd.DataFrame([
        {"Id": "a1e001", "Ran_Priority__c": "#N/A", "Order_Placed__c": "2022-07-27"},
    ])
    df.to_csv(csv_file, index=False)

    mock_sf = MagicMock()
    captured_payloads = []
    def capture_restful(path, method, json, **kwargs):
        captured_payloads.append(json)
        return [{"id": r["Id"], "success": True, "errors": []} for r in json["records"]]
    mock_sf.restful.side_effect = capture_restful

    with patch("salesforce.composite_uploader.get_sf_connection", return_value=mock_sf):
        push_delta_via_composite(
            csv_path=csv_file, object_name="BT Project", report_name="Apollo 10G",
        )

    rec = captured_payloads[0]["records"][0]
    assert rec["Id"] == "a1e001"
    assert rec["Ran_Priority__c"] is None, "#N/A must become JSON null to wipe field"
    assert rec["Order_Placed__c"] == "2022-07-27", "Non-#N/A value must be preserved"


def test_composite_uploader_rollback_preserves_null_wipes(tmp_path):
    """Verify that rollback operations send empty fields as null
    to restore the original blank/null state in Salesforce."""
    csv_file = tmp_path / "rollback_file.csv"  # 'rollback' in name triggers is_rb
    df = pd.DataFrame([
        {"Id": "a1e001", "Ran_Priority__c": "NOKIA", "Order_Placed__c": ""},
    ])
    df.to_csv(csv_file, index=False)

    mock_sf = MagicMock()
    captured_payloads = []
    def capture_restful(path, method, json, **kwargs):
        captured_payloads.append(json)
        return [{"id": r["Id"], "success": True, "errors": []} for r in json["records"]]
    mock_sf.restful.side_effect = capture_restful

    with patch("salesforce.composite_uploader.get_sf_connection", return_value=mock_sf):
        push_delta_via_composite(
            csv_path=csv_file, object_name="BT Project", report_name="Apollo 10G",
        )

    rec = captured_payloads[0]["records"][0]
    assert rec["Id"] == "a1e001"
    assert rec["Ran_Priority__c"] == "NOKIA", "Non-empty rollback value must be preserved"
    assert "Order_Placed__c" in rec, "Empty rollback field must be included to restore null"
    assert rec["Order_Placed__c"] is None, "Empty rollback field must be sent as null"
