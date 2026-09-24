# Core Engine Architecture Decision Records (ADRs)

> Historical context explaining WHY core engine, data validation, delta calculation, and post-audit algorithms are built this way.

---

### ADR 1: File Archiving Strategy (`core/engine.py`)
- **Decision:** We use `shutil.copy2` instead of `shutil.move` for processing inputs.
- **Reason:** The user frequently tests the system. If we move/delete the source files, testing is annoying. Copying retains the raw inputs for repeat runs.

---

### ADR 9: Enterprise Dataloader.io Validation & Reporting (`core/engine.py` & `core/normalizer.py`)
- **Decision:** Enforce row-level atomicity matching Salesforce Data Loader — any invalid date or data type mismatch rejects the entire row rather than partially pushing other fields. Generate 8 structured output files (`final_input_file.csv`, `success_records.csv`, `error_records.csv`, `skipped_records.csv`, `validation_report.csv`, `field_level_changes.csv`, `invalid_primary_key.csv`, `duplicate_primary_keys.csv`) with strict UK `DD/MM/YYYY` date formatting.
- **Reason:** Prevents data corruption and partial record updates in Sitetracker while giving users granular error diagnostics identical to Dataloader.io.

---

### ADR 10: 1-Click Rollback Payload & Run History Browser (`core/engine.py`, `ui/run_history.py`, `ui/data_load.py`)
- **Decision:** Generate a mirror `rollback_file.csv` containing pre-change Sitetracker values whenever deltas are computed, with an emergency revert gate in Section 6. Provide a dedicated Run History & Audit browser scanning existing `runs/` and `archive/` folders with 1-click downloads.
- **Reason:** Gives the team an absolute safety net to undo accidental data writes and provides self-service auditability without needing command-line or IDE access.

---

### ADR 15: Dataloader-Style Null Wipe Safeguard & '#N/A' Bulk API 2.0 Ingest (`core/engine.py`, `salesforce/bulk_uploader.py`, `ui/data_load.py`, `cli.py`)
- **Decision:** Blank cells in the source input file are ignored by default (`insert_nulls=False`), preserving existing Sitetracker data. Users can explicitly enable the 'Overwrite with Blanks (Insert Nulls)' toggle in the UI or CLI (`--insert-nulls`), which serializes empty fields as `#N/A`. The Bulk API 2.0 uploader preserves `#N/A` strings and avoids pandas default NA conversion (`keep_default_na=False`).
- **Reason:** Salesforce Bulk API 2.0 ignores empty strings in CSV uploads; only the literal string `#N/A` instructs Salesforce to clear a field. Defaulting to ignore-blanks prevents accidental data wipes if users upload partial spreadsheets, while `#N/A` enables explicit field clearance matching Dataloader.io behavior.

---

### ADR 17: Dynamic Multi-Object & Multi-Primary Key Architecture (`core/mapping_loader.py`, `salesforce/data_fetcher.py`, `ui/data_load.py`)
- **Decision:** Dynamically inspect `Mapping_file.xlsx` for all distinct objects (`loader.objects()`) and all declared primary keys (`loader.all_primary_keys()`). The UI presents object pills, an interactive object filter bar (`[All Objects] [BT Project] [Project]`), individual object badges and gold `🔑 PRIMARY KEY` tags on each mapping row, and lets users dynamically target specific objects during live SOQL fetches and Bulk API 2.0 uploads.
- **Reason:** Real-world Sitetracker reports (such as Apollo 10G) frequently span multiple related Salesforce objects (e.g. `BT Project` and `Project`) and can have composite or per-object primary keys. Hardcoding a single object (`Site__c`) or single primary key broke multi-object reports and caused SOQL query failures.

---

### ADR 23: InputValidator Subdirectory Isolation & Dynamic Baseline Origin Badges (`core/validator.py`, `ui/data_load.py`, `tests/test_validator.py`)
- **Decision:** Enforce `f.is_file()` inside `InputValidator._get_single_file()` to strictly exclude subdirectories (such as `archive/` created by file uploaders). Render prominent SLDS badges across Step 1 (Source & Object), Step 3 (Delta Engine), and Step 4 (Review & Ingest) dynamically distinguishing between `🌐 LIVE SITETRACKER (SOQL QUERY)` and `📁 OFFLINE SPREADSHEET FILE`, displaying exact timestamps and record counts.
- **Reason:** When users upload files via the Streamlit UI, previous files are archived into an `archive/` subdirectory. `InputValidator` was reading `folder.iterdir()` without checking `f.is_file()`, treating `archive/` as a second data file and failing runs with `Source directory must contain exactly 1 file, found 2: ['file.csv', 'archive']`. Filtering `f.is_file()` eliminates this fatal error, and dynamic origin badges provide absolute clarity on whether deltas are being computed against real-time cloud data or static disk spreadsheets.

