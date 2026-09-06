# File Structure Map & Architecture Decisions

This is a living document. **AI AGENTS:** You must update this file whenever you add, remove, or modify the purpose of a file in the codebase.

## 1. Directory Map

### `/core` (Backend Logic & Data Processing)
- `engine.py`: The master execution script. Orchestrates loading data, validating, normalizing, and writing the 5 standard output files.
- `validator.py`: Handles checking for missing or duplicate primary keys.
- `normalizer.py`: Data cleaning and transformations.
- `mapping_loader.py`: Reads the `Mapping_file.xlsx` to determine which columns to map.
- `config_loader.py`: Loads the YAML configurations.
- `models.py`: Data classes or Pydantic models for structured data holding.
- `exceptions.py`: Custom error handling.

### `/ui` (Streamlit Frontend)
- `components.py`: Shared UI components including Dataloader.io 4-stage pipeline stepper, step navigation buttons, headers, and download confirmation popovers.
- `styles.py`: Salesforce Lightning Design System (SLDS) design tokens, CSS styling, executive KPI metric cards, and status pill badges.
- `data_load.py`: Guided 4-step Dataloader.io pipeline (Source & Object ➔ Visual Field Mapping Canvas ➔ Delta & Validation Engine ➔ Review, Downloads & Bulk API Ingest).
- `run_history.py`: UI page for browsing past engine runs, viewing execution metrics, re-downloading output files, and inspecting archived source inputs.
- `mapping_editor.py`: Interactive UI allowing the user to view and edit mapping rules directly in the browser with history/rollback capabilities.
- `data_export.py`: Handles environment profile switching (Sandbox vs Production), Workbench session token connection, displaying authenticated user profile details, and logout.

### `/salesforce` (Integrations)
- `auth.py`: Handles OAuth, multi-environment profile token caching (`.sf_auth_sandbox.json`, `.sf_auth_prod.json`), Workbench session token sanitization, and automatic token refreshing.
- `client.py`: API wrapper for making legacy REST requests to SFDC with profile awareness.
- `sf_client.py`: Bridge module providing a `simple-salesforce` client (`Salesforce`) backed by active environment profile OAuth/session tokens with automatic expiration refresh.
- `data_fetcher.py`: Builds dynamic SOQL queries from `Mapping_file.xlsx` and fetches live Sitetracker records via `simple-salesforce`.
- `bulk_uploader.py`: Uploads `final_input_file.csv` to Salesforce via Bulk API 2.0 with payload column sanitization and record-level error logging.
- `field_discovery.py`: Discovers Salesforce object metadata via `describe()`, filters updateable fields, and maps types to text/date/number/boolean.
- `metadata.py` & `userinfo.py`: Utilities for fetching SFDC objects.

### `/config` (Settings)
- `settings.py`: Global environment variables and paths.
- `logging_config.py`: Standardized logging setup.
- `/reports`: Contains YAML files (`apollo_10g.yml`, `master_site_listing.yml`) defining the specific Primary Keys and settings for different report types.

### `/scripts` (Utilities)
- `auto_deploy.sh`: Bash script run via cron on the Oracle server to automatically pull git updates.
- `deploy_to_oracle.sh`: Bash script setting up VM, swap, iptables, uv, code-server, and systemd services on Oracle Cloud.
- `scaffold_report.py`: CLI generator script for scaffolding new report configs.
- `setup_ssl.sh`: Automated script for configuring Nginx reverse proxy with WebSocket support and Let's Encrypt HTTPS via DuckDNS or custom domain.

### Root Files
- `cli.py`: Command-line interface for scaffolding or running reports without the UI.
- `quick_test.py`: End-to-end integration test script.
- `app.py`: Symlink or wrapper to `ui/app.py` for running Streamlit from root.

### `/.agents/skills` (AI Agent Custom Skills)
- `senior-architect-review/`: Multi-pass architectural review & iterative plan refinement with anti-duplication audits.
- `new-feature-add/`: Senior developer feature workflow with isolation, ADR logging, and zero-regression tests.
- `python-pro/`: Python 3.12+ type annotations (PEP 604), pathlib, and PEP 8 standards.
- `data-engineer/`: Pandas vectorization, memory optimization, and defensive data processing.
- `unit-testing-test-generate/`: Pytest AAA pattern, fixtures, and external mock standards.
- `uv-package-manager/`: Fast package and environment management via `uv`.

---

## 2. Architecture Decision Records (ADRs)
*Historical context explaining WHY things are built this way.*

1. **File Archiving Strategy (`core/engine.py`)**: 
   - *Decision:* We use `shutil.copy2` instead of `shutil.move` for processing inputs.
   - *Reason:* The user frequently tests the system. If we move/delete the source files, testing is annoying. Copying retains the raw inputs for repeat runs.
2. **Salesforce Authentication (`ui/data_export.py`)**: 
   - *Decision:* We allow manual token pasting in the UI alongside standard OAuth.
   - *Reason:* The user operates on a restricted company laptop/network where automated OAuth flows may be blocked by firewalls.
