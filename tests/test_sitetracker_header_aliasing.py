"""Unit and integration tests for Sitetracker header self-healing aliasing and universal column resolution."""

from __future__ import annotations

import pandas as pd
import pytest

from core.normalizer import DataNormalizer


class TestResolveSourceColumn:
    """Test DataNormalizer.resolve_source_column under all hierarchy and casing conditions."""

    def test_exact_match_source_col(self):
        candidates = ["Project Ref", "Random Col", "Status"]
        resolved = DataNormalizer.resolve_source_column(
            candidates, s_col="Project Ref", st_col="Project Reference", api_col="Project_Reference__c"
        )
        assert resolved == "Project Ref"

    def test_fallback_to_sitetracker_col(self):
        candidates = ["Project Reference", "Random Col", "Status"]
        resolved = DataNormalizer.resolve_source_column(
            candidates, s_col="Project Ref", st_col="Project Reference", api_col="Project_Reference__c"
        )
        assert resolved == "Project Reference"

    def test_fallback_to_api_col(self):
        candidates = ["Project_Reference__c", "Random Col", "Status"]
        resolved = DataNormalizer.resolve_source_column(
            candidates, s_col="Project Ref", st_col="Project Reference", api_col="Project_Reference__c"
        )
        assert resolved == "Project_Reference__c"

    def test_case_insensitive_match_source_col(self):
        candidates = ["ran priority", "Random Col"]
        resolved = DataNormalizer.resolve_source_column(
            candidates, s_col="RAN Priority", st_col="Ran Priority", api_col="Ran_Priority__c"
        )
        # Sitetracker col exact match takes precedence if present, but here only "ran priority" (all lowercase) exists
        assert resolved == "ran priority"

    def test_case_insensitive_match_sitetracker_col(self):
        candidates = ["ran priority", "Other Col"]
        resolved = DataNormalizer.resolve_source_column(
            candidates, s_col="Vendor Col", st_col="Ran Priority", api_col="Ran_Priority__c"
        )
        assert resolved == "ran priority"

    def test_whitespace_tolerance(self):
        candidates = ["  Project Reference  ", "Status"]
        resolved = DataNormalizer.resolve_source_column(
            candidates, s_col="Project Ref", st_col="Project Reference", api_col="Project_Reference__c"
        )
        assert resolved == "Project Reference"

    def test_no_match_returns_none(self):
        candidates = ["Completely Unrelated", "Another Col"]
        resolved = DataNormalizer.resolve_source_column(
            candidates, s_col="Project Ref", st_col="Project Reference", api_col="Project_Reference__c"
        )
        assert resolved is None

    def test_none_and_nan_tolerance(self):
        candidates = ["ColA", "ColB", None, float("nan"), ""]
        resolved = DataNormalizer.resolve_source_column(
            candidates, s_col="ColA", st_col=None, api_col="nan"
        )
        assert resolved == "ColA"


class TestValidatorWithSitetrackerHeaders:
    """Verify that InputValidator accepts source files whose columns match Sitetracker field names."""

    def test_validator_accepts_sitetracker_headers(self, tmp_path, monkeypatch):
        from config import settings
        from core.validator import InputValidator

        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

        work_dir = tmp_path / "Apollo_10G"
        src_dir = work_dir / "input" / "source"
        st_dir = work_dir / "input" / "sitetracker"
        src_dir.mkdir(parents=True)
        st_dir.mkdir(parents=True)

        # Source CSV uses Sitetracker Field Names (e.g. 'Project Reference', 'Ran Priority', etc.)
        pd.DataFrame([{
            "Project ID": "P-192182",
            "Project Reference": "PX71-SG-CKJJONJ",
            "HE/MEAS Delay Status": "BT - WTG FIBRE TO BE SCHEDULED",
            "Firm Order Placed": "13/12/2018",
            "Ran Priority": "Huawei",
            "NIA Order Delivery (A)": "",
            "Transmission Delivered (A)": "31/10/2025",
            "Transmission Delivered (F)": "",
            "COC Uploaded": "06/07/2019",
            "PRTC (A)": "",
            "PRTC (F)": "",
            "HE/MEAS Status": "18.2 CAB SWAP OR READY",
            "Project": "P-192182",
            "WES PSID": "BTWD217198",
        }]).to_csv(src_dir / "Project Delivery Status Log- Testing .csv", index=False)

        # Sitetracker baseline
        pd.DataFrame([{
            "Id": "a1e4J000000CK3YQAW",
            "Project Reference": "PX71-SG-CKJJONJ",
            "WES PSID": "BTWD217198",
            "HE/MEAS Status": "18.2 CAB SWAP OR READY",
            "Ran Priority": "Cisco",
            "HE/MEAS Delay Status": "1ST PARTY WAYLEAVE PERMISSIONS",
            "NIA Order Delivery (A)": "",
            "Firm Order Placed": "2018-12-13",
            "Transmission Delivered (A)": "2025-10-31",
            "COC Uploaded": "2019-07-06",
            "Transmission Delivered (F)": "",
            "PRTC (F)": "",
            "PRTC (A)": "",
        }]).to_csv(st_dir / "Apollo_10G_sitetracker_live.csv", index=False)

        validator = InputValidator("Apollo 10G")
        result = validator.validate_all()

        assert result.is_valid is True, f"Validation errors: {result.errors}"
        assert len(result.errors) == 0


