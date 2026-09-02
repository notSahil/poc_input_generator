"""Discover available fields on a Salesforce object using describe metadata."""

import logging
from salesforce.sf_client import get_sf_connection
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


def map_sf_type(sf_type: str) -> str:
    """Map Salesforce field types to internal Data Types: text, date, number, boolean."""
    type_str = str(sf_type).lower().strip()
    mapping = {
        "string": "text",
        "textarea": "text",
        "picklist": "text",
        "multipicklist": "text",
        "combobox": "text",
        "email": "text",
        "phone": "text",
        "url": "text",
        "id": "text",
        "reference": "text",
        "encryptedstring": "text",
        "date": "date",
        "datetime": "date",
        "time": "text",
        "double": "number",
        "int": "number",
        "long": "number",
        "currency": "number",
        "percent": "number",
        "boolean": "boolean",
    }
    return mapping.get(type_str, "text")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
def discover_object_fields(object_name: str) -> list[dict]:
    """
    Query Salesforce object describe metadata and return clean list of field mappings.

    Returns:
        list of dicts with keys:
        ['Source File Column Name', 'Sitetracker Field Name', 'API Name', 'Data Type', 'Is External ID']
    """
    clean_name = object_name.strip().replace(" ", "_")
    if not clean_name.endswith("__c") and clean_name not in ("Account", "Contact", "Opportunity", "Lead", "Case"):
        clean_name = f"{clean_name}__c"

    sf = get_sf_connection()
    logger.info("Fetching describe metadata for object: %s", clean_name)

    describe = getattr(sf, clean_name).describe()
    raw_fields = describe.get("fields", [])

    discovered = []
    for f in raw_fields:
        is_updateable = f.get("updateable", False)
        is_ext_id = f.get("externalId", False)
        is_name_field = f.get("nameField", False)
        field_name = f.get("name", "")

        # Keep fields that can either be updated or used as identifiers (e.g. Id)
        if is_updateable or is_ext_id or is_name_field or field_name == "Id":
            label = f.get("label", field_name)
            sf_type = f.get("type", "string")

            discovered.append({
                "Source File Column Name": "",
                "Sitetracker Field Name": label,
                "API Name": field_name,
                "Data Type": map_sf_type(sf_type),
                "Is External ID": "Yes" if is_ext_id else "No"
            })

    logger.info("Discovered %d usable fields for object '%s'", len(discovered), clean_name)
    return discovered