---

### ADR 25: Simple, Reliable Per-Run Audit Logging (`core/audit_logger.py`, `core/engine.py`, `core/manual_engine.py`, `salesforce/job_manager.py`, `ui/data_load.py`, `ui/run_history.py`)
- **Decision:** Implement a dedicated, thread-safe, non-blocking `AuditLogger` writing a human-readable `audit.log` into every run directory (`runs/<date>/run_<time>/audit.log` and `data/manual_runs/<obj>/<date>/run_<time>/audit.log`). Log 6 essential operational checkpoints: Run start (user, org, mode), Input/validation, Upload progress (batches, size, duration), Salesforce record errors (ID, field, error code, message), Python tracebacks (standard `traceback.format_exc()` without local variables), and Run completion (status, duration, output files). Enforce strict security masking for tokens and secrets, and wrap file writing in defensive error boundaries so logging failures can never disrupt data operations. Add "View Log" and "Download Log" controls in Step 4 and Run History.
- **Reason:** Operators and engineers need clear, immediate forensic visibility when a data load fails, without requiring server terminal access or complex log aggregation infrastructure. Thread-safe file appending ensures background upload workers write safely, while secret masking protects against token leaks in compliance with security policies.

---

### ADR 31: Interactive Field Mapping, Column Presence Badges, & Custom Mapping Overrides in Guided Pipeline (`ui/data_load.py`, `core/mapping_loader.py`, `core/validator.py`, `core/engine.py`)
- **Decision:** Enhance Step 1 & Step 2 of Guided Pipeline with early header mismatch detection, column presence badges (`✅ Found in Source` / `⚠️ Missing in Source`), clean `TEXT` fallback for empty data types, and an on-the-fly interactive mapping customizer with source column dropdowns and ignore toggles. Extend `MappingLoader`, `InputValidator`, and `InputFileEngine` with a backwards-compatible `custom_mapping_df: pd.DataFrame | None = None` keyword-only parameter.
- **Reason:** When operators upload a file with different column names or missing non-essential fields, the pipeline previously failed late in Step 3 without visual feedback in Step 2. Early mismatch detection alerts the operator immediately in Step 1, status badges clearly indicate column coverage, and interactive customization allows updating subsets of fields on the fly without modifying the protected corporate Excel template `data/common/Mapping_file.xlsx`.

---

### ADR 32: Sitetracker Header Self-Healing Aliasing & Universal Column Resolver (`core/normalizer.py`, `core/validator.py`, `core/engine.py`, `salesforce/data_fetcher.py`, `ui/data_load.py`)
- **Decision:** Introduce a centralized, pure static resolver `DataNormalizer.resolve_source_column(candidates, s_col, st_col=None, api_col=None)` with strict precedence hierarchy: (1) Exact match for `Source File Column Name`, (2) Exact match for `Sitetracker Field Name`, (3) Exact match for `API Name`, and (4-6) Case-insensitive and whitespace-stripped matches. Integrate this resolver uniformly across `InputValidator`, `InputFileEngine`, `DataFetcher`, and `ui/data_load.py`. In Step 1, auto-detect Sitetracker export formats (e.g. `Project Reference`, `Ran Priority`) and display an informative green/blue confirmation banner instead of a false-positive mismatch error. In Step 2, auto-select matching columns in the interactive customizer dropdowns and display `✅ Auto-Matched (<col>)` status badges.
- **Reason:** Users regularly download baseline exports or reports directly from Sitetracker, edit a few values, and upload them back into the pipeline as the source file. Because Sitetracker exports use Sitetracker field names rather than vendor spreadsheet headers from `Mapping_file.xlsx`, previous versions raised false-positive mismatch warnings, defaulted dropdowns to skip, failed live SOQL primary key extraction, and aborted with `ValidationError`. Self-healing aliasing guarantees 100% interoperability with direct Sitetracker downloads without modifying the protected corporate mapping file.

---