class TestEngineWithSitetrackerHeaders:
    """Verify that InputFileEngine processes Sitetracker header spreadsheets end-to-end."""

    def test_engine_processes_sitetracker_headers(self, tmp_path, monkeypatch):
        from config import settings
        from core.engine import InputFileEngine

        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

        work_dir = tmp_path / "Apollo_10G"
        src_dir = work_dir / "input" / "source"
        st_dir = work_dir / "input" / "sitetracker"
        runs_dir = work_dir / "runs"
        archive_dir = work_dir / "archive"
        src_dir.mkdir(parents=True)
        st_dir.mkdir(parents=True)
        runs_dir.mkdir(parents=True)
        archive_dir.mkdir(parents=True)

        # Source CSV with Sitetracker Field Names and 2 deliberate deltas:
        # 1. Ran Priority changed from Cisco to Huawei
        # 2. HE/MEAS Delay Status changed from '1ST PARTY...' to 'BT - WTG...'
        pd.DataFrame([{
            "Project ID": "P-192182",
            "Project Reference": "PX71-SG-CKJJONJ",
            "HE/MEAS Delay Status": "BT - WTG FIBRE TO BE SCHEDULED",
            "Firm Order Placed": "13/12/2018",
            "Ran Priority": "Huawei",
            "NIA Order Delivery (A)": "",
            "Transmission Delivered (A)": "31/10/2025",
            "Transmission Delivered (F)": "",
            "COC Uploaded": "06/07/2019",
            "PRTC (A)": "",
            "PRTC (F)": "",
            "HE/MEAS Status": "18.2 CAB SWAP OR READY",
            "Project": "P-192182",
            "WES PSID": "BTWD217198",
        }]).to_csv(src_dir / "Project Delivery Status Log- Testing .csv", index=False)

        # Sitetracker baseline
        pd.DataFrame([{
            "Id": "a1e4J000000CK3YQAW",
            "Project Reference": "PX71-SG-CKJJONJ",
            "WES PSID": "BTWD217198",
            "HE/MEAS Status": "18.2 CAB SWAP OR READY",
            "Ran Priority": "Cisco",
            "HE/MEAS Delay Status": "1ST PARTY WAYLEAVE PERMISSIONS",
            "NIA Order Delivery (A)": "",
            "Firm Order Placed": "2018-12-13",
            "Transmission Delivered (A)": "2025-10-31",
            "COC Uploaded": "2019-07-06",
            "Transmission Delivered (F)": "",
            "PRTC (F)": "",
            "PRTC (A)": "",
        }]).to_csv(st_dir / "Apollo_10G_sitetracker_live.csv", index=False)

        engine = InputFileEngine("Apollo 10G")
        result = engine.run(skip_validation=False)

        assert result.success is True
        assert result.total_source_records == 1
        assert result.valid_source_records == 1
        assert result.delta_records == 1
        assert result.field_changes_count == 2

        # Check standard 5 output contracts
        assert (result.run_dir / "final_input_file.csv").exists()
        assert (result.run_dir / "field_level_changes.csv").exists()
        assert (result.run_dir / "rollback_file.csv").exists()
        assert (result.run_dir / "run_summary.txt").exists()

        # Verify no false date delta was generated for COC Uploaded (2019-07-06 vs 06/07/2019)
        changes_df = pd.read_csv(result.run_dir / "field_level_changes.csv")
        assert len(changes_df) == 2
        assert "COC Uploaded" not in changes_df["Sitetracker Column"].values

        # Check final_input_file.csv contents
        final_df = pd.read_csv(result.run_dir / "final_input_file.csv")
        assert "Id" in final_df.columns
        assert final_df.iloc[0]["Id"] == "a1e4J000000CK3YQAW"
        assert final_df.iloc[0]["Ran_Priority__c"] == "Huawei"
        assert final_df.iloc[0]["HE_MEAS_Delay_Status__c"] == "BT - WTG FIBRE TO BE SCHEDULED"


class TestDataFetcherPKExtraction:
    """Verify that fetch_sitetracker_data_for_report extracts PKs from Sitetracker header spreadsheets."""

    def test_pk_extracted_from_sitetracker_header(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock
        from config import settings
        from salesforce.data_fetcher import fetch_sitetracker_data

        monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

        work_dir = tmp_path / "Apollo_10G"
        src_dir = work_dir / "input" / "source"
        src_dir.mkdir(parents=True)

        pd.DataFrame([{
            "Project ID": "P-192182",
            "Project Reference": "PX71-SG-CKJJONJ",
            "Ran Priority": "Huawei",
        }]).to_csv(src_dir / "test_source.csv", index=False)

        # Mock Salesforce connection to capture query or return dummy
        mock_sf = MagicMock()
        mock_sf.query_all.return_value = {
            "totalSize": 1,
            "done": True,
            "records": [{
                "Id": "a1e4J000000CK3YQAW",
                "Project_Reference__c": "PX71-SG-CKJJONJ",
            }]
        }
        monkeypatch.setattr("salesforce.data_fetcher.get_sf_connection", lambda profile: mock_sf)

        saved_path = fetch_sitetracker_data("Apollo 10G", source_file=src_dir / "test_source.csv")
        assert saved_path is not None
        assert saved_path.exists()
        # Verify query was called with WHERE Project_Reference__c IN ('PX71-SG-CKJJONJ')
        assert mock_sf.query_all.called
        query_str = mock_sf.query_all.call_args[0][0]
        assert "PX71-SG-CKJJONJ" in query_str



