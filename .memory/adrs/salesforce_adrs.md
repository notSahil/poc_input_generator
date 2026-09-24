# Salesforce Integration Architecture Decision Records (ADRs)

> Historical context explaining WHY Salesforce OAuth, REST Composite micro-batching, Bulk API 2.0 sanitization, and governor limit protections were built this way.

---

### ADR 2: Salesforce Authentication (`ui/data_export.py`)
- **Decision:** We allow manual token pasting in the UI alongside standard OAuth.
- **Reason:** The user operates on a restricted company laptop/network where automated OAuth flows may be blocked by firewalls.

---

### ADR 4: Salesforce Integration Bridge (`salesforce/sf_client.py`)
- **Decision:** Bridge `simple-salesforce` to use our custom `.sf_auth.json` OAuth tokens rather than its built-in login prompt.
- **Reason:** Preserves existing multi-tab OAuth & manual token auth workflows while unlocking Bulk API 2.0 and robust SOQL querying without rewriting the auth layer.

---

### ADR 5: SOQL Auto-Fetch Header Normalization (`salesforce/data_fetcher.py`)
- **Decision:** When fetching live records via SOQL, auto-rename Salesforce API fields to the human-readable `Sitetracker Field Name` headers defined in `Mapping_file.xlsx` while keeping `Id`.
- **Reason:** Preserves strict contract and zero-modification guarantee for `core/engine.py`, which expects human-readable headers from original Sitetracker CSV exports.

---

### ADR 6: Bulk API 2.0 Payload Sanitization & Safety Gate (`salesforce/bulk_uploader.py`)
- **Decision:** Clean the delta CSV payload before sending to Bulk API 2.0 by dropping human-readable source column headers (e.g. 'Project Ref') and keeping only valid Salesforce API names + 'Id'. Require explicit 'CONFIRM' input from user in UI.
- **Reason:** Prevents Salesforce Bulk API 2.0 schema rejection errors and protects client data from accidental writes.

---

### ADR 7: Metadata Field Discovery & Auto-Type Normalization (`salesforce/field_discovery.py`)
- **Decision:** Query object metadata via `describe()` and map rich Salesforce types (`currency`, `double`, `percent`, `datetime`, `textarea`, etc.) into 4 standardized internal types (`text`, `number`, `date`, `boolean`). Filter for updateable and identifier fields only.
- **Reason:** Eliminates manual typos when configuring new dataloaders and guarantees schema compatibility with normalization rules.

---

### ADR 8: Automated Session Maintenance & Network Resilience (`salesforce/sf_client.py` & `tenacity`)
- **Decision:** Automatically refresh expired access tokens using the refresh token flow before initializing client connections. Wrap critical network queries and Bulk uploads with tenacity exponential backoff retries.
- **Reason:** Guarantees production reliability for scheduled or long-running operations without requiring frequent manual re-authentications.

---

### ADR 11: Multi-Environment Profile Architecture & Workbench Quick Connect (`salesforce/auth.py`, `ui/data_export.py`, `ui/data_load.py`)
- **Decision:** Support isolated environment profiles (`sandbox` vs `prod`) storing distinct token caches (`.sf_auth_sandbox.json` vs `.sf_auth_prod.json`) and tracked in `.sf_profile.json`. Provide a guided Workbench session connection UI with automated token sanitization (stripping `MY_TOKEN:` and `###` artifacts) and environment badges in Data Load and Export pages.
- **Reason:** Allows developer/sandbox testing against real Sitetracker custom schemas without risking production data or overwriting corporate production credentials, providing a frictionless 1-click switch between environments.

---

### ADR 12: Sitetracker Managed Package Object Resolution (`salesforce/data_fetcher.py`, `salesforce/bulk_uploader.py`, `config/reports/master_site_listing.yml`)
- **Decision:** Automatically map generic object names like `Site` to the Sitetracker managed package custom object `sitetracker__Site__c` rather than standard Salesforce `Site` (which is for Experience Cloud / Sites).
- **Reason:** Sitetracker stores site tracking records under `sitetracker__Site__c`. Querying or updating standard `Site` causes Salesforce API to throw `INVALID_FIELD` or `INVALID_TYPE`.

---

### ADR 13: Bulk API 2.0 Date ISO Serialization (`salesforce/bulk_uploader.py`)
- **Decision:** Automatically convert UK date formatted values (`DD/MM/YYYY`) into standard ISO format (`YYYY-MM-DD`) during payload cleaning before submitting Bulk API 2.0 ingest jobs.
- **Reason:** Salesforce Bulk API 2.0 uses `xsd:date` schema deserialization, which strictly rejects `DD/MM/YYYY` formats with `INVALID_FIELD: Failed to deserialize field`. Automatic ISO formatting maintains human UK format in CSVs/UI while ensuring 100% Salesforce API compliance.

---