### ADR 33: Unified Interactive Field Mapping Table & Strict ISO Date Normalization (`core/normalizer.py`, `salesforce/bulk_uploader.py`, `ui/data_load.py`)
- **Decision:**
  1. **Strict ISO Date Normalization**: In `DataNormalizer.normalize_date_uk()` and `salesforce/bulk_uploader._format_date()`, inspect date strings for ISO format (`^\d{4}-\d{2}-\d{2}`). If matched, parse strictly with `dayfirst=False` (or `format="%Y-%m-%d"`); otherwise parse with `dayfirst=True`.
  2. **Unified Interactive Step 2 Screen**: Merge the redundant collapsed expander and static HTML list in Step 2 of `ui/data_load.py` into a single, cohesive **Interactive Field Mapping Table**. Every Sitetracker field row displays the target field, object, data type badge, interactive source column dropdown (auto-selected via `resolve_source_column`), and real-time match status pill (`✅ Exact Match`, `✅ Auto-Matched`, `✏️ Custom Mapped`, `⏭ Skipped`, `⚠️ Missing in File`). Include top/bottom action bars with `[💾 Apply Mapping]` and `[🔄 Reset Defaults]`, and prevent skipping the Primary Key.
- **Reason:** When comparing Sitetracker ISO dates (e.g. `2019-07-06` for July 6th) with UK spreadsheet dates (e.g. `06/07/2019`), pandas `dayfirst=True` incorrectly interpreted the ISO date as June 7th (`07/06/2019`), generating false deltas in `field_level_changes.csv`. Checking ISO format eliminates all false date deltas. Concurrently, displaying interactive dropdowns directly in the main Step 2 table eliminates operator confusion over static read-only field lists and provides seamless on-the-fly column customization.

---

### ADR 35: 2-Tier Post-Dataloader Audit & Live Salesforce Ground-Truth Verification (`core/post_validator.py`, `salesforce/post_fetcher.py`, `salesforce/composite_uploader.py`, `salesforce/bulk_uploader.py`, `salesforce/job_manager.py`, `ui/data_load.py`, `ui/manual_loader.py`)
- **Decision:** Implement a comprehensive two-tier post-ingest audit architecture:
  1. **Tier 1 (Transaction-Level Audit — Dataloader.io Parity):** Immediately upon ingest completion, generate `salesforce_success_records.csv` and `salesforce_error_records.csv` enriched with the source Primary Key (`Project Ref` / `Site ID`), Salesforce `Id`, and exact Salesforce error codes/messages (e.g. `ENTITY_IS_LOCKED`, custom validation exceptions).
  2. **Tier 2 (Deep Ground-Truth Verification — Live SOQL Reconciliation):** Automatically query live Salesforce records via chunked SOQL (`salesforce/post_fetcher.py`) for all successful records, compare expected vs actual live values using semantic equivalence (UK vs ISO dates, numbers, `#N/A` null wipes), and generate `post_update_validation_report.csv` and `post_update_discrepancies.csv`.
  3. **UI Step 4 & Screen 4 Integration:** Render Dataloader.io success/error download buttons and an interactive Post-Update Live Audit card with KPI metric tiles (Fields Audited, Verified Match %, Trigger Overwrites, Stale) and an expandable discrepancies inspector.
- **Reason:** Dataloader transaction receipts only verify that Salesforce accepted the API payload without throwing an exception. They cannot detect if an Apex trigger silently changed a value afterwards, if a locked formula prevented a write, or if a null wipe failed. Live SOQL verification gives operators 100% forensic certainty.

---

### ADR 38: Multi-Object Schema Completeness, Resilient Validation & Run History 1-Click Revert Safety Net (`core/validator.py`, `core/engine.py`, `ui/run_history.py`)
- **Decision:**
  1. *Resilient Column Validation (`core/validator.py`)*: Allow source spreadsheets to contain a subset of mapped columns. Missing non-PK columns produce informative warnings (and are safely skipped by the engine), while requiring at least the Primary Key and one mapped data field.
  2. *Schema Completeness (`core/engine.py`)*: Apply `.reindex(columns=...)` across `final_df`, `rollback_df`, and per-object payloads (`df_obj_updates`, `df_obj_rollbacks`) to guarantee 100% header preservation even when fields have zero changes.
  3. *Run History 1-Click Revert Safety Net (`ui/run_history.py`)*: Provide an authoritative 1-Click Rollback / Revert Safety Net card in Run History (with a `REVERT` confirmation gate and payload inspector) for both Guided and Manual runs. Render dedicated per-object download buttons for `rollback_file_<Object>.csv` and `final_input_file_<Object>.csv`.
- **Reason:** Multi-object reports (such as Apollo 10G updating both `BT Project` and `Project`) previously failed during rollback attempts because partial rollback files lacked zero-delta columns, causing fatal validation errors when re-uploaded. Furthermore, manually uploading a mixed-object rollback file to a single object caused unmatched ID errors. 1-Click Rollback in Run History allows operators to restore exact pre-change Salesforce values across all objects directly on the server without downloading, editing, or re-uploading CSVs.
