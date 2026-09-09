"""Salesforce Ad-Hoc Metadata and Live Data Fetcher.

Allows dynamic object discovery, field discovery, and parallel SOQL querying
for arbitrary Salesforce objects in manual dataloader operations.
"""

from concurrent.futures import ThreadPoolExecutor
import logging
import re
from typing import Any
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from core.exceptions import SalesforceAPIError, SalesforceAuthError
from salesforce.field_discovery import map_sf_type
from salesforce.sf_client import get_sf_connection

logger = logging.getLogger(__name__)


def chunk_identifiers(
    identifiers: list[str],
    max_batch_size: int = 200,
    max_query_length: int = 4000,
) -> list[list[str]]:
    """
    Split primary key identifiers into URL-safe chunks respecting both item count
    and approximate SOQL WHERE clause character limits to prevent HTTP 431 errors.
    """
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_length = 0

    for item in identifiers:
        val = str(item).strip()
        if not val or val.lower() == "nan":
            continue
        # Account for quotes, comma, space: 'val',
        item_len = len(val) + 4
        if len(current_chunk) >= max_batch_size or (current_length + item_len) > max_query_length:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [val]
            current_length = item_len
        else:
            current_chunk.append(val)
            current_length += item_len

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def fetch_all_objects(profile: str | None = None) -> list[dict[str, Any]]:
    """
    Query Salesforce describeGlobal to list all queryable and updateable objects.

    Returns:
        Sorted list of dicts:
        [{'name': 'sitetracker__Site__c', 'label': 'Site', 'custom': True, 'category': 'Sitetracker'}, ...]
    """
    sf = get_sf_connection(profile=profile)
    logger.info("Discovering all Salesforce objects for profile: %s", profile or "default")

    describe_data = sf.describe()
    raw_sobjects = describe_data.get("sobjects", [])

    discovered: list[dict[str, Any]] = []
    for sobj in raw_sobjects:
        # Filter only objects that can be queried and updated
        if not sobj.get("queryable", False):
            continue
        if not (sobj.get("updateable", False) or sobj.get("createable", False)):
            continue

        name = sobj.get("name", "")
        label = sobj.get("label", name)
        is_custom = sobj.get("custom", False)

        # Filter out internal/system tables that should never be bulk loaded
        name_lower = name.lower()
        if any(name_lower.endswith(sfx) for sfx in (
            "__share", "__history", "__feed", "__tag", "__changeevent",
            "__viewstat", "__votestat", "__dataevent"
        )):
            continue
        if name_lower.startswith("apex"):
            continue

        if name.lower().startswith("sitetracker__"):
            category = "Sitetracker"
        elif is_custom:
            category = "Custom"
        else:
            category = "Standard"

        discovered.append({
            "name": name,
            "label": label,
            "custom": is_custom,
            "category": category,
        })

    # Pinned priority objects (most commonly used in Sitetracker telecom workflows)
    pinned_objects = [
        "sitetracker__Site__c",
        "BT_Project__c",
        "sitetracker__Project__c",
        "sitetracker__Job__c",
        "sitetracker__Work_Order__c",
        "sitetracker__Milestone__c",
        "Account",
        "Contact",
    ]
    pinned_rank = {obj.lower(): i for i, obj in enumerate(pinned_objects)}

    # Sort priority: Pinned core objects first, then Sitetracker, Custom, Standard, then alphabetically by label
    category_order = {"Sitetracker": 0, "Custom": 1, "Standard": 2}
    discovered.sort(key=lambda x: (
        pinned_rank.get(x["name"].lower(), 999),
        category_order.get(x["category"], 3),
        x["label"].lower(),
    ))

    logger.info("Found %d updateable Salesforce objects.", len(discovered))
    return discovered


def fetch_object_fields(object_name: str, profile: str | None = None) -> list[dict[str, Any]]:
    """
    Query metadata describe for a specific Salesforce object.

    Returns:
        list of field metadata dictionaries containing:
        - api_name: str
        - label: str
        - data_type: str ('text', 'date', 'number', 'boolean')
        - is_external_id: bool
        - updateable: bool
        - createable: bool
    """
    sf = get_sf_connection(profile=profile)
    clean_obj = str(object_name).strip()
    logger.info("Fetching field describe for object: %s", clean_obj)

    try:
        describe = getattr(sf, clean_obj).describe()
    except Exception as e:
        logger.error("Failed to describe object '%s': %s", clean_obj, e)
        raise SalesforceAPIError(f"Could not inspect Salesforce object '{clean_obj}': {e}") from e

    raw_fields = describe.get("fields", [])
    fields_info: list[dict[str, Any]] = []

    for f in raw_fields:
        api_name = f.get("name", "")
        label = f.get("label", api_name)
        sf_type = f.get("type", "string")
        is_ext_id = bool(f.get("externalId", False))
        is_updateable = bool(f.get("updateable", False))
        is_createable = bool(f.get("createable", False))
        is_name_field = bool(f.get("nameField", False))

        # Include fields that can be updated, created, or used as lookup keys
        if is_updateable or is_createable or is_ext_id or is_name_field or api_name == "Id":
            fields_info.append({
                "api_name": api_name,
                "label": label,
                "data_type": map_sf_type(sf_type),
                "is_external_id": is_ext_id,
                "updateable": is_updateable,
                "createable": is_createable,
            })

    # Sort fields alphabetically by label
    fields_info.sort(key=lambda x: x["label"].lower())
    return fields_info


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
def _query_batch(sf: Any, soql: str) -> list[dict[str, Any]]:
    """Execute a single SOQL batch with automatic retries."""
    res = sf.query_all(soql)
    return res.get("records", [])


