"""Unit tests for MappingLoader."""

import pytest
from core.exceptions import MappingError, MappingFileNotFoundError
from core.mapping_loader import MappingLoader


class TestMappingLoader:
    def test_load_valid_mapping(self, test_mapping_file):
        loader = MappingLoader(test_mapping_file, "Test Report")
        df = loader.load()
        assert not df.empty
        assert len(df) == 3

    def test_missing_file_raises_error(self, tmp_path):
        loader = MappingLoader(tmp_path / "non_existent.xlsx", "Test Report")
        with pytest.raises(MappingFileNotFoundError):
            loader.load()

    def test_unknown_report_raises_mapping_error(self, test_mapping_file):
        loader = MappingLoader(test_mapping_file, "Unknown Report")
        with pytest.raises(MappingError) as exc_info:
            loader.load()
        assert "No mapping rows found for report 'Unknown Report'" in str(exc_info.value)

    def test_primary_keys(self, test_mapping_file):
        loader = MappingLoader(test_mapping_file, "Test Report")
        pk_src, pk_st = loader.primary_keys()
        assert pk_src == "Site Reference"
        assert pk_st == "Site_Ref__c"

    def test_field_mapping(self, test_mapping_file):
        loader = MappingLoader(test_mapping_file, "Test Report")
        field_map = loader.field_mapping()
        assert len(field_map) == 3
        # First mapping item
        assert field_map[0] == ("Site Reference", "Site_Ref__c", "Site_Ref__c", "text")
        # Date mapping item
        assert field_map[2] == ("Target Date", "Target_Date__c", "Target_Date__c", "date")

    def test_objects_and_all_primary_keys(self, test_mapping_file):
        loader = MappingLoader(test_mapping_file, "Test Report")
        pks = loader.all_primary_keys()
        assert len(pks) >= 1
        assert pks[0]["source"] == "Site Reference"
        assert pks[0]["sitetracker"] == "Site_Ref__c"

        objs = loader.objects()
        assert isinstance(objs, list)
