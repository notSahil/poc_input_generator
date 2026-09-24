# Streamlit UI & User Experience Architecture Decision Records (ADRs)

> Historical context explaining WHY Streamlit views, 4-step stepper wizards, SLDS design tokens, and session reconnection features were built this way.

---

### ADR 16: Dataloader.io Enterprise UI Overhaul & Guided Pipeline Stepper (`ui/data_load.py`, `ui/styles.py`, `ui/components.py`, `app.py`)
- **Decision:** Restyle the frontend using Salesforce Lightning Design System (SLDS) CSS tokens and refactor `ui/data_load.py` from a monolithic vertical scrolling page into a guided 4-step pipeline wizard (`1. Source & Object` ➔ `2. Field Mapping` ➔ `3. Delta Engine` ➔ `4. Review & Ingest`) with visual 3-column connector cards, executive KPI metric tiles, and `streamlit-antd-components` stepper integration.
- **Reason:** Eliminates vertical scroll fatigue, establishes a clear mental model of data pipeline progression, gives users immediate visual confidence in field mappings and schema health, and creates an enterprise-grade user experience identical to MuleSoft Dataloader.io.

---

### ADR 19: Ad-Hoc / Manual Dataloader Architecture (Dataloader.io Mode) (`core/manual_engine.py`, `salesforce/adhoc_fetcher.py`, `ui/manual_loader.py`)
- **Decision:** Deliver ad-hoc manual data loading as a dedicated, architecturally quarantined module rather than adding branching logic into the existing report pipeline. Provide live describeGlobal object discovery, dynamic field describe, an intelligent auto-matcher comparing CSV headers to Salesforce fields, an interactive row-by-row selection table with field upload checkboxes, and a headless comparison engine (`ManualLoadEngine`) that validates dates, numbers, duplicate keys, and missing keys while generating the exact 5 standard output files + `rollback_file.csv` with `#N/A` clearance.
- **Reason:** Gives users complete freedom to update any custom or standard Salesforce object without modifying the static Excel mapping file or YAML configurations, while guaranteeing 100% zero blast radius and backwards compatibility for existing production reports (`Apollo 10G`, `Master Site Listing`).

---

### ADR 24: Dedicated Revert Progress Telemetry, Enterprise Branding Decoupling, and Port 8080 Portable Launchers (`ui/data_load.py`, `app.py`, `ui/manual_loader.py`, `run_windows.bat`, `run_company_laptop_8080.bat`, `run_company_laptop_8080.sh`)
- **Decision:** Remove intrusive "Phone Disconnect Safe" banners from the active ingest screen. Add distinct, dedicated rollback / revert progress visualization when `is_rollback=True` (displaying "Revert / Rollback in Progress", restored record counts, and revert in-flight notifications). Replace all copycat "Dataloader.io" terminology across navigation cards and headers with clear enterprise descriptions of delta computation and schema synchronization. Add portable launchers configured for port 8080.
- **Reason:** Extraneous banners added visual noise and cluttered the progress monitor. Rollback operations previously reused ingest phrasing ("Ingestion in Progress"), creating operator confusion. Decoupling from "Dataloader.io" naming conveys proper enterprise software identity, and port 8080 launchers enable seamless execution on company laptops without port conflict.

---

### ADR 26: Enterprise 4-Screen Manual Dataloader Wizard & Safety Gates (`ui/manual_loader.py`, `core/manual_engine.py`, `core/exceptions.py`, `config/settings.py`)
- **Decision:** Refactor the ad-hoc manual upload flow into a focused, sequential 4-screen wizard:
  1. `Screen 1: Select Object & Upload File` (Target object discovery, operation selection [Update active, Insert upcoming], multi-format file upload, leading-zero preservation).
  2. `Screen 2: Load/Create Mapping Profile & Select Match Key` (Saved profile management in `data/mapping_profiles/`, authoritative match key derivation from `Mapping_file.xlsx` or manual selection with zero guessing, field mapping table with status, data types, and Ignored toggles).
  3. `Screen 3: Validate, Preview Changes, & Safety Gates` (Delta comparison, live SOQL query by business key resolving to Salesforce `Id`, First Occurrence Wins source duplicate quarantine to `duplicate_primary_keys.csv`, ambiguous Salesforce duplicate detection blocking execution via `duplicate_salesforce_records.csv`, unmatched records default-excluded with mandatory confirmation checkbox, empty match key validation gate, and auto-resetting safety confirmation state).
  4. `Screen 4: Run Results & Downloads` (Execution metrics, 1-click downloads for final input, rollback file, field level changes, duplicate files, skipped records, and audit log, with instant 1-click rollback restoration).
