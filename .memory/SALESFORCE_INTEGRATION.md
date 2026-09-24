# Salesforce Integration & Sitetracker API Reference

> **SALESFORCE ARCHITECTURE REFERENCE**  
> Complete technical reference for Salesforce OAuth 2.0 authentication, REST Composite collections, Bulk API 2.0 micro-batching, and Sitetracker package conventions.

---

## Quick Redirection
- **Data Pipeline Flow** → [`.memory/PIPELINE_FLOW.md`](PIPELINE_FLOW.md)
- **Output Contracts** → [`.memory/CONTRACTS.md`](CONTRACTS.md)
- **Module Index** → [`.memory/MODULE_INDEX.md`](MODULE_INDEX.md)
- **Salesforce ADRs** → [`.memory/adrs/salesforce_adrs.md`](adrs/salesforce_adrs.md)

---

## 1. Authentication Architecture

The application supports multiple authentication mechanisms managed by `salesforce/auth.py` and `salesforce/sf_client.py`.

### 1.1 Multi-Environment Profiles
The system maintains isolated token caches and configurations across 3 environments:
- `sandbox`: Developer / Full Sandbox (`https://test.salesforce.com`)
- `partial`: Partial Copy Sandbox (`https://test.salesforce.com`)
- `prod`: Production Org (`https://login.salesforce.com`)

The currently active profile is saved in `.sf_profile.json`.

### 1.2 Authentication Methods
1. **OAuth 2.0 Web Server Flow with PKCE (RFC 7636):**
   - Generates cryptographically secure `code_verifier` and `code_challenge`.
   - Starts local loopback callback server on `http://localhost:1717/oauth/callback`.
   - Captures auth code and exchanges it for access and refresh tokens.
2. **Manual Session Token Entry:**
   - Supported for company laptops behind strict firewalls where callback port 1717 is blocked.
   - `sanitize_session_token()` cleans input by stripping whitespace, quotes, `MY_TOKEN:` prefixes, and `###` delimiters.

### 1.3 Automatic Token Refresh & Heartbeat
- **Time-Based Check:** If the access token is older than 7,000 seconds (~1.94 hours), it is flagged for refresh.
- **Live Heartbeat Ping:** Dynamically pings `GET {instance_url}/services/oauth2/userinfo` (cached with 30s TTL, 2.5s timeout).
- **Auto-Refresh Trigger:** On 401 Unauthorized or expiration, `refresh_access_token()` executes `POST /services/oauth2/token` with `grant_type=refresh_token`. The new token is atomically saved to `.sf_auth_<profile>.json`.

---

## 2. Ingestion Engines & Upload Safeguards

### 2.1 Lightning REST Composite SObject Collections (`composite_uploader.py`)
* **Endpoint:** `PATCH /services/data/vXX.X/composite/sobjects`
* **Performance:** High speed (~1.5–2.5s per batch; ~15–20 seconds for 500 records).
* **Batch Size:** Default 15 records (tunable from 5 to 50).
* **🚨 CRITICAL SAFEGUARD — REST Key-Omission:**
  - In Salesforce Composite API, passing `"Field__c": null` in JSON explicitly **clears/wipes** that field in Salesforce!
  - To prevent accidental data loss when uploading records with sparse changes, `composite_uploader.py` **omits unmapped or unchanged keys entirely from the payload**.
  - A key is only sent if it has an actual new value, an explicit `#N/A` wipe command, or is a rollback execution.

### 2.2 Bulk API 2.0 (`bulk_uploader.py`)
* **Use Case:** Very large datasets (2,000+ records) or scheduled jobs.
* **🚨 CRITICAL SAFEGUARD — Apex Trigger Micro-Batching (25 records):**
  - Sitetracker managed package triggers (`BTProjectTrigger`, `sitetracker.StProjectTrigger`) execute child task and milestone cascades per record.
  - Submitting 200+ records in a single batch causes Salesforce to throw `System.LimitException: sitetracker:Too many DML statements: 151:--`.
  - Micro-batching into 25-record chunks isolates transaction contexts, keeping Apex DMLs safely below 150.
* **ISO Date Formatting:** Converts UK dates (`DD/MM/YYYY`) to ISO `YYYY-MM-DD` (`xsd:date`).
* **Explicit `#N/A` Wipes:** Preserves the `#N/A` string so Bulk API 2.0 clears the field.
* **In-Loop Token Re-Hydration:** If a long upload takes 10+ minutes and tokens rotate, the uploader catches 401s, re-reads tokens, and retries the chunk up to 3 times with exponential backoff.

---

## 3. Sitetracker Managed Package Conventions

1. **Namespace Prefix:**
   - Sitetracker custom objects and fields use the `sitetracker__` namespace.
   - Example: Site records are stored in `sitetracker__Site__c`, NOT standard Salesforce `Site`.
2. **Salesforce Record IDs:**
   - 18-character case-insensitive unique IDs.
   - Any ID passed to Salesforce MUST match regex: `^[0-9A-Za-z]{15}([0-9A-Za-z]{3})?$`.
   - In UI and CSV outputs, record IDs are consolidated under a single clean column: `Record_Id` (or `Id`).
3. **Primary Match Keys:**
   - Typically `Project Reference` (`Project_Reference__c`), `Site ID` (`Site_ID__c`), or `Vendor Key`.
   - Resolved dynamically via `Mapping_file.xlsx` or Manual Dataloader Screen 2.

---

## 4. Known Gotchas & Anti-Patterns to Avoid

| Anti-Pattern | Why It Breaks | Correct Pattern |
|---|---|---|
| Sending `"Field__c": null` in REST Composite | Wipes live Salesforce data for untouched fields | Omit the key from the dictionary entirely |
| Submitting 100+ records in Bulk API 2.0 | Crashes with Apex Governor limit: `Too many DML statements: 151` | Micro-batch in 15–25 record chunks |
| Passing UK dates `DD/MM/YYYY` to Bulk API | Fails with `INVALID_FIELD: Failed to deserialize field` | Convert to ISO `YYYY-MM-DD` at upload time |
| Querying standard `Site` instead of `sitetracker__Site__c` | Throws `INVALID_TYPE: sObject type 'Site' is not supported` | Always resolve Sitetracker managed package name |
| Storing raw tokens in code or Git | Security violation | Keep tokens strictly in gitignored `.sf_auth_*.json` |
