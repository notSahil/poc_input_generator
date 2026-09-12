"""Tests for core/manual_engine.py and salesforce/adhoc_fetcher.py."""

from pathlib import Path
import pandas as pd
import pytest

from core.manual_engine import (
    AdhocEngineConfig,
    AdhocFieldMapping,
    ManualLoadEngine,
    resolve_pk_and_fields_for_query,
    suggest_field_mappings,
)
from salesforce.adhoc_fetcher import chunk_identifiers


class TestChunkIdentifiers:
    """Tests for URL-safe SOQL chunking."""

    def test_chunking_respects_batch_size(self):
        # Arrange
        pks = [f"ID_{i:04d}" for i in range(250)]

        # Act
        chunks = chunk_identifiers(pks, max_batch_size=100, max_query_length=10000)

        # Assert
        assert len(chunks) == 3
        assert len(chunks[0]) == 100
        assert len(chunks[1]) == 100
        assert len(chunks[2]) == 50

    def test_chunking_respects_max_query_length(self):
        # Arrange
        long_pks = ["VERY_LONG_PRIMARY_KEY_STRING_VAL_" + str(i) for i in range(50)]

        # Act
        chunks = chunk_identifiers(long_pks, max_batch_size=500, max_query_length=200)

        # Assert
        assert len(chunks) > 1
        for chunk in chunks:
            total_len = sum(len(x) + 4 for x in chunk)
            assert total_len <= 200 or len(chunk) == 1


class TestSuggestFieldMappings:
    """Tests for intelligent auto-matching algorithm."""

    def test_exact_and_normalized_matching(self):
        # Arrange
        source_cols = ["Site_ID", "Site Name", "Start_Date", "Unmatched_Col"]
        sf_fields = [
            {"api_name": "sitetracker__Site_ID__c", "label": "Site ID", "data_type": "text"},
            {"api_name": "Site_Name__c", "label": "Site Name", "data_type": "text"},
            {"api_name": "Start_Date__c", "label": "Project Start Date", "data_type": "date"},
            {"api_name": "Other_Field__c", "label": "Other", "data_type": "text"},
        ]

        # Act
        mappings = suggest_field_mappings(
            source_cols, sf_fields, source_pk_col="Site_ID", target_pk_field="sitetracker__Site_ID__c"
        )

        # Assert
        assert len(mappings) == 4

        site_id_map = next(m for m in mappings if m.source_column == "Site_ID")
        assert site_id_map.target_field_api == "sitetracker__Site_ID__c"
        assert site_id_map.upload_enabled is False  # Primary key is lookup-only, never updated

        name_map = next(m for m in mappings if m.source_column == "Site Name")
        assert name_map.target_field_api == "Site_Name__c"
        assert name_map.upload_enabled is True

        start_date_map = next(m for m in mappings if m.source_column == "Start_Date")
        assert start_date_map.target_field_api == "Start_Date__c"
        assert start_date_map.data_type == "date"
        assert start_date_map.upload_enabled is True

        unmatched_map = next(m for m in mappings if m.source_column == "Unmatched_Col")
        assert unmatched_map.target_field_api == ""
        assert unmatched_map.upload_enabled is False

    def test_canonical_mapping_file_matching(self):
        # Arrange - Master Site Listing columns
        source_cols = ["TM Cell ID", "Site_on_Master_Site_List__c", "Date_of_Master_Site_Listing__c"]
        sf_fields = [
            {"api_name": "Name", "label": "TM Cell ID", "data_type": "text"},
            {"api_name": "Site_on_Master_Site_List__c", "label": "Site on Master Site List", "data_type": "text"},
            {"api_name": "Date_of_Master_Site_Listing__c", "label": "Date of Master Site Listing", "data_type": "date"},
        ]

        # Act
        mappings = suggest_field_mappings(source_cols, sf_fields, object_name="sitetracker__Site__c")

        # Assert
        tm_map = next(m for m in mappings if m.source_column == "TM Cell ID")
        assert tm_map.target_field_api == "Name"
        assert tm_map.upload_enabled is True

        site_list_map = next(m for m in mappings if m.source_column == "Site_on_Master_Site_List__c")
        assert site_list_map.target_field_api == "Site_on_Master_Site_List__c"
        assert site_list_map.upload_enabled is True

    def test_matched_fields_sorted_first_and_pk_at_top(self):
        # Arrange - mix of unmapped, matched, and PK columns
        source_cols = ["Random_Unmapped_1", "Site_on_Master_Site_List__c", "Id", "Random_Unmapped_2", "TM Cell ID"]
        sf_fields = [
            {"api_name": "Id", "label": "Record ID", "data_type": "text"},
            {"api_name": "Name", "label": "TM Cell ID", "data_type": "text"},
            {"api_name": "Site_on_Master_Site_List__c", "label": "Site on Master Site List", "data_type": "text"},
        ]

        # Act
        mappings = suggest_field_mappings(
            source_cols, sf_fields, source_pk_col="Id", target_pk_field="Id", object_name="sitetracker__Site__c"
        )

        # Assert:
        # Rank 0: Id (PK)
        # Rank 1: Site_on_Master_Site_List__c, TM Cell ID (matched)
        # Rank 2: Random_Unmapped_1, Random_Unmapped_2 (unmapped)
        assert mappings[0].source_column == "Id"
        assert mappings[0].target_field_api == "Id"
        assert mappings[0].upload_enabled is False

        assert mappings[1].source_column == "Site_on_Master_Site_List__c"
        assert mappings[1].target_field_api == "Site_on_Master_Site_List__c"
        assert mappings[1].upload_enabled is True

        assert mappings[2].source_column == "TM Cell ID"
        assert mappings[2].target_field_api == "Name"
        assert mappings[2].upload_enabled is True

        assert mappings[3].source_column == "Random_Unmapped_1"
        assert mappings[3].target_field_api == ""
        assert mappings[3].upload_enabled is False

        assert mappings[4].source_column == "Random_Unmapped_2"
        assert mappings[4].target_field_api == ""
        assert mappings[4].upload_enabled is False