3. **Environment Setup**:
   - *Decision:* No local installations on the company laptop. Everything runs remotely via `code-server` in the browser.
   - *Reason:* Bypasses company laptop restrictions. Streamlit hot-reloading is used to instantly preview code saved in the browser IDE.
4. **Salesforce Integration Bridge (`salesforce/sf_client.py`)**:
   - *Decision:* Bridge `simple-salesforce` to use our custom `.sf_auth.json` OAuth tokens rather than its built-in login prompt.
   - *Reason:* Preserves existing multi-tab OAuth & manual token auth workflows while unlocking Bulk API 2.0 and robust SOQL querying without rewriting the auth layer.
5. **SOQL Auto-Fetch Header Normalization (`salesforce/data_fetcher.py`)**:
   - *Decision:* When fetching live records via SOQL, auto-rename Salesforce API fields to the human-readable `Sitetracker Field Name` headers defined in `Mapping_file.xlsx` while keeping `Id`.
   - *Reason:* Preserves strict contract and zero-modification guarantee for `core/engine.py`, which expects human-readable headers from original Sitetracker CSV exports.
6. **Bulk API 2.0 Payload Sanitization & Safety Gate (`salesforce/bulk_uploader.py`)**:
   - *Decision:* Clean the delta CSV payload before sending to Bulk API 2.0 by dropping human-readable source column headers (e.g. 'Project Ref') and keeping only valid Salesforce API names + 'Id'. Require explicit 'CONFIRM' input from user in UI.
   - *Reason:* Prevents Salesforce Bulk API 2.0 schema rejection errors and protects client data from accidental writes.
7. **Metadata Field Discovery & Auto-Type Normalization (`salesforce/field_discovery.py`)**:
   - *Decision:* Query object metadata via `describe()` and map rich Salesforce types (`currency`, `double`, `percent`, `datetime`, `textarea`, etc.) into 4 standardized internal types (`text`, `number`, `date`, `boolean`). Filter for updateable and identifier fields only.
   - *Reason:* Eliminates manual typos when configuring new dataloaders and guarantees schema compatibility with normalization rules.
8. **Automated Session Maintenance & Network Resilience (`salesforce/sf_client.py` & `tenacity`)**:
   - *Decision:* Automatically refresh expired access tokens using the refresh token flow before initializing client connections. Wrap critical network queries and Bulk uploads with tenacity exponential backoff retries.
   - *Reason:* Guarantees production reliability for scheduled or long-running operations without requiring frequent manual re-authentications.
9. **Enterprise Dataloader.io Validation & Reporting (`core/engine.py` & `core/normalizer.py`)**:
   - *Decision:* Enforce row-level atomicity matching Salesforce Data Loader — any invalid date or data type mismatch rejects the entire row rather than partially pushing other fields. Generate 8 structured output files (`final_input_file.csv`, `success_records.csv`, `error_records.csv`, `skipped_records.csv`, `validation_report.csv`, `field_level_changes.csv`, `invalid_primary_key.csv`, `duplicate_primary_keys.csv`) with strict UK `DD/MM/YYYY` date formatting.
   - *Reason:* Prevents data corruption and partial record updates in Sitetracker while giving users granular error diagnostics identical to Dataloader.io.
10. **1-Click Rollback Payload & Run History Browser (`core/engine.py`, `ui/run_history.py`, `ui/data_load.py`)**:
   - *Decision:* Generate a mirror `rollback_file.csv` containing pre-change Sitetracker values whenever deltas are computed, with an emergency revert gate in Section 6. Provide a dedicated Run History & Audit browser scanning existing `runs/` and `archive/` folders with 1-click downloads.
   - *Reason:* Gives the team an absolute safety net to undo accidental data writes and provides self-service auditability without needing command-line or IDE access.
11. **Multi-Environment Profile Architecture & Workbench Quick Connect (`salesforce/auth.py`, `ui/data_export.py`, `ui/data_load.py`)**:
   - *Decision:* Support isolated environment profiles (`sandbox` vs `prod`) storing distinct token caches (`.sf_auth_sandbox.json` vs `.sf_auth_prod.json`) and tracked in `.sf_profile.json`. Provide a guided Workbench session connection UI with automated token sanitization (stripping `MY_TOKEN:` and `###` artifacts) and environment badges in Data Load and Export pages.
   - *Reason:* Allows developer/sandbox testing against real Sitetracker custom schemas without risking production data or overwriting corporate production credentials, providing a frictionless 1-click switch between environments.
12. **Sitetracker Managed Package Object Resolution (`salesforce/data_fetcher.py`, `salesforce/bulk_uploader.py`, `config/reports/master_site_listing.yml`)**:
   - *Decision:* Automatically map generic object names like `Site` to the Sitetracker managed package custom object `sitetracker__Site__c` rather than standard Salesforce `Site` (which is for Experience Cloud / Sites).
   - *Reason:* Sitetracker stores site tracking records under `sitetracker__Site__c`. Querying or updating standard `Site` causes Salesforce API to throw `INVALID_FIELD` or `INVALID_TYPE`.
