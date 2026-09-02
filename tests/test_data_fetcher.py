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
