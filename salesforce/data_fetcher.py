"""Fetch live Sitetracker data using SOQL queries generated from field mappings."""

import logging
from pathlib import Path
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from core.mapping_loader import MappingLoader
from salesforce.sf_client import get_sf_connection
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def build_soql_for_report(report_name: str) -> tuple[str, str, dict[str, str]]:
    """
    Build a SOQL query for the given report based on its field mapping.

    Returns:
        tuple of (soql_query, object_name, api_to_st_col_map)
    """
    # 1. Load report YAML configuration
    yaml_cfg = YamlConfigLoader.load(report_name)
    report_cfg = yaml_cfg.get("report", {})
    configured_obj = report_cfg.get("salesforce_object") or report_cfg.get("object")
    sf_id_col = report_cfg.get("sf_id_column", "Id")

    # 2. Load field mapping
    mapping = MappingLoader(settings.MAPPING_FILE, report_name)
    mapping_df = mapping.load()

    # Determine object name
    if configured_obj:
        object_name = str(configured_obj).strip()
    else:
        raw_obj = mapping_df["Object Name"].dropna().iloc[0] if "Object Name" in mapping_df.columns else "Site"
        object_name = str(raw_obj).strip()

    # If object name is Site, map to the real Sitetracker managed package object
    if object_name.lower() in ("site", "site__c"):
        object_name = "sitetracker__Site__c"
    elif " " in object_name and not object_name.endswith("__c"):
        # e.g. "BT Project" -> "BT_Project__c" or fallback
        object_name = f"{object_name.replace(' ', '_')}__c"

    # 3. Collect unique API fields
    api_fields: list[str] = [sf_id_col] if sf_id_col else ["Id"]
    api_to_st_map: dict[str, str] = {}

    for _, row in mapping_df.iterrows():
        api_name = str(row.get("API Name", "")).strip()
        st_field = str(row.get("Sitetracker Field Name", "")).strip()

        if api_name and api_name.lower() != "nan":
            if api_name not in api_fields:
                api_fields.append(api_name)
            if st_field and st_field.lower() != "nan":
                api_to_st_map[api_name] = st_field

    # 4. Construct SOQL query
    fields_clause = ", ".join(api_fields)
    soql_query = f"SELECT {fields_clause} FROM {object_name}"

    logger.info("Generated SOQL for '%s': %s", report_name, soql_query)
    return soql_query, object_name, api_to_st_map


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
def fetch_sitetracker_data(report_name: str, output_dir: Path | None = None) -> Path:
    """
    Fetch current live Sitetracker records for a report and write to CSV.

    Args:
        report_name: Configured report name (e.g. 'Apollo 10G').
        output_dir: Destination folder. Defaults to the report's input/sitetracker directory.

    Returns:
        Path to the saved CSV file.
    """
    yaml_cfg = YamlConfigLoader.load(report_name)
    if output_dir is None:
        work_dir = yaml_cfg["folders"]["work_dir"]
        st_folder = yaml_cfg["folders"]["sitetracker_dir"]
        output_dir = settings.DATA_DIR / work_dir / st_folder

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Build query
    soql_query, object_name, api_to_st_map = build_soql_for_report(report_name)

    # 2. Execute via simple-salesforce
    sf = get_sf_connection()
    logger.info("Executing SOQL query against Salesforce: %s", soql_query)
    query_result = sf.query_all(soql_query)

    records = query_result.get("records", [])
    if not records:
        raise ValueError(
            f"Salesforce query returned 0 records for object '{object_name}'. "
            f"Verify your object has data and your user has read permissions."
        )

    df = pd.DataFrame(records)

    # 3. Clean Salesforce attributes metadata
    if "attributes" in df.columns:
        df = df.drop(columns=["attributes"])

    # 4. Normalize columns to match Sitetracker field names expected by engine
    # Keep original Id and mapped column names
    rename_dict = {api: st for api, st in api_to_st_map.items() if api in df.columns and st}
    df = df.rename(columns=rename_dict)

    # 5. Clean out existing files in the sitetracker folder (skip hidden files)
    for old_file in output_dir.iterdir():
        if old_file.is_file() and not old_file.name.startswith("."):
            try:
                old_file.unlink()
                logger.info("Removed stale sitetracker file: %s", old_file)
            except Exception as e:
                logger.warning("Could not delete old file %s: %s", old_file, e)

    # 6. Save as CSV
    clean_name = report_name.replace(" ", "_")
    output_file = output_dir / f"{clean_name}_sitetracker_live.csv"
    df.to_csv(output_file, index=False, encoding="utf-8")

    logger.info(
        "Successfully fetched %d records for '%s' -> %s",
        len(df), report_name, output_file
    )
    return output_file