13. **Bulk API 2.0 Date ISO Serialization (`salesforce/bulk_uploader.py`)**:
   - *Decision:* Automatically convert UK date formatted values (`DD/MM/YYYY`) into standard ISO format (`YYYY-MM-DD`) during payload cleaning before submitting Bulk API 2.0 ingest jobs.
   - *Reason:* Salesforce Bulk API 2.0 uses `xsd:date` schema deserialization, which strictly rejects `DD/MM/YYYY` formats with `INVALID_FIELD: Failed to deserialize field`. Automatic ISO formatting maintains human UK format in CSVs/UI while ensuring 100% Salesforce API compliance.
14. **Salesforce Connected App OAuth 2.0 Integration with Auto-Refresh (`salesforce/auth.py`, `ui/data_export.py`, `config/settings.py`)**:
   - *Decision:* Implement full OAuth 2.0 Web Server Flow via Connected App (Consumer Key & Secret) supporting 1-click browser authorization, background local callback interception on port 1717, manual authorization-code fallback for corporate proxy environments, and automatic token refresh (`refresh_token`) to prevent session timeouts.
   - *Reason:* Eliminates manual 1-hour session token expiration and Workbench copy-pasting, providing an enterprise-standard, permanent SSO login experience.
15. **Dataloader-Style Null Wipe Safeguard & '#N/A' Bulk API 2.0 Ingest (`core/engine.py`, `salesforce/bulk_uploader.py`, `ui/data_load.py`, `cli.py`)**:
   - *Decision:* Blank cells in the source input file are ignored by default (`insert_nulls=False`), preserving existing Sitetracker data. Users can explicitly enable the 'Overwrite with Blanks (Insert Nulls)' toggle in the UI or CLI (`--insert-nulls`), which serializes empty fields as `#N/A`. The Bulk API 2.0 uploader preserves `#N/A` strings and avoids pandas default NA conversion (`keep_default_na=False`).
   - *Reason:* Salesforce Bulk API 2.0 ignores empty strings in CSV uploads; only the literal string `#N/A` instructs Salesforce to clear a field. Defaulting to ignore-blanks prevents accidental data wipes if users upload partial spreadsheets, while `#N/A` enables explicit field clearance matching Dataloader.io behavior.
16. **Dataloader.io Enterprise UI Overhaul & Guided Pipeline Stepper (`ui/data_load.py`, `ui/styles.py`, `ui/components.py`, `app.py`)**:
   - *Decision:* Restyle the frontend using Salesforce Lightning Design System (SLDS) CSS tokens and refactor `ui/data_load.py` from a monolithic vertical scrolling page into a guided 4-step pipeline wizard (`1. Source & Object` ➔ `2. Field Mapping` ➔ `3. Delta Engine` ➔ `4. Review & Ingest`) with visual 3-column connector cards, executive KPI metric tiles, and `streamlit-antd-components` stepper integration.
   - *Reason:* Eliminates vertical scroll fatigue, establishes a clear mental model of data pipeline progression, gives users immediate visual confidence in field mappings and schema health, and creates an enterprise-grade user experience identical to MuleSoft Dataloader.io.
17. **Dynamic Multi-Object & Multi-Primary Key Architecture (`core/mapping_loader.py`, `salesforce/data_fetcher.py`, `ui/data_load.py`)**:
   - *Decision:* Dynamically inspect `Mapping_file.xlsx` for all distinct objects (`loader.objects()`) and all declared primary keys (`loader.all_primary_keys()`). The UI presents object pills, an interactive object filter bar (`[All Objects] [BT Project] [Project]`), individual object badges and gold `🔑 PRIMARY KEY` tags on each mapping row, and lets users dynamically target specific objects during live SOQL fetches and Bulk API 2.0 uploads.
   - *Reason:* Real-world Sitetracker reports (such as Apollo 10G) frequently span multiple related Salesforce objects (e.g. `BT Project` and `Project`) and can have composite or per-object primary keys. Hardcoding a single object (`Site__c`) or single primary key broke multi-object reports and caused SOQL query failures.
18. **Dynamic Real-Time Salesforce Session Verification & Unified Multi-Object SOQL Fetch (`salesforce/auth.py`, `app.py`, `ui/data_load.py`)**:
   - *Decision:* Implement dynamic real-time Salesforce session verification (`check_connection_status`) pinging `/services/oauth2/userinfo` with 30s TTL in-memory caching and a 2.5s network timeout. Discontinue legacy `.sf_auth.json` file writes/syncs to prevent stale ghost tokens. Update UI active environment indicators across `app.py` and `ui/data_load.py` to display `● Connected` only when an active, live verified session exists, and `○ Disconnected` / `● Offline` otherwise. In Step 1 of Data Load, streamline live data retrieval into a unified 1-click SOQL fetch querying all mapped fields across objects into the Sitetracker baseline CSV, while preserving object badges and filter buttons in Step 2 for inspection.
   - *Reason:* Statically checking file existence or arithmetic timestamps caused false-positive connected statuses when tokens were invalidated, offline, or expired. Forcing users to select individual objects for SOQL fetching fragmented multi-object reports; a single 1-click fetch retrieves all mapped fields needed to compute deltas against source files while maintaining clear object reference badges.