class TestDetectTargetObject:
    """Tests for target object auto-detection from uploaded spreadsheet headers."""

    def test_detects_site_object(self):
        from core.manual_engine import detect_target_object
        cols = ["Id", "TM Cell ID", "Site_on_Master_Site_List__c", "Date_of_Master_Site_Listing__c"]
        assert detect_target_object(cols) == "sitetracker__Site__c"

    def test_detects_bt_project_object(self):
        from core.manual_engine import detect_target_object
        cols = ["Project Ref", "RAN Priority", "HE/MEAS Delay"]
        assert detect_target_object(cols) == "BT_Project__c"

    def test_detects_none_for_unknown_columns(self):
        from core.manual_engine import detect_target_object
        cols = ["Col_Alpha", "Random_Data_123", "Some_Number"]
        assert detect_target_object(cols) is None


class TestSalesforceIdValidation:
    """Tests for Salesforce ID syntax validation and filtering."""

    def test_valid_and_invalid_ids(self):
        from salesforce.adhoc_fetcher import is_valid_salesforce_id
        # Valid 15 and 18 character IDs
        assert is_valid_salesforce_id("0015g00000abcde") is True
        assert is_valid_salesforce_id("0015g00000abcdeAAA") is True
        assert is_valid_salesforce_id("a012w00000abcdeAAA") is True

        # Invalid IDs
        assert is_valid_salesforce_id("a012w00000000001AAA") is False  # 19 chars
        assert is_valid_salesforce_id("SITE-001") is False  # Non-alphanumeric
        assert is_valid_salesforce_id("") is False
        assert is_valid_salesforce_id("123") is False