- **Reason:** Eliminates heuristic guessing of primary keys, prevents accidental cloud data corruption caused by ambiguous duplicate matches in Salesforce, ensures strict isolation of user profiles outside `data/common/Mapping_file.xlsx` with zero credential leaks, and gives operators absolute control and visibility over unmatched or duplicate rows before any DML is executed.

---

### ADR 29: Universal In-Flight Ingest Telemetry & Session Reconnection (`ui/live_monitor.py`, `ui/components.py`, `app.py`, `ui/data_load.py`, `ui/manual_loader.py`)
- **Decision:** Implement a universal live telemetry monitor (`ui/live_monitor.py`) backed by `job_store.get_active_jobs()` and `job_manager.get_job_progress()`. Render a prominent, persistent SLDS active ingest banner on the Home page whenever any background upload or rollback is executing on the server. Add smart in-flight detection to Step 1 of both Guided and Manual Dataloaders with 1-click re-attachment buttons (`[👁️ Re-attach to Live Progress ➔]`).
- **Reason:** Long-running cloud uploads (5–15 minutes across 20+ micro-batches) previously lost their UI progress bar if the operator closed their browser, switched tabs on mobile, or refreshed the page, causing confusion over whether the upload stopped. Because background threads execute on the server and checkpoint to SQLite and `ingest_progress.json`, the server continues safely. Session reconnection restores full operator visibility, live progress telemetry, and instant 1-Click Rollback access regardless of browser disconnects.

---

### ADR 36: Post-Dataload Audit Files in Run History & Manual Dataloader Hub (`ui/run_history.py`, `ui/manual_loader.py`)
- **Decision:**
  1. **Run History Integration (`ui/run_history.py`):** Added `salesforce_success_records.csv`, `salesforce_error_records.csv`, `post_update_validation_report.csv`, and `post_update_discrepancies.csv` to the historical files download center across both Guided Report runs (`_render_run_details`) and Manual Ingestions (`_render_manual_run_details`). Enhanced file grid layout with responsive 4-column chunking.
  2. **Live Post-Audit Replay in History:** Created reusable `_render_post_audit_summary()` in `ui/run_history.py` to replay live ground-truth metrics (Fields Audited, Verified Match %, Trigger Overwrites, Stale / Not Saved) and an expandable discrepancies inspection table whenever `post_update_validation_report.csv` exists in the historical run directory.
  3. **Manual Dataloader Fix & Artifact Hub (`ui/manual_loader.py`):** De-indented Dataloader.io Results Downloads in Step 4 so that `salesforce_success_records.csv` and `salesforce_error_records.csv` are accessible immediately upon completion even when `failed_records == 0`. Added dedicated cloud transaction download buttons in Screen 4's "Download Generated Artifacts" hub.
- **Reason:** Gives operators historical access to Salesforce cloud transaction files and live reconciliation audits across past engine executions, while guaranteeing that manual ad-hoc uploads provide the same level of auditing and download convenience as automated guided reports.

---

### ADR 37: Dynamic Mapping Session Invalidation in Manual Dataloader (`ui/manual_loader.py`)
- **Decision:** Reset `st.session_state.adhoc_mappings` whenever the uploaded source file name, file size, or target object changes. Add defensive validation checking that all mapped source columns exist in the active uploaded file.
- **Reason:** When an operator uploaded a different file or changed target objects in Manual Dataloader, Streamlit retained the previously configured field mapping in `st.session_state.adhoc_mappings` (e.g. Master Site Listing columns persisting when loading an Apollo 10G file). This caused confusing phantom column selections, mismatched data types, and failed uploads. Invalidating the session cache guarantees clean, accurate mappings for every file.
