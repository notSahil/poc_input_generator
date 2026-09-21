"""Live Post-Update Salesforce Data Fetcher.

Retrieves current live records from Salesforce by their Salesforce IDs
using URL-safe chunked SOQL queries to verify update persistence.
"""

from concurrent.futures import ThreadPoolExecutor
import logging
import pandas as pd

from salesforce.adhoc_fetcher import _query_batch, chunk_identifiers, is_valid_salesforce_id
from salesforce.data_fetcher import normalize_salesforce_object_name
from salesforce.sf_client import get_sf_connection

logger = logging.getLogger(__name__)


def fetch_live_records_by_ids(
    object_name: str,
    record_ids: list[str],
    fields: list[str],
    profile: str | None = None,
) -> pd.DataFrame:
    """Fetch current live data from Salesforce for the given record IDs.

    Args:
        object_name: Salesforce object API name (e.g. 'sitetracker__Site__c').
        record_ids: List of Salesforce 15 or 18 character IDs.
        fields: List of field API names to query.
        profile: Optional Salesforce profile ('sandbox', 'prod').

    Returns:
        pd.DataFrame containing live Salesforce data with 'Id' and the requested fields.
    """
    clean_obj = normalize_salesforce_object_name(object_name)
    if not clean_obj.endswith("__c") and clean_obj not in (
        "Account", "Contact", "Opportunity", "Lead", "Case"
    ):
        clean_obj = f"{clean_obj}__c"

    # Filter valid IDs only
    valid_ids = [str(rid).strip() for rid in record_ids if is_valid_salesforce_id(str(rid).strip())]
    if not valid_ids:
        logger.warning("No valid Salesforce IDs provided to fetch live post-update data.")
        return pd.DataFrame(columns=["Id"] + fields)

    # Unique fields ensuring Id is included
    select_fields = sorted(list({"Id"} | {f.strip() for f in fields if f and f.strip().lower() != "id"}))
    select_clause = ", ".join(select_fields)

    # Chunk IDs to prevent URL length overflow
    chunks = chunk_identifiers(valid_ids, max_batch_size=200, max_query_length=4000)
    logger.info(
        "Fetching live post-update records for %s: %d IDs in %d chunk(s)",
        clean_obj, len(valid_ids), len(chunks),
    )

    sf = get_sf_connection(profile=profile)
    all_records: list[dict] = []

    def _fetch_chunk(chunk_ids: list[str]) -> list[dict]:
        in_clause = ", ".join(f"'{cid}'" for cid in chunk_ids)
        soql = f"SELECT {select_clause} FROM {clean_obj} WHERE Id IN ({in_clause})"
        return _query_batch(sf, soql)

    if len(chunks) == 1:
        all_records = _fetch_chunk(chunks[0])
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for chunk_res in executor.map(_fetch_chunk, chunks):
                all_records.extend(chunk_res)

    if not all_records:
        return pd.DataFrame(columns=select_fields)

    df = pd.json_normalize(all_records)
    # Drop nested Salesforce attributes
    attr_cols = [c for c in df.columns if "attributes" in c]
    if attr_cols:
        df = df.drop(columns=attr_cols)

    if "Id" in df.columns:
        df = df.drop_duplicates(subset=["Id"])

    return df
