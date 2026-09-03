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
- `app.py`: The main Streamlit entry point. Renders the dashboard and triggers the core engine.
- `data_load.py`: UI page for selecting reports, previewing mappings, 1-click live SOQL fetching from Sitetracker, validating inputs, visual source grid with status badges, and running delta generation.
- `run_history.py`: UI page for browsing past engine runs, viewing execution metrics, re-downloading output files, and inspecting archived source inputs.
- `mapping_editor.py`: Interactive UI allowing the user to view and edit mapping rules directly in the browser with history/rollback capabilities.
- `data_export.py`: Handles downloading the output files, authenticating via OAuth/manual tokens, inspecting SObjects, and monitoring live Salesforce API quotas and limits.

### `/salesforce` (Integrations)
- `auth.py`: Handles OAuth, manual token authentication, and automatic token refreshing with Salesforce.
- `client.py`: API wrapper for making legacy REST requests to SFDC.
- `sf_client.py`: Bridge module providing a `simple-salesforce` client (`Salesforce`) backed by existing `.sf_auth.json` OAuth tokens with automatic expiration refresh.
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

### Root Files
- `cli.py`: Command-line interface for scaffolding or running reports without the UI.
- `quick_test.py`: End-to-end integration test script.
- `app.py`: Symlink or wrapper to `ui/app.py` for running Streamlit from root.

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


