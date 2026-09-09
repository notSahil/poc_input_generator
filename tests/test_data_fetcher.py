"""Unit tests for salesforce/data_fetcher.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from salesforce.data_fetcher import build_soql_for_report, fetch_sitetracker_data


def test_build_soql_for_report():
    soql, obj_name, api_to_st_map = build_soql_for_report("Apollo 10G")

    assert soql.startswith("SELECT ")
    assert " FROM " in soql
    assert "Id" in soql
    assert "Project_Reference__c" in soql
    assert len(api_to_st_map) > 0
    assert api_to_st_map.get("Project_Reference__c") == "Project Reference"


def test_build_soql_for_report_with_target_object():
    soql, obj_name, api_to_st_map = build_soql_for_report("Apollo 10G", target_object="Project")
    assert "FROM" in soql
    assert "Id" in soql
    # Should only contain Project fields, not BT Project fields
    assert "WES_PSID__c" in soql


def test_build_soql_for_report_multi_object_relationships():
    soql, obj_name, api_to_st_map = build_soql_for_report("Apollo 10G")
    assert obj_name == "BT_Project__c"
    assert "FROM BT_Project__c" in soql
    # Primary object fields
    assert "Project_Reference__c" in soql
    # Related object fields via relationship prefix
    assert "Project__r.WES_PSID__c" in soql
    assert "Project__r.HE_MEAS_Status__c" in soql
    # Relationship field mapping
    assert api_to_st_map["Project__r.WES_PSID__c"] == "WES PSID"
    assert api_to_st_map["Project__r.HE_MEAS_Status__c"] == "HE/MEAS Status"


def test_fetch_sitetracker_data_success(tmp_path):
    mock_records = [
        {
            "attributes": {"type": "Project__c", "url": "/services/data/v59.0/sobjects/Project__c/a123"},
            "Id": "a12345678901234567",
            "Project_Reference__c": "PROJ-101",
            "WES_PSID__c": "PSID-999"
        },
        {
            "attributes": {"type": "Project__c", "url": "/services/data/v59.0/sobjects/Project__c/a124"},
            "Id": "a12345678901234568",
            "Project_Reference__c": "PROJ-102",
            "WES_PSID__c": "PSID-998"
        }
    ]

    mock_sf = MagicMock()
    mock_sf.query_all.return_value = {"records": mock_records, "totalSize": 2, "done": True}

    with patch("salesforce.data_fetcher.get_sf_connection", return_value=mock_sf):
        out_csv = fetch_sitetracker_data("Apollo 10G", output_dir=tmp_path)

        assert out_csv.exists()
        assert out_csv.name.endswith(".csv")

        # Read back CSV and verify contents
        df = pd.read_csv(out_csv, dtype=str)
        assert len(df) == 2
        assert "attributes" not in df.columns
        assert "Id" in df.columns
        assert "Project Reference" in df.columns  # Renamed from Project_Reference__c
        assert df.iloc[0]["Project Reference"] == "PROJ-101"


def test_fetch_sitetracker_data_empty_records(tmp_path):
    mock_sf = MagicMock()
    mock_sf.query_all.return_value = {"records": [], "totalSize": 0, "done": True}

    with patch("salesforce.data_fetcher.get_sf_connection", return_value=mock_sf):
        with pytest.raises(ValueError, match="Salesforce query returned 0 records"):
            fetch_sitetracker_data("Apollo 10G", output_dir=tmp_path)


def test_build_soql_for_report_with_pk_filter():
    pks = ["PROJ-101", "PROJ-102", "PROJ-103"]
    soql, obj_name, _ = build_soql_for_report("Apollo 10G", pk_filter_values=pks)

    assert "WHERE Project_Reference__c IN ('PROJ-101', 'PROJ-102', 'PROJ-103')" in soql


def test_build_soql_for_report_pk_sanitization():
    pks = ["PROJ-101", "O'Connor", "Test's"]
    soql, obj_name, _ = build_soql_for_report("Apollo 10G", pk_filter_values=pks)

    assert "WHERE Project_Reference__c IN ('PROJ-101', 'O\\'Connor', 'Test\\'s')" in soql


def test_fetch_sitetracker_data_with_source_file(tmp_path):
    # Create mock source excel file
    src_file = tmp_path / "test_source.xlsx"
    src_df = pd.DataFrame({
        "Project Ref": ["PROJ-101", "PROJ-102"],
        "Notes": ["Alpha", "Beta"]
    })
    src_df.to_excel(src_file, index=False)

    mock_records = [
        {
            "attributes": {"type": "Project__c"},
            "Id": "a12345678901234567",
            "Project_Reference__c": "PROJ-101",
            "WES_PSID__c": "PSID-999"
        },
        {
            "attributes": {"type": "Project__c"},
            "Id": "a12345678901234568",
            "Project_Reference__c": "PROJ-102",
            "WES_PSID__c": "PSID-998"
        }
    ]

    mock_sf = MagicMock()
    mock_sf.query_all.return_value = {"records": mock_records, "totalSize": 2, "done": True}

    with patch("salesforce.data_fetcher.get_sf_connection", return_value=mock_sf) as mock_get_sf:
        out_csv = fetch_sitetracker_data(
            "Apollo 10G",
            output_dir=tmp_path / "st_out",
            source_file=src_file,
            profile="partial"
        )

        mock_get_sf.assert_called_once_with(profile="partial")
        # Verify query had WHERE IN clause
        call_args = mock_sf.query_all.call_args[0][0]
        assert "WHERE Project_Reference__c IN ('PROJ-101', 'PROJ-102')" in call_args

        assert out_csv.exists()
        df = pd.read_csv(out_csv, dtype=str)
        assert len(df) == 2
        assert list(df["Project Reference"]) == ["PROJ-101", "PROJ-102"]


def test_chunk_pks():
    from salesforce.data_fetcher import _chunk_pks
    pks = [f"PX71-CJLKGON{i:05d}" for i in range(9649)]
    chunks = _chunk_pks(pks, max_items=200, max_chars=4000)

    assert len(chunks) > 1
    total_items = sum(len(c) for c in chunks)
    assert total_items == 9649

    for chunk in chunks:
        assert len(chunk) <= 200
        combined_chars = sum(len(x) + 12 for x in chunk)
        # Should never exceed 4,000 chars (with single item leeway)
        assert combined_chars <= 4200


def test_fetch_sitetracker_data_batching(tmp_path):
    src_file = tmp_path / "large_source.csv"
    pks = [f"PROJ-{i:04d}" for i in range(500)]
    pd.DataFrame({"Project Ref": pks}).to_csv(src_file, index=False)

    def mock_query(query):
        records = []
        for pk in pks:
            if pk in query:
                records.append({
                    "attributes": {"type": "Project__c"},
                    "Id": f"a{abs(hash(pk)) % 10000000000000000:017d}",
                    "Project_Reference__c": pk,
                })
        return {"records": records, "totalSize": len(records), "done": True}

    mock_sf = MagicMock()
    mock_sf.query_all.side_effect = mock_query

    with patch("salesforce.data_fetcher.get_sf_connection", return_value=mock_sf):
        out_csv = fetch_sitetracker_data(
            "Apollo 10G",
            output_dir=tmp_path / "st_out",
            source_file=src_file
        )

        assert mock_sf.query_all.call_count >= 2
        df = pd.read_csv(out_csv, dtype=str)
        assert len(df) == 500

