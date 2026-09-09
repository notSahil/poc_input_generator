"""Fetch live Sitetracker data using SOQL queries generated from field mappings."""

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from core.exceptions import MappingError
from core.mapping_loader import MappingLoader
from salesforce.sf_client import get_sf_connection
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def normalize_salesforce_object_name(obj_name: str) -> str:
    """Normalize user-friendly or variant object names to canonical Salesforce API names."""
    s = str(obj_name).strip()
    if s.lower() in ("site", "site__c", "sitetracker__site__c"):
        return "sitetracker__Site__c"
    if s.lower() in ("project", "project__c", "sitetracker__project__c"):
        return "sitetracker__Project__c"
    if " " in s and not s.endswith("__c"):
        return f"{s.replace(' ', '_')}__c"
    return s


def build_soql_for_report(
    report_name: str,
    target_object: str | None = None,
    pk_filter_values: list[str] | None = None,
) -> tuple[str, str, dict[str, str]]:
    """
    Build a SOQL query for the given report based on its field mapping.

    Args:
        report_name: Name of the report.
        target_object: Optional specific object name from the mapping file to query.
        pk_filter_values: Optional list of primary key values to filter via WHERE ... IN (...).

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
    if target_object:
        chosen_obj = str(target_object).strip()
    elif configured_obj:
        chosen_obj = str(configured_obj).strip()
    else:
        # Check if an object has the primary key
        pk_rows = mapping_df[mapping_df["Primary Key?"].astype(str).str.strip().str.upper().isin(["YES", "Y", "TRUE"])]
        if not pk_rows.empty and "Object Name" in pk_rows.columns and pd.notna(pk_rows.iloc[0]["Object Name"]):
            chosen_obj = str(pk_rows.iloc[0]["Object Name"]).strip()
        elif "Object Name" in mapping_df.columns and not mapping_df["Object Name"].dropna().empty:
            chosen_obj = str(mapping_df["Object Name"].dropna().iloc[0]).strip()
        else:
            chosen_obj = "Site"

    # Normalize object name to Salesforce API name
    object_name = normalize_salesforce_object_name(chosen_obj)

    # Filter mapping rows for this object ONLY IF target_object was explicitly specified
    if target_object and "Object Name" in mapping_df.columns:
        filtered_df = mapping_df[mapping_df["Object Name"].astype(str).str.strip().str.lower() == chosen_obj.lower()]
        query_df = filtered_df if not filtered_df.empty else mapping_df
    else:
        query_df = mapping_df

    # 3. Collect unique API fields (supporting relationships for multi-object reports)
    api_fields: list[str] = [sf_id_col] if sf_id_col else ["Id"]
    api_to_st_map: dict[str, str] = {}

    for _, row in query_df.iterrows():
        api_name = str(row.get("API Name", "")).strip()
        st_field = str(row.get("Sitetracker Field Name", "")).strip()
        row_obj = str(row.get("Object Name", "")).strip()

        if not api_name or api_name.lower() == "nan":
            continue

        # Resolve field path: if row_obj is different from chosen_obj,
        # query it through the relationship prefix (e.g. Project__r.WES_PSID__c)
        field_expr = api_name
        norm_row_obj = normalize_salesforce_object_name(row_obj) if row_obj else ""
        norm_chosen_obj = normalize_salesforce_object_name(chosen_obj) if chosen_obj else ""

        if norm_row_obj and norm_chosen_obj and norm_row_obj.lower() != norm_chosen_obj.lower():
            if "." not in api_name:
                rel_prefix = f"{row_obj.replace(' ', '_')}__r"
                field_expr = f"{rel_prefix}.{api_name}"
                # Also include lookup ID field if present (e.g. Project__c)
                lookup_id = f"{row_obj.replace(' ', '_')}__c"
                if lookup_id not in api_fields and lookup_id.lower() != object_name.lower():
                    api_fields.append(lookup_id)

        if field_expr not in api_fields:
            api_fields.append(field_expr)

        if st_field and st_field.lower() != "nan":
            api_to_st_map[field_expr] = st_field
            api_to_st_map[api_name] = st_field

    # 4. Locate Primary Key API field
    pk_api_name: str | None = None
    pk_rows = query_df[query_df["Primary Key?"].astype(str).str.strip().str.upper().isin(["YES", "Y", "TRUE"])]
    if pk_rows.empty and "Primary Key?" in mapping_df.columns:
        pk_rows = mapping_df[mapping_df["Primary Key?"].astype(str).str.strip().str.upper().isin(["YES", "Y", "TRUE"])]

    if not pk_rows.empty:
        candidate_api = str(pk_rows.iloc[0].get("API Name", "")).strip()
        if candidate_api and candidate_api.lower() != "nan":
            pk_api_name = candidate_api

    # 5. Construct SOQL query
    fields_clause = ", ".join(api_fields)
    soql_query = f"SELECT {fields_clause} FROM {object_name}"

    if pk_filter_values and pk_api_name:
        clean_pks: list[str] = []
        seen: set[str] = set()
        for v in pk_filter_values:
            if v is not None:
                s = str(v).strip()
                if s and s.lower() != "nan" and s not in seen:
                    seen.add(s)
                    clean_pks.append(s)

        if clean_pks:
            escaped = [v.replace("'", "\\'") for v in clean_pks]
            in_clause = ", ".join(f"'{v}'" for v in escaped[:200])
            soql_query += f" WHERE {pk_api_name} IN ({in_clause})"
            if len(clean_pks) > 200:
                logger.warning(
                    "PK filter contains %d values; single SOQL clamped to first 200 for URL length safety.",
                    len(clean_pks),
                )
    elif pk_filter_values and not pk_api_name:
        logger.warning(
            "pk_filter_values provided for '%s', but no primary key API field found for object '%s'. Executing unfiltered query.",
            report_name, object_name,
        )

    logger.info("Generated SOQL for '%s' (object: %s): %s", report_name, object_name, soql_query)
    return soql_query, object_name, api_to_st_map


def _chunk_pks(pks: list[str], max_items: int = 200, max_chars: int = 4000) -> list[list[str]]:
    """
    Split primary keys into chunks that are safe from HTTP 431 (Request Header Fields Too Large).
    Ensures that no single chunk exceeds max_items or max_chars when combined into a SOQL WHERE IN clause.
    """
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_chars = 0

    for pk in pks:
        # Approximate URL-encoded length for each item: '%27' + value + '%27%2C+'
        pk_len = len(pk) + 12
        if current_chunk and (len(current_chunk) >= max_items or (current_chars + pk_len) >= max_chars):
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0
        current_chunk.append(pk)
        current_chars += pk_len

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _query_sf(sf, soql: str, api_to_st_map: dict[str, str], report_name: str) -> list[dict]:
    """Execute SOQL query via simple-salesforce with friendly schema error mapping."""
    try:
        res = sf.query_all(soql)
        return res.get("records", [])
    except Exception as e:
        err_text = str(e)
        content = getattr(e, "content", [])
        if isinstance(content, list) and len(content) > 0 and isinstance(content[0], dict):
            err_text = content[0].get("message", err_text)

        # Check if error is due to an unconfigured relationship prefix or lookup field
        if "." in soql or "__r" in soql:
            rel_match = re.search(r"Didn't understand relationship '([^']+)'", err_text)
            col_match = re.search(r"No such column '([^']+)' on entity '([^']+)'", err_text)
            failing_token = None
            if rel_match:
                failing_token = rel_match.group(1)
            elif col_match and (col_match.group(1).endswith("__r") or col_match.group(1).endswith("__c")):
                failing_token = col_match.group(1)

            if failing_token:
                logger.warning(
                    "SOQL query failed on relationship/field '%s' (%s). Retrying with direct fields only...",
                    failing_token, err_text,
                )
                select_match = re.match(r"SELECT\s+(.*?)\s+FROM\s+(\w+)(.*)", soql, re.IGNORECASE | re.DOTALL)
                if select_match:
                    all_fields = [f.strip() for f in select_match.group(1).split(",")]
                    direct_fields = [
                        f for f in all_fields
                        if not f.startswith(f"{failing_token}.") and f != failing_token and ("." not in f if rel_match else True)
                    ]
                    clean_soql = f"SELECT {', '.join(direct_fields)} FROM {select_match.group(2)}{select_match.group(3)}"
                    logger.info("Executing resilient fallback SOQL query: %s", clean_soql)
                    try:
                        res = sf.query_all(clean_soql)
                        return res.get("records", [])
                    except Exception as fallback_err:
                        logger.warning("Fallback SOQL query also failed: %s", fallback_err)

        match = re.search(r"No such column '([^']+)' on entity '([^']+)'", err_text)
        if match:
            missing_col, entity = match.group(1), match.group(2)
            st_col_name = api_to_st_map.get(missing_col, missing_col)
            raise MappingError(
                f"Field '{missing_col}' (mapped to '{st_col_name}') does not exist on Salesforce object '{entity}'.\n\n"
                f"📋 How to fix:\n"
                f"1. Open the Mapping Editor for report '{report_name}'.\n"
                f"2. Check the row for '{st_col_name}'.\n"
                f"3. Verify if '{missing_col}' is the correct API Name in Salesforce, or if it belongs to a different Object."
            ) from None

        raise RuntimeError(f"Salesforce query error: {err_text}") from None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
def fetch_sitetracker_data(
    report_name: str,
    output_dir: Path | None = None,
    target_object: str | None = None,
    source_file: Path | None = None,
    profile: str | None = None,
) -> Path:
    """
    Fetch current live Sitetracker records for a report and write to CSV.
    If source_file is provided, only records matching its primary keys are fetched via SOQL WHERE IN.

    Args:
        report_name: Configured report name (e.g. 'Apollo 10G').
        output_dir: Destination folder. Defaults to the report's input/sitetracker directory.
        target_object: Optional specific object name to query.
        source_file: Optional path to uploaded source spreadsheet to extract primary keys from.
        profile: Optional Salesforce profile name ('sandbox', 'partial', 'prod').

    Returns:
        Path to the saved CSV file.
    """
    yaml_cfg = YamlConfigLoader.load(report_name)
    if output_dir is None:
        work_dir = yaml_cfg["folders"]["work_dir"]
        st_folder = yaml_cfg["folders"]["sitetracker_dir"]
        output_dir = settings.DATA_DIR / work_dir / st_folder

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Extract primary key values from source file if provided
    clean_pks: list[str] = []
    if source_file is not None and Path(source_file).exists():
        src_path = Path(source_file)
        try:
            from core.normalizer import DataNormalizer
            if src_path.suffix.lower() in (".xlsx", ".xls"):
                raw_df = pd.read_excel(src_path, dtype=str)
            else:
                raw_df = pd.read_csv(src_path, dtype=str)
            src_df = DataNormalizer.normalize_columns(raw_df)

            mapping = MappingLoader(settings.MAPPING_FILE, report_name)
            mapping.load()
            src_pk, _ = mapping.primary_keys()

            pk_col = None
            if src_pk in src_df.columns:
                pk_col = src_pk
            else:
                for c in src_df.columns:
                    if str(c).strip().lower() == str(src_pk).strip().lower():
                        pk_col = c
                        break

            if pk_col:
                seen_pk: set[str] = set()
                for val in src_df[pk_col].dropna():
                    s = str(val).strip()
                    if s and s.lower() != "nan" and s not in seen_pk:
                        seen_pk.add(s)
                        clean_pks.append(s)
                logger.info(
                    "Extracted %d unique primary key values from source file '%s' (column: '%s')",
                    len(clean_pks), src_path.name, src_pk,
                )
            else:
                logger.warning(
                    "Primary key column '%s' not found in source file '%s'. Available: %s",
                    src_pk, src_path.name, list(src_df.columns),
                )
        except Exception as e_src:
            logger.warning("Could not extract primary keys from source file '%s': %s", src_path, e_src)

    # 2. Connect to Salesforce
    sf = get_sf_connection(profile=profile)

    # 3. Execute SOQL queries (batching chunks of 1000 if clean_pks > 1000)
    records: list[dict] = []
    object_name = "sitetracker__Site__c"
    api_to_st_map: dict[str, str] = {}

    if clean_pks:
        chunks = _chunk_pks(clean_pks, max_items=200, max_chars=4000)
        total_chunks = len(chunks)
        logger.info(
            "Divided %d primary keys into %d URL-safe SOQL batches (max 200 items / 4,000 chars) to prevent HTTP 431.",
            len(clean_pks), total_chunks,
        )

        def _fetch_chunk(chunk_data: tuple[int, list[str]]) -> list[dict]:
            idx, chunk = chunk_data
            soql_chunk, _, st_map = build_soql_for_report(
                report_name, target_object=target_object, pk_filter_values=chunk
            )
            logger.info(
                "Executing safe SOQL batch %d/%d (%d PKs): %s",
                idx + 1, total_chunks, len(chunk), soql_chunk[:140],
            )
            return _query_sf(sf, soql_chunk, st_map, report_name)

        if total_chunks == 1:
            soql_chunk, object_name, api_to_st_map = build_soql_for_report(
                report_name, target_object=target_object, pk_filter_values=chunks[0]
            )
            records = _query_sf(sf, soql_chunk, api_to_st_map, report_name)
        else:
            _, object_name, api_to_st_map = build_soql_for_report(
                report_name, target_object=target_object, pk_filter_values=chunks[0]
            )
            with ThreadPoolExecutor(max_workers=4) as executor:
                for batch_records in executor.map(_fetch_chunk, enumerate(chunks)):
                    records.extend(batch_records)
    else:
        soql_query, object_name, api_to_st_map = build_soql_for_report(
            report_name, target_object=target_object, pk_filter_values=None
        )
        logger.info("Executing SOQL query against Salesforce (unfiltered): %s", soql_query)
        records = _query_sf(sf, soql_query, api_to_st_map, report_name)

    if not records:
        if clean_pks:
            src_name = Path(source_file).name if source_file else "source file"
            raise ValueError(
                f"Salesforce query returned 0 records for object '{object_name}' matching the {len(clean_pks)} "
                f"primary keys from '{src_name}'. "
                f"Please verify that these records exist in this Salesforce environment."
            )
        raise ValueError(
            f"Salesforce query returned 0 records for object '{object_name}' in this Salesforce Org. "
            f"Please verify that this environment contains data for '{object_name}'."
        )

    # 4. Clean and flatten Salesforce records
    df = pd.json_normalize(records)
    attr_cols = [c for c in df.columns if "attributes" in c]
    if attr_cols:
        df = df.drop(columns=attr_cols)

    # Deduplicate by Id if present
    if "Id" in df.columns:
        df = df.drop_duplicates(subset=["Id"])

    # 5. Normalize columns to match Sitetracker field names expected by engine
    rename_dict = {api: st for api, st in api_to_st_map.items() if api in df.columns and st}
    df = df.rename(columns=rename_dict)

    # 6. Clean out existing files in the sitetracker folder (skip hidden files)
    for old_file in output_dir.iterdir():
        if old_file.is_file() and not old_file.name.startswith("."):
            try:
                old_file.unlink()
                logger.info("Removed stale sitetracker file: %s", old_file)
            except Exception as e:
                logger.warning("Could not delete old file %s: %s", old_file, e)

    # 7. Save as CSV
    clean_name = report_name.replace(" ", "_")
    output_file = output_dir / f"{clean_name}_sitetracker_live.csv"
    df.to_csv(output_file, index=False, encoding="utf-8")

    logger.info(
        "Successfully fetched %d records for '%s' -> %s",
        len(df), report_name, output_file,
    )
    return output_file