def is_valid_salesforce_id(val: str) -> bool:
    """Check if a string is a syntactically valid 15 or 18 character base-62 Salesforce ID."""
    v = str(val).strip()
    return bool(re.match(r"^[a-zA-Z0-9]{15}([a-zA-Z0-9]{3})?$", v))


def fetch_adhoc_live_data(
    object_name: str,
    fields: list[str],
    pk_field: str,
    pk_values: list[str],
    profile: str | None = None,
) -> pd.DataFrame:
    """
    Fetch current live data from Salesforce for arbitrary objects and primary key values.

    Args:
        object_name: Salesforce API name (e.g. 'sitetracker__Site__c')
        fields: List of Salesforce field API names to query
        pk_field: Salesforce field API name used as the primary key filter (e.g. 'Id', 'Site_ID__c')
        pk_values: Unique primary key values to filter
        profile: Active Salesforce auth profile

    Returns:
        pd.DataFrame containing live Salesforce records with requested fields.
    """
    sf = get_sf_connection(profile=profile)
    clean_obj = str(object_name).strip()

    # Ensure Id and pk_field are always selected
    select_fields_set = {"Id", pk_field}
    for f in fields:
        clean_f = str(f).strip()
        if clean_f and clean_f.lower() != "nan":
            select_fields_set.add(clean_f)

    select_fields_list = sorted(select_fields_set)
    select_clause = ", ".join(select_fields_list)

    # Clean PK values
    clean_pks = [str(v).strip() for v in pk_values if str(v).strip() and str(v).lower() != "nan"]
    if not clean_pks:
        raise ValueError(f"No valid primary key values provided to query object '{clean_obj}'.")

    # If querying by Salesforce system 'Id', filter out syntactically invalid IDs
    # (e.g. 19-character dummy IDs or non-alphanumeric text) to prevent Salesforce
    # SOQL parser from aborting with INVALID_QUERY_FILTER_OPERATOR.
    if pk_field.lower() == "id":
        valid_id_pks = [v for v in clean_pks if is_valid_salesforce_id(v)]
        if len(valid_id_pks) < len(clean_pks):
            invalid_count = len(clean_pks) - len(valid_id_pks)
            logger.warning(
                "Filtered out %d invalid Salesforce ID(s) (must be 15 or 18 alphanumeric characters)",
                invalid_count,
            )
        if not valid_id_pks:
            logger.info("None of the %d PK values were valid Salesforce IDs. Returning empty DataFrame.", len(clean_pks))
            return pd.DataFrame(columns=select_fields_list)
        pks_to_query = valid_id_pks
    else:
        pks_to_query = clean_pks

    chunks = chunk_identifiers(pks_to_query, max_batch_size=200, max_query_length=4000)
    logger.info(
        "Fetching live data for %s: %d PKs split into %d safe SOQL chunks",
        clean_obj, len(pks_to_query), len(chunks),
    )

    all_records: list[dict[str, Any]] = []

    def _execute_chunk(chunk_pks: list[str]) -> list[dict[str, Any]]:
        # Escape single quotes in PK values
        escaped_values = [v.replace("'", "\\'") for v in chunk_pks]
        in_clause = ", ".join(f"'{v}'" for v in escaped_values)
        soql = f"SELECT {select_clause} FROM {clean_obj} WHERE {pk_field} IN ({in_clause})"
        return _query_batch(sf, soql)

    if len(chunks) == 1:
        all_records = _execute_chunk(chunks[0])
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for chunk_records in executor.map(_execute_chunk, chunks):
                all_records.extend(chunk_records)

    if not all_records:
        return pd.DataFrame(columns=select_fields_list)

    # Flatten nested attributes (e.g., Salesforce attributes dict)
    df = pd.json_normalize(all_records)
    attr_cols = [c for c in df.columns if "attributes" in c]
    if attr_cols:
        df = df.drop(columns=attr_cols)

    # Deduplicate by Salesforce Id if present
    if "Id" in df.columns:
        df = df.drop_duplicates(subset=["Id"])

    return df