### ADR 14: Salesforce Connected App OAuth 2.0 Integration with Auto-Refresh (`salesforce/auth.py`, `ui/data_export.py`, `config/settings.py`)
- **Decision:** Implement full OAuth 2.0 Web Server Flow via Connected App (Consumer Key & Secret) supporting 1-click browser authorization, background local callback interception on port 1717, manual authorization-code fallback for corporate proxy environments, and automatic token refresh (`refresh_token`) to prevent session timeouts.
- **Reason:** Eliminates manual 1-hour session token expiration and Workbench copy-pasting, providing an enterprise-standard, permanent SSO login experience.

---

### ADR 18: Dynamic Real-Time Salesforce Session Verification & Unified Multi-Object SOQL Fetch (`salesforce/auth.py`, `app.py`, `ui/data_load.py`)
- **Decision:** Implement dynamic real-time Salesforce session verification (`check_connection_status`) pinging `/services/oauth2/userinfo` with 30s TTL in-memory caching and a 2.5s network timeout. Discontinue legacy `.sf_auth.json` file writes/syncs to prevent stale ghost tokens. Update UI active environment indicators across `app.py` and `ui/data_load.py` to display `● Connected` only when an active, live verified session exists, and `○ Disconnected` / `● Offline` otherwise. In Step 1 of Data Load, streamline live data retrieval into a unified 1-click SOQL fetch querying all mapped fields across objects into the Sitetracker baseline CSV, while preserving object badges and filter buttons in Step 2 for inspection.
- **Reason:** Statically checking file existence or arithmetic timestamps caused false-positive connected statuses when tokens were invalidated, offline, or expired. Forcing users to select individual objects for SOQL fetching fragmented multi-object reports; a single 1-click fetch retrieves all mapped fields needed to compute deltas against source files while maintaining clear object reference badges.

---

### ADR 20: Apex Trigger DML Governor Limit, Micro-Batching & Resilient Rollback Architecture (`salesforce/bulk_uploader.py`, `ui/data_load.py`, `core/mapping_loader.py`)
- **Decision:** Micro-batch all Bulk API 2.0 ingest and rollback operations using `batch_size=25` (configurable via UI slider to 10, 25, 50, 100) via `simple-salesforce` chunking. Aggregate metrics and job IDs across all batch chunks. Shield multi-object loops with per-object try/except blocks and parse Salesforce error responses with `on_bad_lines='skip', engine='python'` to prevent unquoted error commas from crashing tokenization. Render full failure diagnostics tables on rollback failures. Make `MappingLoader.load()` accept both underscore and space variants (`Apollo 10G` and `Apollo_10G`) interchangeably.
- **Reason:** Sitetracker managed package triggers (`BTProjectTrigger`, `sitetracker.StProjectTrigger`) execute child task/milestone cascades per record. Submitting 200+ records in a single batch triggers `System.LimitException: sitetracker:Too many DML statements: 151:--`. Micro-batching into 25-record chunks isolates transaction contexts, keeping Apex DMLs safely below the 150 limit (~25–50 DMLs). Resilient parsing and exception shielding ensure neither ingest nor emergency rollback crash when encountering governor limits or multiline error messages.

---

### ADR 21: Lightning REST Composite Collections Engine, Background Worker & Disconnect Immunity (`salesforce/composite_uploader.py`, `salesforce/job_manager.py`, `ui/data_load.py`)
- **Decision:** Deliver a high-speed synchronous ingest engine using Salesforce REST Composite SObject Collections (`PATCH /services/data/vXX.X/composite/sobjects`), executing batches in ~1.5–2.5s per 50 records without Bulk API 2.0 queue provisioning latency (~15–20 seconds total for 350–500 records). Decouple ingest and rollback into a detached server-side background thread (`salesforce/job_manager.py`) persisting real-time progress to `ingest_progress.json`. Render an animated progress bar (`st.progress`), batch counter, and live metrics in Step 4.
- **Reason:** Bulk API 2.0 is designed for 100,000+ records and carries a fixed 15–25s cloud queue overhead per job, leading to 8–10 minutes of queue waiting when micro-batching 531 records into 22 jobs. Furthermore, mobile browsers (Safari/Chrome on iOS/Android) aggressively freeze background tabs and drop WebSockets when users switch apps or lock their screens, interrupting synchronous Streamlit executions. REST Composite Collections executes 30x faster (15s total), and server-side background threads guarantee uploads complete uninterrupted even if the user closes their browser or switches apps.

---