class TestManualLoadEngine:
    """Tests for ManualLoadEngine execution, deltas, and artifact generation."""

    @pytest.fixture
    def mock_data(self):
        source_df = pd.DataFrame([
            # Row 1: Normal update (Site name changed, date formatted)
            {"Site_ID": "SITE-001", "Site_Name": "New Site Alpha", "Live_Date": "25/12/2026", "Status": "Active"},
            # Row 2: Duplicate PK (First occurrence wins)
            {"Site_ID": "SITE-001", "Site_Name": "Duplicate Site Alpha", "Live_Date": "25/12/2026", "Status": "Active"},
            # Row 3: Unchanged record
            {"Site_ID": "SITE-002", "Site_Name": "Beta Existing", "Live_Date": "01/01/2026", "Status": "Active"},
            # Row 4: PK not in Salesforce (Skipped)
            {"Site_ID": "SITE-999", "Site_Name": "Ghost Site", "Live_Date": "01/01/2026", "Status": "Active"},
            # Row 5: Clear field back to blank (testing #N/A)
            {"Site_ID": "SITE-003", "Site_Name": "", "Live_Date": "05/05/2026", "Status": "Inactive"},
        ])

        live_sf_df = pd.DataFrame([
            {"Id": "a0010000001AlphaAAA", "Site_ID__c": "SITE-001", "Site_Name__c": "Old Site Alpha", "Live_Date__c": "2026-01-01", "Status__c": "Active"},
            {"Id": "a0010000002BetaBBB", "Site_ID__c": "SITE-002", "Site_Name__c": "Beta Existing", "Live_Date__c": "2026-01-01", "Status__c": "Active"},
            {"Id": "a0010000003GammaCCC", "Site_ID__c": "SITE-003", "Site_Name__c": "Original Gamma Name", "Live_Date__c": "2026-05-05", "Status__c": "Inactive"},
        ])

        return source_df, live_sf_df

    def test_engine_delta_and_artifacts(self, tmp_path, mock_data):
        # Arrange
        source_df, live_sf_df = mock_data
        run_dir = tmp_path / "test_run"

        mappings = [
            AdhocFieldMapping("Site_ID", "Site_ID__c", "Site ID", data_type="text", upload_enabled=False),
            AdhocFieldMapping("Site_Name", "Site_Name__c", "Site Name", data_type="text", upload_enabled=True),
            AdhocFieldMapping("Live_Date", "Live_Date__c", "Live Date", data_type="date", upload_enabled=True),
            AdhocFieldMapping("Status", "Status__c", "Status", data_type="text", upload_enabled=True),
        ]

        config = AdhocEngineConfig(
            object_name="sitetracker__Site__c",
            source_pk_col="Site_ID",
            target_pk_field="Site_ID__c",
            sf_id_field="Id",
            insert_nulls=True,
            mappings=mappings,
        )

        engine = ManualLoadEngine(config, custom_run_dir=run_dir)

        # Act
        result = engine.run(source_df, live_sf_df)

        # Assert Metrics
        assert result.total_source_rows == 5
        assert result.duplicate_pks == 1
        assert result.skipped_pks == 1
        assert result.changed_records == 2  # SITE-001 (Name + Date) and SITE-003 (Name cleared to #N/A)
        assert result.unchanged_records == 1  # SITE-002

        # Assert Artifacts Exist
        assert result.artifacts["final_input_file"].exists()
        assert result.artifacts["rollback_file"].exists()
        assert result.artifacts["field_level_changes"].exists()
        assert result.artifacts["duplicate_primary_keys"].exists()
        assert result.artifacts["skipped_records"].exists()
        assert result.artifacts["run_summary"].exists()

        # Assert final_input_file.csv contents
        final_df = pd.read_csv(result.artifacts["final_input_file"], dtype=str, keep_default_na=False)
        assert len(final_df) == 2
        assert "Id" in final_df.columns
        assert "Site_ID" not in final_df.columns  # Dropped from upload payload

        # Check SITE-001
        row_001 = final_df[final_df["Id"] == "a0010000001AlphaAAA"].iloc[0]
        assert row_001["Site_Name__c"] == "New Site Alpha"
        assert row_001["Live_Date__c"] == "25/12/2026"  # UK date formatting

        # Check SITE-003 cleared to #N/A
        row_003 = final_df[final_df["Id"] == "a0010000003GammaCCC"].iloc[0]
        assert row_003["Site_Name__c"] == "#N/A"

        # Assert rollback_file.csv contents
        rollback_df = pd.read_csv(result.artifacts["rollback_file"], dtype=str)
        assert len(rollback_df) == 2
        rb_row_001 = rollback_df[rollback_df["Id"] == "a0010000001AlphaAAA"].iloc[0]
        assert rb_row_001["Site_Name__c"] == "Old Site Alpha"
        assert rb_row_001["Live_Date__c"] == "2026-01-01"

        rb_row_003 = rollback_df[rollback_df["Id"] == "a0010000003GammaCCC"].iloc[0]
        assert rb_row_003["Site_Name__c"] == "Original Gamma Name"

        # Assert duplicate_primary_keys.csv
        dup_df = pd.read_csv(result.artifacts["duplicate_primary_keys"], dtype=str)
        assert len(dup_df) == 1
        assert dup_df.iloc[0]["Primary_Key"] == "SITE-001"
        assert int(dup_df.iloc[0]["First_Occurrence_Row"]) == 1

        # Assert skipped_records.csv
        skip_df = pd.read_csv(result.artifacts["skipped_records"], dtype=str)
        assert len(skip_df) == 1
        assert skip_df.iloc[0]["Primary_Key"] == "SITE-999"

    def test_engine_when_pk_is_salesforce_id(self, tmp_path):
        # Arrange - source and live where PK is 'Id' (Id -> Id)
        source_df = pd.DataFrame([
            {"Id": "a0010000001AlphaAAA", "Site_Name": "Updated Alpha"},
            {"Id": "a0010000002BetaBBB", "Site_Name": "Unchanged Beta"},
        ])
        live_sf_df = pd.DataFrame([
            {"Id": "a0010000001AlphaAAA", "Site_Name__c": "Old Alpha"},
            {"Id": "a0010000002BetaBBB", "Site_Name__c": "Unchanged Beta"},
        ])
        run_dir = tmp_path / "id_pk_run"

        mappings = [
            AdhocFieldMapping("Id", "Id", "Record ID", data_type="text", upload_enabled=False),
            AdhocFieldMapping("Site_Name", "Site_Name__c", "Site Name", data_type="text", upload_enabled=True),
        ]
        config = AdhocEngineConfig(
            object_name="sitetracker__Site__c",
            source_pk_col="Id",
            target_pk_field="Id",
            sf_id_field="Id",
            insert_nulls=True,
            mappings=mappings,
        )
        engine = ManualLoadEngine(config, custom_run_dir=run_dir)

        # Act
        result = engine.run(source_df, live_sf_df)

        # Assert
        assert result.changed_records == 1
        assert result.unchanged_records == 1
        final_df = pd.read_csv(result.artifacts["final_input_file"], dtype=str)
        assert len(final_df) == 1
        assert final_df.iloc[0]["Id"] == "a0010000001AlphaAAA"
        assert final_df.iloc[0]["Site_Name__c"] == "Updated Alpha"

    def test_engine_both_blank_or_none_not_flagged_as_delta(self, tmp_path):
        # Arrange - Source has empty string "", Salesforce has None (both are empty)
        source_df = pd.DataFrame([
            {"Id": "a0010000001AlphaAAA", "Site_Name": ""},
        ])
        live_sf_df = pd.DataFrame([
            {"Id": "a0010000001AlphaAAA", "Site_Name__c": None},
        ])
        run_dir = tmp_path / "both_blank_run"

        mappings = [
            AdhocFieldMapping("Id", "Id", "Record ID", data_type="text", upload_enabled=False),
            AdhocFieldMapping("Site_Name", "Site_Name__c", "Site Name", data_type="text", upload_enabled=True),
        ]
        config = AdhocEngineConfig(
            object_name="sitetracker__Site__c",
            source_pk_col="Id",
            target_pk_field="Id",
            sf_id_field="Id",
            insert_nulls=True,  # Even with insert_nulls=True, empty to empty must NOT be a delta
            mappings=mappings,
        )
        engine = ManualLoadEngine(config, custom_run_dir=run_dir)

        # Act
        result = engine.run(source_df, live_sf_df)

        # Assert: No change should be recorded since both are already blank/None
        assert result.changed_records == 0
        assert result.unchanged_records == 1
        changes_df = pd.read_csv(result.artifacts["field_level_changes"])
        assert len(changes_df) == 0

