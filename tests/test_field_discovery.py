"""Unit tests for salesforce/field_discovery.py."""

from unittest.mock import MagicMock, patch
import pytest

from salesforce.field_discovery import discover_object_fields, map_sf_type


def test_map_sf_type():
    assert map_sf_type("string") == "text"
    assert map_sf_type("textarea") == "text"
    assert map_sf_type("picklist") == "text"
    assert map_sf_type("date") == "date"
    assert map_sf_type("datetime") == "date"
    assert map_sf_type("double") == "number"
    assert map_sf_type("currency") == "number"
    assert map_sf_type("int") == "number"
    assert map_sf_type("boolean") == "boolean"
    assert map_sf_type("unknown_custom_type") == "text"


def test_discover_object_fields_success():
    mock_describe_result = {
        "fields": [
            {
                "name": "Id",
                "label": "Record ID",
                "type": "id",
                "updateable": False,
                "externalId": False
            },
            {
                "name": "Site_Number__c",
                "label": "Site Number",
                "type": "string",
                "updateable": True,
                "externalId": True
            },
            {
                "name": "Target_Date__c",
                "label": "Target Date",
                "type": "date",
                "updateable": True,
                "externalId": False
            },
            {
                "name": "CreatedDate",
                "label": "Created Date",
                "type": "datetime",
                "updateable": False,
                "externalId": False
            }
        ]
    }

    mock_sf = MagicMock()
    mock_obj = MagicMock()
    mock_obj.describe.return_value = mock_describe_result
    setattr(mock_sf, "Site__c", mock_obj)

    with patch("salesforce.field_discovery.get_sf_connection", return_value=mock_sf):
        fields = discover_object_fields("Site")

        assert len(fields) == 3  # Id, Site_Number__c, Target_Date__c (CreatedDate filtered out)
        api_names = [f["API Name"] for f in fields]
        assert "Id" in api_names
        assert "Site_Number__c" in api_names
        assert "Target_Date__c" in api_names
        assert "CreatedDate" not in api_names

        site_num_field = next(f for f in fields if f["API Name"] == "Site_Number__c")
        assert site_num_field["Data Type"] == "text"
        assert site_num_field["Is External ID"] == "Yes"
        assert site_num_field["Sitetracker Field Name"] == "Site Number"