### ADR 22: In-Flight Chunk Stage Reporting, 15-Record Micro-Batches & Resilient Profile Credential Auto-Refresh (`salesforce/composite_uploader.py`, `salesforce/auth.py`, `salesforce/job_manager.py`, `ui/data_load.py`)
- **Decision:** Emit dual `in_flight` and `completed_chunk` lifecycle callbacks reporting record ranges (e.g. `Records 1 to 15`) and tune default Apex batch size from 50 to 15 (with options 5, 10, 15, 25, 50). Add an active in-flight status banner and a manual `🔄 Refresh Status` button to the Live Ingest Card. Fix `refresh_access_token` in `salesforce/auth.py` to check `.sf_creds_{profile}.json` before `.env`, enabling seamless background token auto-refresh for UI-authenticated sessions.
- **Reason:** Sitetracker validation rules (`Actual_Date_Cant_Updated_When_Approved`) and trigger cascades take ~2–3s per record to evaluate in Salesforce. A 50-record batch took ~115s inside Salesforce, causing the UI to look frozen for 2 minutes before the first progress increment. Reducing default batch size to 15 ensures progress bar increments smoothly every ~30s, and in-flight banners assure users Salesforce is actively calculating. Loading client secrets from profile credentials prevents multi-minute background jobs from crashing on OAuth session expiration.

---

### ADR 27: REST Composite Key-Omission & Zero-Data-Loss Safeguard (`salesforce/composite_uploader.py`)
- **Decision:** In the REST Composite payload builder (`prepared_records` loop), omit dictionary keys entirely when the value is `None` or empty string — unless the value is an explicit `#N/A` wipe or the operation is a rollback (`is_rollback=True`). Add debug logging of omitted field counts per batch.
- **Reason:** Salesforce REST Composite API JSON semantics differ critically from Bulk API 2.0 CSV: sending `"Field__c": null` in JSON instructs Salesforce to **wipe/clear** that field, whereas in Bulk API CSV an empty cell is safely ignored. When `pd.DataFrame` aligns heterogeneous update dicts (rows with different changed fields) into a uniform CSV, missing columns become empty cells, which `clean_payload_for_salesforce()` converts to `None`. Without key omission, this sends `null` for every unchanged field, wiping live Sitetracker data. Omitting keys guarantees Salesforce leaves untouched fields at their existing values.

---

### ADR 30: Bulk API 2.0 Failure CSV Pre-Sanitization & 100% Record Audit Integrity (`salesforce/csv_sanitizer.py`, `salesforce/bulk_uploader.py`, `salesforce/job_manager.py`)
- **Decision:** Introduce a pure-function pre-sanitizer module `salesforce/csv_sanitizer.py` with `sanitize_failure_csv(raw_csv)` and `is_valid_salesforce_id(val)`. Inject pre-sanitization before `pd.read_csv()` in both `bulk_uploader.py` and `job_manager.py`, and switch parser error handling to `on_bad_lines="warn"`. Broaden Salesforce ID validation from custom-only (`^a...`) to universal 15/18-character IDs (`^[0-9A-Za-z]{15}([0-9A-Za-z]{3})?$`) plus test fixtures, and consolidate all phantom-row filtering onto this shared validator.
- **Reason:** Salesforce Bulk API 2.0 returns malformed CSV responses containing unescaped internal double quotes inside Apex validation formulas (e.g. `Validation Formula "Rule_Name" Invalid`) and multiline PL/SQL stack traces without RFC 4180 quote wrapping. Previously, `pd.read_csv(..., on_bad_lines="skip")` silently dropped 30+ failed records per upload, causing severe discrepancies between Salesforce cloud failure counts and downloaded failure CSV audit trails. Pre-sanitizing repairs internal quotes, stitches multiline traces with ` | ` separators, and preserves trailing columns, guaranteeing 100% record accountability and zero silent drops.

---

### ADR 34: Bulk API 2.0 In-Loop Token Re-Hydration & Chunk Resiliency (`salesforce/bulk_uploader.py`, `ui/live_monitor.py`)
- **Decision:**
  1. Wrap Bulk API 2.0 per-chunk execution (`bulk_type.update/upsert/insert`) in a 3-attempt retry loop with exponential backoff (1s, 2s).
  2. In the retry exception handler, invoke `get_sf_connection(profile=profile)` and re-bind `bulk_type = getattr(sf.bulk2, clean_obj)`. This seamlessly re-hydrates the in-memory Salesforce session from disk (where background token rotation stores new access tokens) or triggers a fresh OAuth token exchange before retrying the chunk.
  3. If a chunk permanently fails after all 3 attempts, mark its records in `failures_list` with `CHUNK_SUBMISSION_ERROR: {last_chunk_err}`, assign a tracking ID `FAILED_CHUNK_{chunk_idx}`, and safely skip querying Salesforce `get_failed_records()` for fake chunk IDs while persisting all submission errors to `bulk_upload_failures.csv`.
  4. Clarify the UI completion banner in `ui/live_monitor.py` to state `⚠️ **{op_label} Completed with Partial Failures.**` rather than falsely attributing all errors to Salesforce validation rules.
- **Reason:** During large uploads (such as 2,000 records across 134 batches of 15), execution takes 10+ minutes. If Salesforce rotates or revokes an OAuth token or closes a long-held TCP socket, subsequent batches previously failed in a cascade of 401 Unauthorized errors within seconds. Re-hydrating the connection and re-binding `sf.bulk2` inside the chunk loop guarantees that long-running Bulk API 2.0 operations are 100% resilient to token rotation, socket drops, and transient gateway hiccups.