from unittest.mock import MagicMock, patch
from salesforce.adhoc_fetcher import fetch_all_objects, fetch_object_fields, fetch_adhoc_live_data


class TestAdhocFetcher:
    """Unit tests for salesforce/adhoc_fetcher.py with mocked SF client."""

    @patch("salesforce.adhoc_fetcher.get_sf_connection")
    def test_fetch_all_objects(self, mock_get_sf):
        mock_sf = MagicMock()
        mock_sf.describe.return_value = {
            "sobjects": [
                {"name": "sitetracker__Site__c", "label": "Site", "custom": True, "queryable": True, "updateable": True},
                {"name": "Account", "label": "Account", "custom": False, "queryable": True, "updateable": True},
                {"name": "Read_Only__c", "label": "Read Only", "custom": True, "queryable": True, "updateable": False, "createable": False},
            ]
        }
        mock_get_sf.return_value = mock_sf

        objects = fetch_all_objects()
        assert len(objects) == 2
        assert objects[0]["name"] == "sitetracker__Site__c"
        assert objects[0]["category"] == "Sitetracker"
        assert objects[1]["name"] == "Account"
        assert objects[1]["category"] == "Standard"

    @patch("salesforce.adhoc_fetcher.get_sf_connection")
    def test_fetch_object_fields(self, mock_get_sf):
        mock_sf = MagicMock()
        mock_site_obj = MagicMock()
        mock_site_obj.describe.return_value = {
            "fields": [
                {"name": "Id", "label": "Record ID", "type": "id", "updateable": False, "externalId": False},
                {"name": "Site_Name__c", "label": "Site Name", "type": "string", "updateable": True, "externalId": False},
                {"name": "Site_Number__c", "label": "Site External ID", "type": "string", "updateable": True, "externalId": True},
            ]
        }
        setattr(mock_sf, "sitetracker__Site__c", mock_site_obj)
        mock_get_sf.return_value = mock_sf

        fields = fetch_object_fields("sitetracker__Site__c")
        assert len(fields) == 3
        api_names = [f["api_name"] for f in fields]
        assert "Id" in api_names
        assert "Site_Name__c" in api_names
        assert "Site_Number__c" in api_names

    @patch("salesforce.adhoc_fetcher.get_sf_connection")
    def test_fetch_adhoc_live_data(self, mock_get_sf):
        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {
            "records": [
                {"Id": "001AAA", "Site_ID__c": "S-1", "Name": "Alpha", "attributes": {"type": "Site"}},
                {"Id": "002BBB", "Site_ID__c": "S-2", "Name": "Beta", "attributes": {"type": "Site"}},
            ]
        }
        mock_get_sf.return_value = mock_sf

        df = fetch_adhoc_live_data("sitetracker__Site__c", ["Name"], "Site_ID__c", ["S-1", "S-2"])
        assert len(df) == 2
        assert "Id" in df.columns
        assert "Site_ID__c" in df.columns
        assert "Name" in df.columns
        assert "attributes" not in df.columns

    def test_engine_zero_changes_does_not_produce_empty_files(self, tmp_path):
        """Ensure that when there are zero changes, artifacts have headers and don't fail pd.read_csv."""
        # Arrange
        source_df = pd.DataFrame([
            {"Site_ID": "SITE-100", "Site_Name": "Identical Name"}
        ])
        live_sf_df = pd.DataFrame([
            {"Id": "001XYZ", "Site_ID__c": "SITE-100", "Site_Name__c": "Identical Name"}
        ])
        mappings = [
            AdhocFieldMapping("Site_ID", "Site_ID__c", "Site ID", data_type="text", upload_enabled=False),
            AdhocFieldMapping("Site_Name", "Site_Name__c", "Site Name", data_type="text", upload_enabled=True),
        ]
        config = AdhocEngineConfig("Site__c", "Site_ID", "Site_ID__c", "Id", True, mappings)
        engine = ManualLoadEngine(config, custom_run_dir=tmp_path / "zero_run")

        # Act
        result = engine.run(source_df, live_sf_df)

        # Assert
        assert result.changed_records == 0
        assert result.unchanged_records == 1

        # All artifact files MUST be parseable by pd.read_csv without EmptyDataError
        for key, path in result.artifacts.items():
            if path.suffix == ".csv":
                df = pd.read_csv(path, dtype=str)
                assert isinstance(df, pd.DataFrame)

    def test_resolve_pk_and_fields_for_query_master_site_listing(self):
        """Verify TM Cell ID resolves to Name and mapped fields are found."""
        cols = ["TM Cell ID", "Date of Master Site Listing", "Site on Master Site List"]
        pk_src, pk_sf, fields = resolve_pk_and_fields_for_query("sitetracker__Site__c", cols)
        assert pk_src == "TM Cell ID"
        assert pk_sf == "Name"
        assert "Date_of_Master_Site_Listing__c" in fields
        assert "Site_on_Master_Site_List__c" in fields

    def test_resolve_pk_and_fields_for_query_explicit_id(self):
        """Verify Record ID explicitly maps to Id."""
        cols = ["Record ID (Site)", "Site Name"]
        pk_src, pk_sf, fields = resolve_pk_and_fields_for_query("sitetracker__Site__c", cols)
        assert pk_src == "Record ID (Site)"
        assert pk_sf == "Id"

    def test_engine_offline_baseline_column_name_fallback(self, tmp_path):
        """Verify engine works when offline baseline has source column names instead of SF API names."""
        source_df = pd.DataFrame([
            {"TM Cell ID": "10140", "Site on Master Site List": "Yes"}
        ])
        # Baseline uses 'TM Cell ID' column instead of 'Name'
        live_sf_df = pd.DataFrame([
            {"Id": "a0p4J000000Dn1lQAC", "TM Cell ID": "10140", "Site on Master Site List": "No"}
        ])
        mappings = [
            AdhocFieldMapping("TM Cell ID", "Name", "TM Cell ID", upload_enabled=False),
            AdhocFieldMapping("Site on Master Site List", "Site_on_Master_Site_List__c", "Site on Master Site List", upload_enabled=True),
        ]
        config = AdhocEngineConfig("sitetracker__Site__c", "TM Cell ID", "Name", "Id", True, mappings)
        engine = ManualLoadEngine(config, custom_run_dir=tmp_path / "offline_fallback_run")

        result = engine.run(source_df, live_sf_df)
        assert result.changed_records == 1
        assert result.total_source_rows == 1

