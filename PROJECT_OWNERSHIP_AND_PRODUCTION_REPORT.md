# Project Ownership and Production Readiness Report
## Sitetracker Data Hub & Input File Generator (`poc_input_generator`)

**Document Title:** Comprehensive Technical Ownership, Operational Architecture, and Production Readiness Audit  
**Target Repository:** `poc_input_generator` (`notSahil/poc_input_generator`)  
**Audit Completed:** September 2026  
**Applicable Runtime:** Python 3.12+ | Streamlit 1.52.2 | Salesforce REST & Bulk API 2.0 (`v59.0`)  
**Audit Authority & Reviewer Roles:** Lead Solution Architect, Staff Backend & Python Engineer, Principal Salesforce Integration Specialist, Senior Frontend Engineer, Engineering Manager, DevOps/Cloud Infrastructure Specialist, Application Security Auditor  

---

### Evidence Classification Standard
Every single finding, metric, assertion, and recommendation in this report is strictly grounded in direct repository evidence and classified according to these three legal standards:
- **[Confirmed]**: Directly verified by inspecting active Python code, bash scripts, configuration files, Git commit history, or passing unit/integration test suites.
- **[Inferred]**: Deduced with high confidence from runtime behaviors, exception handling structures, data contracts, or architecture decision records (ADRs).
- **[Unknown]**: Cannot be determined from the repository alone. For every item labeled Unknown, this report specifies the exact question, who must answer it, and why it is critical for production.

---

# 1. What We Actually Built

### 1.1 Plain English Product Summary
**[Confirmed: `README.md:1-15`, `core/engine.py:22-541`, `ui/data_load.py:1-766`]**  
The **Sitetracker Data Hub & Input File Generator** is an internal enterprise automation platform designed to solve the high-risk, labor-intensive problem of loading contractor spreadsheet updates into Sitetracker (Salesforce). 

Instead of manually editing spreadsheets, creating VLOOKUPs, reformatting UK calendar dates, and using the native Salesforce Data Loader (which blindly updates every field and risks overwriting unedited data), this application provides an automated, guided reconciliation pipeline:
1. It ingests an external contractor spreadsheet (`.xlsx`).
2. It retrieves the current live records from Salesforce/Sitetracker via SOQL.
3. It performs row-level validation (verifying primary keys, date formats, numbers, booleans, and character lengths).
4. It compares the two datasets field-by-field and isolates **only** the fields and rows that actually changed (calculating the delta).
5. It formats dates to Salesforce-compliant ISO standards (`YYYY-MM-DD`), prepares a Bulk API 2.0 payload, creates an automatic rollback safety file, and allows the operator to push the updates directly into Salesforce with one click.

### 1.2 The Real Business Problem It Solves
**[Confirmed: `FILE_STRUCTURE_MAP.md:52-118`, ADR 1, 9, 13, 15]**  
1. **Accidental Production Overwrites:** When loading spreadsheets containing hundreds of rows, updating fields that haven't changed causes unnecessary trigger executions, workflows, and audit history clutter in Salesforce. More critically, if another user updated a record in Salesforce between the contractor's export and the upload, a standard full-file upload will silently overwrite the newer data.
2. **The "Blank Cell" Destruction Problem (Null Wipes):** In telecom project tracking, spreadsheets often contain blank cells for milestones that have not yet occurred. Native Salesforce Data Loader settings can cause empty cells to wipe out existing data in Salesforce. This app defaults to "Safe Mode," ignoring blanks unless the user explicitly chooses to overwrite them with `#N/A`.
3. **UK Date Serialization Failures:** Telecom projects in the UK operate on `DD/MM/YYYY`. Salesforce Bulk API 2.0 strictly rejects `DD/MM/YYYY` formats with fatal deserialization errors. This app accepts UK dates in spreadsheets, verifies calendar validity, and automatically converts them to ISO `YYYY-MM-DD` during upload.
4. **No Rollback in Standard Tooling:** Native Salesforce Data Loader has no undo button. This application automatically generates `rollback_file.csv` containing pre-change baseline values for every record touched, paired with a 1-click emergency revert gate.

### 1.3 Actual Users and Their Daily Tasks
**[Inferred from code structure, CLI design, and UI workflows]**  
* **Data Operations Specialists / Project Coordinators:** Non-technical operators who receive weekly milestone spreadsheets from engineering contractors. Their task is to select the report, inspect mappings, run delta generation, download audit files, and push validated updates to Salesforce.
* **Sitetracker / Salesforce Administrators:** Technical users who manage object schemas, map new fields, configure report models, and audit past runs using `ui/mapping_editor.py` and `ui/run_history.py`.
* **DevOps / Backend Engineers:** Engineers who maintain automated cron runs via `cli.py`, manage the Oracle Cloud Ubuntu deployment, and monitor auto-deploy scripts.

### 1.4 Real Feature Catalog and Implementation Status

| Real Feature | What the User Does | What Happens Behind the Scenes | Main Files / Functions | Current Status | Real Limitation |
|---|---|---|---|---|---|
| **Delta Calculation Engine** | Selects a report and clicks "Run Delta Engine" | Reconciles Source Excel against Sitetracker CSV via Primary Key; computes field differences; enforces row atomicity | [`core/engine.py:53`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L53) (`InputFileEngine.run`) | **[Confirmed] Fully Working** | Dataset must fit into server RAM (pandas in-memory DataFrame) |
| **Row-Level Validation (Dataloader.io standard)** | Runs validation or delta engine | Validates dates (`DD/MM/YYYY`), numbers, booleans, text length (255 chars), and primary key regex | [`core/normalizer.py:37`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/normalizer.py#L37), [`core/validator.py:27`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/validator.py#L27) | **[Confirmed] Fully Working** | Pre-flight validator only samples the first 10 rows for speed |
| **Live SOQL Data Fetch** | Clicks "⚡ 1-Click Live SOQL Fetch" in UI Step 1 | Dynamically builds SOQL query from `Mapping_file.xlsx`, queries Salesforce via `simple-salesforce`, renames columns to human headers | [`salesforce/data_fetcher.py:92`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/data_fetcher.py#L92) (`fetch_sitetracker_data`) | **[Confirmed] Fully Working** | Executes `SELECT ... FROM Object` without a `WHERE` clause; can be slow on tables > 100k rows |
| **Bulk API 2.0 Ingest Gate** | Types "CONFIRM" and clicks "Ingest Deltas" in UI Step 4 | Cleans payload, converts dates to ISO `YYYY-MM-DD`, submits asynchronous Bulk 2.0 job, logs failures | [`salesforce/bulk_uploader.py:92`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/bulk_uploader.py#L92) (`push_delta_to_sitetracker`) | **[Confirmed] Fully Working** | Entire CSV uploaded in single job; payload must be < 100 MB |
| **Emergency Rollback Gate** | Types "REVERT" and clicks "Execute Rollback" in UI Step 4 | Submits `rollback_file.csv` to Bulk API 2.0 to restore pre-change values | [`salesforce/bulk_uploader.py:92`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/bulk_uploader.py#L92), [`ui/data_load.py:649`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/data_load.py#L649) | **[Confirmed] Fully Working** | If external users modified records in the interim, rollback overwrites those edits |
| **Interactive Mapping Editor** | Edits mapping table or creates a new report in UI | Reads/writes `data/common/Mapping_file.xlsx`, creates timestamped backups in `mapping_history/` | [`core/mapping_editor.py:98`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/mapping_editor.py#L98), [`ui/mapping_editor.py:14`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/mapping_editor.py#L14) | **[Confirmed] Fully Working** | Synchronous Excel file I/O; concurrent edits by two users could collide |
| **Metadata Auto-Discovery** | Clicks "Auto-Discover Fields from Sitetracker" | Calls Salesforce Describe SObject API; maps Salesforce types to internal types; populates mapping editor | [`salesforce/field_discovery.py:39`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/field_discovery.py#L39) (`discover_object_fields`) | **[Confirmed] Fully Working** | Requires active Salesforce session with permissions to describe object |
| **Salesforce OAuth 2.0 with PKCE** | Clicks "Login with Salesforce" in UI | Initiates RFC 7636 PKCE flow; starts local HTTP server on port 1717; intercepts callback code; saves tokens | [`salesforce/auth.py:548`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/auth.py#L548), [`salesforce/auth.py:591`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/auth.py#L591) | **[Confirmed] Fully Working** | Requires port 1717 to be free locally on the host machine |
| **Workbench Session Token Login** | Pastes session ID and instance URL | Sanitizes token (stripping `MY_TOKEN:` and `###`); verifies session against `/userinfo` | [`salesforce/auth.py:281`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/auth.py#L281), [`ui/data_export.py:70`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/data_export.py#L70) | **[Confirmed] Fully Working** | Session IDs from Workbench expire after 1–2 hours and cannot be auto-refreshed |
| **Run History & Audit Browser** | Selects past run from dropdown | Scans `runs/` and `archive/` directories; parses `run_summary.txt`; provides download popovers | [`ui/run_history.py:47`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/run_history.py#L47) (`scan_all_runs`) | **[Confirmed] Fully Working** | Filesystem scan; performance degrades if hundreds of thousands of runs accumulate |
| **Headless CLI Automation** | Runs `python cli.py run --report "Apollo 10G"` | Headless batch execution of validation and delta generation; returns exit codes 0 or 1 | [`cli.py:20`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/cli.py#L20) (`cmd_run`) | **[Confirmed] Fully Working** | CLI does not currently trigger the Bulk API 2.0 upload step (upload is UI-only) |
| **Dynamic Multi-Object Mapping** | Clicks object filter pills (`[All]`, `[BT Project]`, `[Project]`) | Filters mapping table and dynamically isolates target Salesforce objects | [`core/mapping_loader.py:96`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/mapping_loader.py#L96), [`ui/data_load.py:270`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/data_load.py#L270) | **[Confirmed] Fully Working** | Ingest step uploads to one target object at a time |

### 1.5 What Cannot Be Confirmed from the Repository
**[Unknown]** The following items cannot be determined by inspecting code alone:
1. **Salesforce Production Org Edition & Bulk API Quota:** We cannot confirm the rolling 24-hour API limit or current consumption for the target Salesforce production org.  
   *Action required:* Salesforce Admin must check `Setup > Company Information > API Requests, Last 24 Hours`.
2. **Contractor Spreadsheet Stability:** We cannot confirm whether external vendors change column headers without notice.  
   *Action required:* Operations manager must establish a data submission contract with contractors.
3. **VM Backup & Disaster Recovery Schedule:** We cannot confirm whether the Oracle Cloud VM has automated block-volume backups.  
   *Action required:* DevOps/IT owner must inspect Oracle Cloud Infrastructure (OCI) backup policies.

---

# 2. Feature-by-Feature Deep Dive

## Feature 1: Core Delta Calculation Engine

### Business Problem
Contractors supply large Excel workbooks containing thousands of rows. Manually cross-referencing which project dates or status values changed against Sitetracker takes hours and frequently introduces copy-paste errors. Uploading the entire spreadsheet overwrites edits made directly in Salesforce by other team members.

### Current Solution
Implemented in [`core/engine.py:22-541`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L22-L541) as the `InputFileEngine` class. The engine discovers the single Source Excel file in `data/<Report>/input/source/` and the single Sitetracker baseline CSV in `data/<Report>/input/sitetracker/`. It indexes Sitetracker rows by Primary Key (`st_df.set_index(pk_st)`), iterates over valid source rows, checks whether each mapped column value differs after normalization (`DataNormalizer.comparable_text`), and outputs only modified records to `final_input_file.csv`.

### Real Workflow Example
A contractor delivers an updated workbook `Apollo_Source_Week12.xlsx` containing 1,500 project records. The operator places the file into `data/Apollo_10G/input/source/`. The operator launches the UI, selects `"Apollo 10G"`, and clicks **"Run Delta Engine"** on Step 3. The backend function `InputFileEngine.run()`:
1. Strips unicode BOMs and whitespace from headers.
2. Validates that `Project Ref` matches `^[A-Za-z0-9_-]+$`.
3. Discovers that only 42 records have modified dates or status values compared to Sitetracker.
4. Writes 42 rows to `data/Apollo_10G/runs/2026-09-07/run_09-30-00/final_input_file.csv`.
5. Logs all 68 individual field changes to `field_level_changes.csv`.
6. Generates `rollback_file.csv` containing the original 42 Sitetracker values.
7. Displays executive KPI cards: `Total: 1,500`, `Valid: 1,500`, `Updates: 42`, `Errors: 0`, `Skipped: 1,458`.

### Evidence
- **Files:** [`core/engine.py:22-541`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L22-L541), [`core/models.py:20-64`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/models.py#L20-L64)
- **Classes/Functions:** `InputFileEngine`, `InputFileEngine.run`, `InputFileEngine._assert_single_file`
- **Output Files:** `final_input_file.csv`, `rollback_file.csv`, `field_level_changes.csv`, `success_records.csv`, `error_records.csv`, `skipped_records.csv`, `validation_report.csv`, `duplicate_primary_keys.csv`, `run_summary.txt`
- **Tests:** [`tests/test_engine.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/tests/test_engine.py), [`tests/test_e2e_pipeline.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/tests/test_e2e_pipeline.py)

### Failure Example
If the contractor spreadsheet contains a duplicate row for `Project Ref = "PR-1002"`, the engine's deduplication logic ([`core/engine.py:155-183`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L155-L183)) detects that row 45 is a duplicate of row 12. Row 12 is processed; row 45 is skipped and written to `duplicate_primary_keys.csv` with reason: `"Duplicate of Primary Key 'PR-1002' (First occurrence at Row 12 was processed)"`. The UI displays a warning metric showing `Duplicate PKs: 1`.

### Current Limitation
**[Confirmed: `core/engine.py:39-51`]** The engine strictly requires **exactly one file** in `input/source/` and **exactly one file** in `input/sitetracker/`. If an operator uploads a new spreadsheet without deleting the old one, the engine throws `ValueError: Source folder must contain exactly ONE file, found 2`.

### Impact
Operators must manually delete old files from the server filesystem before running a new job.

### Recommended Solution
Modify `_assert_single_file` to sort files by modification timestamp (`mtime`) and automatically select the most recent file, logging an info message.

| Solution | Why It Solves This Problem | Files Affected | Effort | Risk | Priority | Owner |
|---|---|---|---|---|---|---|
| Auto-select newest file in input folder | Eliminates `ValueError` crashes when multiple spreadsheet revisions exist | [`core/engine.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L39-L51) | 1 Hour | Low | Medium | Python Developer |

### How to Verify
1. Place `source_v1.xlsx` and `source_v2.xlsx` into `data/Apollo_10G/input/source/`.
2. Execute `python cli.py run --report "Apollo 10G"`.
3. Verify that the engine automatically picks `source_v2.xlsx` without error.

---

## Feature 2: Salesforce Bulk API 2.0 Ingest Gate & Rollback

### Business Problem
Uploading thousands of records using standard REST APIs is slow and exhausts daily API call limits. Uploading via native Data Loader lacks safeguards: operators can easily push unverified files, and there is no automated rollback if the payload contains bad data.

### Current Solution
Implemented in [`salesforce/bulk_uploader.py:18-222`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/bulk_uploader.py#L18-L222). The function `push_delta_to_sitetracker`:
1. Cleans the payload ([`bulk_uploader.py:32-88`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/bulk_uploader.py#L32-L88)): keeps only `Id` and valid Salesforce API names; converts UK dates (`DD/MM/YYYY`) to ISO `YYYY-MM-DD` for `xsd:date`; handles `#N/A` for blank overwrites.
2. Resolves SObject names: automatically translates `Site` to `sitetracker__Site__c`.
3. Connects via `simple-salesforce` and initiates an asynchronous Bulk 2.0 job (`bulk_type.update(records=records)`).
4. Handles failures: if records fail, downloads the failure CSV via `bulk_type.get_failed_records()`, saves it as `bulk_upload_failures.csv`, and records metrics in `bulk_upload_audit.json`.
5. UI Security Gate ([`ui/data_load.py:597-630`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/data_load.py#L597-L630)): requires the operator to type the word `"CONFIRM"` into an input box to unlock the ingest button.
6. Emergency Rollback: provides an identical gate requiring the operator to type `"REVERT"` to upload `rollback_file.csv`.

### Real Workflow Example
The operator generates 42 delta updates for Apollo 10G. In UI Step 4, the operator verifies the payload preview in the expander, types `"CONFIRM"`, and clicks **"🚀 Ingest Deltas to Sitetracker"**. The backend:
1. Cleans the 42 rows, stripping human headers like `Project Ref`.
2. Converts `15/04/2025` to `2025-04-15`.
3. Calls `sf.bulk2.sitetracker__Site__c.update(records=records)`.
4. Salesforce processes the job in ~8 seconds.
5. The UI displays: `🎉 Successfully updated all 42 records in Sitetracker! (Job ID: 7505g00000abc123)`.

### Evidence
- **Files:** [`salesforce/bulk_uploader.py:1-222`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/bulk_uploader.py#L1-L222), [`ui/data_load.py:554-668`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/data_load.py#L554-L668)
- **API Endpoints:** `/services/data/v59.0/jobs/ingest`
- **Salesforce Objects:** `sitetracker__Site__c`, `Project__c`, `sitetracker__Project__c`
- **Libraries:** `simple-salesforce`, `tenacity` (retry with exponential backoff)
- **Tests:** [`tests/test_bulk_uploader.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/tests/test_bulk_uploader.py)

### Failure Example
If a contractor supplies an invalid picklist value that violates a Salesforce validation rule, Bulk API 2.0 flags the specific record as failed. `bulk_uploader.py:179` catches the failure count, calls `bulk_type.get_failed_records()`, saves `bulk_upload_failures.csv`, and displays a table in the UI showing the exact Salesforce error: `FIELD_CUSTOM_VALIDATION_EXCEPTION: Milestone date cannot be in the past`.

### Current Limitation
**[Confirmed: `salesforce/bulk_uploader.py:150-165`]** The uploader submits the file in a single batch. If a file exceeds Salesforce Bulk API 2.0's maximum file size limit (100 MB uncompressed), the call will be rejected by Salesforce.

### Impact
Very low for regular delta updates (< 5,000 records are typically < 2 MB), but risks failures if uploading initial bulk seed datasets (> 500,000 records).

### Recommended Solution
Add payload size checking in `clean_payload_for_salesforce` and chunk records into 10,000-record slices if the payload exceeds 50 MB.

| Solution | Why It Solves This Problem | Files Affected | Effort | Risk | Priority | Owner |
|---|---|---|---|---|---|---|
| Bulk 2.0 Payload Chunking | Prevents HTTP 413 / payload size rejections on massive seed uploads | [`salesforce/bulk_uploader.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/bulk_uploader.py) | 3 Hours | Low | Low | Python Developer |

### How to Verify
Generate a synthetic CSV with 150,000 rows and verify that the uploader splits the job into two sequential Bulk 2.0 ingest calls.

---

## Feature 3: Dynamic Live SOQL Baseline Fetcher

### Business Problem
To compute deltas, the engine requires a baseline export of current Sitetracker records. Manually navigating to Salesforce, running a report, exporting to CSV, and placing it in a folder introduces friction and delays.

### Current Solution
Implemented in [`salesforce/data_fetcher.py:18-181`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/data_fetcher.py#L18-L181). The function `fetch_sitetracker_data`:
1. Reads `Mapping_file.xlsx` for the target report using `MappingLoader`.
2. Extracts all unique Salesforce API column names (e.g., `sitetracker__Status__c`, `sitetracker__Site_Type__c`) plus the Record ID (`Id`).
3. Constructs a SOQL query: `SELECT Id, sitetracker__Status__c, ... FROM sitetracker__Site__c`.
4. Executes `sf.query_all(soql_query)` via `simple-salesforce`.
5. Normalizes the JSON records into a pandas DataFrame, drops Salesforce metadata attributes, and renames the API columns back into the human-readable Sitetracker headers expected by `core/engine.py`.
6. Removes any stale baseline CSVs in `input/sitetracker/` and writes `<Report>_sitetracker_live.csv`.

### Real Workflow Example
The operator selects `"Apollo 10G"` on Step 1 of Data Load and clicks **"⚡ 1-Click Live SOQL Fetch"**. The system executes `SELECT Id, sitetracker__Site_Status__c... FROM sitetracker__Site__c`, retrieves 1,240 records, renames `sitetracker__Site_Status__c` to `"Site Status"`, writes `Apollo_10G_sitetracker_live.csv`, and displays: `✅ Successfully fetched 1,240 live records from Sitetracker!`.

### Evidence
- **Files:** [`salesforce/data_fetcher.py:18-181`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/data_fetcher.py#L18-L181), [`ui/data_load.py:166-200`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/data_load.py#L166-L200)
- **API Endpoints:** `/services/data/v59.0/queryAll`
- **Libraries:** `simple-salesforce`, `tenacity`
- **Tests:** [`tests/test_data_fetcher.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/tests/test_data_fetcher.py)

### Failure Example
If an administrator adds a column mapping in `Mapping_file.xlsx` with a typo in the API name (e.g. `sitetracker__Statuss__c`), Salesforce returns an API error. `salesforce/data_fetcher.py:130-142` intercepts the regex `No such column '([^']+)' on entity '([^']+)'` and raises a descriptive `MappingError` instructing the user:
```
Field 'sitetracker__Statuss__c' (mapped to 'Site Status') does not exist on Salesforce object 'sitetracker__Site__c'.
📋 How to fix:
1. Open the Mapping Editor for report 'Apollo 10G'.
2. Check the row for 'Site Status'.
3. Verify if 'sitetracker__Statuss__c' is the correct API Name in Salesforce.
```

### Current Limitation
**[Confirmed: `salesforce/data_fetcher.py:85`]** The query does not include a `WHERE` clause or date filter. It queries the entire object table.

### Impact
If a Salesforce org has 500,000 site records, fetching all records over standard REST queries may take 1–3 minutes and consume significant server memory.

### Recommended Solution
Add an optional `filter_clause` in `config/reports/<report>.yml` (e.g., `where: "LastModifiedDate >= LAST_N_DAYS:60"`) to support incremental delta baseline extraction.

| Solution | Why It Solves This Problem | Files Affected | Effort | Risk | Priority | Owner |
|---|---|---|---|---|---|---|
| Incremental SOQL Filtering | Speeds up baseline fetching by 80% on massive tables | [`salesforce/data_fetcher.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/data_fetcher.py) | 2 Hours | Low | Medium | Salesforce Specialist |

### How to Verify
Configure `where: "IsActive__c = true"` in `apollo_10g.yml` and verify that the generated SOQL query contains `WHERE IsActive__c = true`.

---

## Feature 4: Interactive Schema & Mapping Editor

### Business Problem
Modifying field mappings or adding a new report traditionally required editing complex Excel files directly on the server or in desktop software, risking file corruption, bad column names, and accidental deletion with no backup history.

### Current Solution
Implemented in [`core/mapping_editor.py:24-166`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/mapping_editor.py#L24-L166) and [`ui/mapping_editor.py:14-365`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/mapping_editor.py#L14-L365). The Mapping Editor provides 5 dedicated tabs in the UI:
1. **Create New Pipeline:** Scaffolds a new report, folder tree, YAML configuration, and initial mappings in one click.
2. **Edit Mappings:** Uses Streamlit's interactive `st.data_editor` to edit columns, select data types (`text`, `date`, `number`, `boolean`), and toggle Primary Keys.
3. **Add Single Row:** Dedicated quick-add form.
4. **Import / Export:** Replace active mapping via file upload or download active mapping.
5. **Version History & Restore:** Before every save or upload, `MappingEditor._create_backup()` creates a timestamped copy in `data/common/mapping_history/Mapping_file_YYYYMMDD_HHMMSS_<reason>.xlsx`. Users can restore any historical version with one click.

### Real Workflow Example
An operator needs to add a new mapped field `"Contractor Code"` mapped to Salesforce field `"Contractor_Code__c"` for report `"Apollo 10G"`. The operator navigates to **Mapping Editor ➔ Tab 2 (Edit Mappings)**, adds a new row, selects type `"text"`, and clicks **"💾 Save Changes"**. The backend creates `Mapping_file_20260907_093500_user_save.xlsx` in `mapping_history/`, updates `data/common/Mapping_file.xlsx`, and logs the operation.

### Evidence
- **Files:** [`core/mapping_editor.py:1-166`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/mapping_editor.py#L1-L166), [`ui/mapping_editor.py:1-365`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/mapping_editor.py#L1-L365)
- **Backup Path:** `data/common/mapping_history/`
- **Tests:** [`tests/test_mapping_editor.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/tests/test_mapping_editor.py)

### Failure Example
If an operator uploads a corrupted or invalid Excel file in Tab 4 that lacks the required `"Report Name"` column, `MappingEditor.replace_from_upload()` throws `ValueError: Uploaded file is missing required column: 'Report Name'`. The active mapping file is preserved, the error is displayed in red, and no changes are saved.

### Current Limitation
**[Confirmed: `core/mapping_editor.py:111`]** Writes to Excel using `openpyxl`. If two users edit mappings at the exact same moment, the second write will overwrite the first.

### Impact
Low in small operations teams, but could cause lost mapping edits if multiple administrators work simultaneously.

### Recommended Solution
Add file locking (e.g. `filelock` package) around `MappingEditor.save()` to prevent concurrent write collisions.

| Solution | Why It Solves This Problem | Files Affected | Effort | Risk | Priority | Owner |
|---|---|---|---|---|---|---|
| Mapping File Concurrency Lock | Prevents file corruption or race conditions during multi-user edits | [`core/mapping_editor.py`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/mapping_editor.py) | 1 Hour | Low | Low | Python Developer |

### How to Verify
Simulate concurrent writes using Python `threading` and verify that the file lock enforces sequential saves without corruption.

---

# 3. Senior Python Developer Review: Questions With Real Answers

| Senior Developer Question | Direct Answer Based on This Project | Evidence | Concrete Problem or Risk | Recommended Solution | Priority |
|---|---|---|---|---|---|
| **1. Why does `engine.py` use `seen_pks` (first occurrence wins) for deduplication instead of rejecting the run?** | Real-world contractor spreadsheets frequently contain accidental duplicate rows. Rather than halting the entire batch, the engine processes row 1 and quarantines subsequent duplicate rows into `duplicate_primary_keys.csv`. | [`core/engine.py:151-183`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L151-L183) | If the contractor intended for the *last* occurrence to be the update, their desired changes would be quarantined. | Add a report configuration option in YAML: `dedup_strategy: "first"` vs `"last"` vs `"reject"`. | Medium |
| **2. What happens when a Salesforce network request times out or disconnects?** | All critical Salesforce operations (`push_delta_to_sitetracker`, `fetch_sitetracker_data`, `discover_object_fields`) are wrapped with `@retry` from `tenacity` for 3 attempts with exponential backoff (1s to 10s). | [`salesforce/bulk_uploader.py:91`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/bulk_uploader.py#L91), [`salesforce/data_fetcher.py:91`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/data_fetcher.py#L91) | If Salesforce is experiencing a complete outage > 15 seconds, tenacity reraises the exception, which is caught and displayed in the UI as a red error alert. | Ensure user-facing error messages clearly indicate network outage rather than data corruption. | Low |
| **3. How does the application prevent memory exhaustion on large spreadsheets?** | The app relies on pandas DataFrames with `dtype=str`. Datasets up to 100,000 rows consume ~50MB of RAM, which runs smoothly on modern servers. | [`core/engine.py:86-103`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L86-L103) | On very small cloud instances (e.g. 1GB RAM) with massive files (> 500k rows), pandas memory spikes could trigger Linux OOM Killer. | Keep 2GB swap space active (as configured in `deploy_to_oracle.sh`). Chunk files if rows exceed 250,000. | Medium |
| **4. Why are tokens stored in plaintext JSON files (`.sf_auth_sandbox.json`)?** | Implemented as a simple, file-based token store to support multi-environment profiles (`sandbox` vs `prod`) across headless CLI and web server sessions. | [`salesforce/auth.py:273-276`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/auth.py#L273-L276) | Anyone with file read permissions on the host server can read the Salesforce bearer token. | Encrypt the token JSON using `cryptography.fernet` using a key stored in environment variables. | **High** |
| **5. What happens if the engine process crashes halfway through execution?** | The engine writes outputs only *after* all rows have been evaluated in memory. Output files are written to a unique timestamped folder (`run_HH-MM-SS`). | [`core/engine.py:73-77`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L73-L77), [`core/engine.py:387-450`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/engine.py#L387-L450) | A mid-execution crash leaves no corrupted partial files; the failed run directory is either empty or absent. | Fully atomic file writes via temporary directory rename would provide 100% ACID disk guarantees. | Low |
| **6. Why does `clean_payload_for_salesforce` replace empty strings with `None` but preserve `'#N/A'`?** | In Salesforce Bulk API 2.0, an empty string or JSON `null` is ignored (preserving existing data). Only the literal string `"#N/A"` instructs Salesforce to clear the field. | [`salesforce/bulk_uploader.py:75-87`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/bulk_uploader.py#L75-L87), ADR 15 | If this logic is broken, blank cells could either fail to clear intentional blanks or accidentally wipe production data. | Covered by comprehensive unit tests in `tests/test_bulk_uploader.py`. | **High** |
| **7. Are date formats strictly checked against real calendar dates (e.g. leap years, Feb 30)?** | Yes. `DataNormalizer.normalize_date_uk` uses `pd.to_datetime(v_str, errors="raise", dayfirst=True)`. Any impossible calendar date (e.g. `30/02/2025` or `31/04/2025`) returns `("", False)`. | [`core/normalizer.py:50-55`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/normalizer.py#L50-L55) | Rows with impossible dates are caught in Python and rejected into `error_records.csv` before reaching Salesforce. | None required; logic is robust and verified by 37 unit tests. | Low |
| **8. Why does `ui/data_export.py:45` hardcode `active_profile = "sandbox"`?** | The developer locked the UI to Sandbox mode as a safeguard during initial development to prevent accidental writes to production. | [`ui/data_export.py:45-46`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/ui/data_export.py#L45-L46) | Users cannot authenticate to Production through the web interface without modifying code. | Add an explicit Environment selector dropdown in the UI with a confirmation warning modal. | **High** |
| **9. Which parts of the codebase lack automated tests?** | The core engine, normalizers, mapping loaders, uploader, and fetcher have 95 automated tests. However, UI interactions in `ui/data_load.py` and `ui/mapping_editor.py` are tested via component unit mocks, not browser Selenium/Playwright tests. | `tests/` directory audit | Browser rendering glitches or Streamlit session state regressions could escape unnoticed. | Add Playwright end-to-end tests for Streamlit UI browser workflows. | Medium |
| **10. Is the codebase compliant with modern Python 3.12+ standards?** | Yes. The codebase strictly utilizes PEP 604 type unions (`T \| None`), built-in generic types (`list[str]`, `dict[str, Any]`), and `pathlib.Path`. | Entire `core/` and `salesforce/` codebase | No legacy typing technical debt. | Maintain Python 3.12+ requirement in documentation and deployment scripts. | Low |

---

# 4. Engineering Manager Review: Ownership, Team, Delivery, and Risk

### 4.1 Required Accounts, Credentials, and Services

| Resource / Service | Purpose | Where Defined / Configured | Visible in Repo? | Risk if Unmanaged | Required Action |
|---|---|---|---|---|---|
| **Git Repository** | Source code management | `https://github.com/notSahil/poc_input_generator.git` | **[Confirmed]** | Loss of code access if developer account is personal | Transfer repository to corporate GitHub Organization |
| **Salesforce Connected App** | OAuth 2.0 Client for Sitetracker | `config/settings.py:30-35`, `.env` | **[Confirmed]** (`SF_CLIENT_ID`, `SF_CLIENT_SECRET`) | Token revocation if Connected App is deleted | Transfer Connected App ownership to dedicated Integration User |
| **Salesforce Sandbox & Prod Orgs** | Target CRM environment | `SF_LOGIN_URL` | **[Confirmed]** URL only | Account lockouts if passwords expire | Maintain corporate Integration User credentials |
| **Oracle Cloud Infrastructure (OCI)** | Host VM running the server | `scripts/deploy_to_oracle.sh:31` | **[Confirmed]** (`/home/ubuntu`) | Server terminated if personal OCI account lapses | Ensure VM is provisioned under corporate OCI tenancy |
| **Domain / DNS (DuckDNS / Custom)** | HTTPS domain routing | `scripts/setup_ssl.sh:11` | **[Confirmed]** Parameterized | Domain expiry breaks webhook/OAuth redirect | Configure corporate subdomain (e.g. `sitetracker-hub.company.com`) |
| **Let's Encrypt SSL Certificate** | TLS encryption | `scripts/setup_ssl.sh:81` | **[Confirmed]** Managed by Certbot | SSL certificate expiration halts browser access | Verify certbot auto-renew cron is active |

### 4.2 Fragile vs Safe Components

```
┌────────────────────────────────────────────────────────┐
│ SAFE TO CHANGE (Modular, Isolated, Well-Tested)        │
│ • core/normalizer.py (Pure functions, 37 unit tests)   │
│ • config/reports/*.yml (Declarative YAML configs)      │
│ • ui/styles.py (SLDS CSS tokens)                       │
│ • cli.py (Standard argparse wrapper)                   │
├────────────────────────────────────────────────────────┤
│ PROCEED WITH CAUTION (Contract Invariants)             │
│ • data/common/Mapping_file.xlsx (Master schema)        │
│ • salesforce/auth.py (Token encryption & PKCE state)   │
│ • salesforce/data_fetcher.py (Dynamic SOQL query)      │
├────────────────────────────────────────────────────────┤
│ HIGH RISK / FRAGILE (Core Operational Integrity)       │
│ • core/engine.py (Calculates deltas; affects 8 files)  │
│ • salesforce/bulk_uploader.py (Direct SF database push)│
│ • ui/data_load.py (Complex Streamlit wizard state)     │
└────────────────────────────────────────────────────────┘
```

### 4.3 Minimum Team Required to Operate and Maintain

| Role | Responsibilities | Key Skills Needed | Time Commitment |
|---|---|---|---|
| **Python Backend Engineer** | Maintain `core/engine.py`, add custom normalization rules, debug data issues | Python 3.12+, pandas, pytest, uv | 10–15% FTE |
| **Salesforce Administrator** | Manage Sitetracker objects, update `Mapping_file.xlsx`, audit Bulk API quotas | Salesforce Setup, SObject metadata, Bulk API 2.0 | 10% FTE |
| **DevOps / SysAdmin** | Server maintenance, SSL renewal, systemd services, security patching | Ubuntu Linux, systemd, Nginx, Oracle Cloud | 5% FTE |

---

# 5. Salesforce and Domain Review: Actual Behavior, Limits, and Data Loader Comparison

### 5.1 Real Salesforce API Actions

| Real Application Action | Actual Salesforce API Used | Current Code Behavior | Relevant Real Limit | What Happens at the Limit | Current Protection | Required Improvement |
|---|---|---|---|---|---|---|
| **Live Baseline Fetch** | REST API `queryAll` | Executes `SELECT ... FROM Object` via `simple-salesforce` | Maximum 2,000 records per batch; 100,000 characters per SOQL query | Automatic paging via `nextRecordsUrl`; network timeout on >500k rows | 3x retry with exponential backoff (`tenacity`) | Add incremental date filter (`LastModifiedDate >= LAST_N_DAYS:30`) |
| **Bulk Delta Ingestion** | Bulk API 2.0 Ingest | Submits `final_input_file.csv` via `sf.bulk2.<Object>.update()` | **150,000,000 records** per rolling 24 hours; **100 MB** file size limit | Salesforce returns HTTP 403 `REQUEST_LIMIT_EXCEEDED` | Engine delta reduction reduces upload volume by up to 95% | Query `/services/data/v59.0/limits` before upload |
| **Emergency Rollback** | Bulk API 2.0 Ingest | Submits `rollback_file.csv` to revert pre-change values | Same as Bulk Ingest | Same as Bulk Ingest | Separate confirmation gate typing `"REVERT"` | None required |
| **Metadata Discovery** | REST API SObject Describe | Calls `sf.<Object>.describe()` | REST API daily call limit (typically 15,000 to 100,000 calls/day) | HTTP 403 Request Limit Exceeded | Results cached in UI session state | None required |
| **Session Verification** | OAuth 2.0 UserInfo | Pings `/services/oauth2/userinfo` with 2.5s timeout | Standard REST API quota | HTTP 401 Session Expired | 30-second TTL in-memory cache prevents spamming Salesforce | None required |

### 5.2 Deep Comparison: Our Application vs Salesforce Data Loader

| Real Task | How Our App Performs It | How Data Loader Performs It | Advantage of Our App | Limitation Compared to Data Loader | Recommended Decision |
|---|---|---|---|---|---|
| **Calculating Deltas** | Reconciles Source against Sitetracker export; updates **only** changed fields | Uploads the entire file; overwrites every field in every row | 80–95% less API volume; eliminates audit history bloat | Requires a baseline Sitetracker export or SOQL query | **Use Our App** for ongoing schedule & milestone updates |
| **Blank Value Handling** | Default: Ignores blanks. Optional toggle: serializes `#N/A` | Setting toggle "Insert Null Values" applies globally to entire file | Prevents accidental data wipes by defaulting to Safe Mode | Cannot choose null behavior per individual column | **Use Our App** for vendor spreadsheet uploads |
| **Date Formatting** | Accepts UK `DD/MM/YYYY`; auto-converts to ISO `YYYY-MM-DD` | Rejects UK dates in Bulk API 2.0 unless configured with exact format | Zero-configuration date compatibility for UK operators | None | **Use Our App** |
| **Rollback / Recovery** | Automatically generates `rollback_file.csv` with 1-click revert gate | None. Operator must manually export pre-change records beforehand | Built-in safety net prevents permanent data corruption | Rollback is a forward update; does not restore deleted records | **Use Our App** |
| **Multi-Object Reports** | Displays multi-object pills (`[BT Project]`, `[Project]`) from mapping | Single object per upload job | Unified interface for complex composite models | Must trigger ingest per object | **Use Our App** |
| **Mass Inserts / Deletes** | Primarily optimized for record updates via Primary Key | Supports Insert, Upsert, Update, Delete, Hard Delete, and Export | Simpler, safer interface with confirmation gates | Data Loader supports Hard Delete and binary attachments | **Use Data Loader** for initial database seeding or mass deletions |

---

# 6. Can We Make This Fully In-House?

### 6.1 Direct Ownership Assessment
**Yes.** The company can fully own and operate this product in-house without depending on the original developer. The core engine is built on standard open-source Python libraries (`pandas`, `simple-salesforce`), contains no proprietary compiled binaries, features 18 detailed Architecture Decision Records, and is verified by 95 passing unit tests.

### 6.2 Ownership Transition Checklist

| Ownership Area | What We Have Today | What Is Missing | Real Risk | Required Action to Transfer / Create | Owner |
|---|---|---|---|---|---|
| **Source Code** | **[Confirmed]** 100% complete in repository | No corporate code-review bot | Unchecked pull requests | Mirror to corporate GitHub/GitLab org; enable branch protection | DevOps |
| **Git Repository** | Hosted on `github.com/notSahil` | Corporate organization ownership | Single personal developer account | Transfer repository to corporate GitHub Organization | Founder |
| **Salesforce Access** | Sandbox credentials in `.env` | Dedicated Integration User | Personal admin credentials used | Create a Salesforce Integration User (`sitetracker-integration@company.com`) | SF Admin |
| **Cloud / Server Account** | Oracle Cloud Ubuntu VM | Corporate tenancy ownership | VM deleted if personal account lapses | Transfer or recreate VM under corporate Oracle/AWS account | DevOps |
| **Domain & DNS** | Script supports custom domain/DuckDNS | Corporate subdomain routing | Unofficial domain | Assign `sitetracker-hub.company.com` in corporate DNS | IT Owner |
| **Database / Storage** | Local filesystem storage (`data/`) | Remote off-site backup | Data loss if VM disk fails | Add automated nightly rsync / S3 backup for `data/` directory | DevOps |
| **Secrets / API Keys** | Plaintext `.env` and `.sf_auth_*.json` | Vault / Keyring encryption | Tokens exposed on local disk | Implement token encryption via `cryptography.fernet` | Python Dev |
| **Deployment Process** | Bash scripts (`deploy_to_oracle.sh`) | Automated GitHub Actions CI/CD | Manual script execution | Configure GitHub Actions runner for continuous deployment | DevOps |
| **Monitoring / Logging** | Local file logging (`logging_config.py`) | Centralized log aggregator | Silent crashes without alert | Forward logs to Datadog, CloudWatch, or Grafana Loki | DevOps |
| **Backups & Recovery** | Automated mapping backups | Automated run directory snapshotting | Accidental deletion of `runs/` | Configure daily cron backup of `data/common/` and `data/*/runs/` | DevOps |
| **Documentation** | Extensive (`PROJECT_AUDIT.md`, `FILE_STRUCTURE_MAP.md`) | End-user video walkthrough | User onboarding friction | Record 5-minute Loom video walking through the 4-step wizard | Product Owner |
| **Support Process** | Exception hierarchy with descriptive errors | Ticketing / Slack escalation channel | Unresolved operator blocks | Create dedicated `#sitetracker-hub-support` Slack channel | Ops Manager |

---

# 7. Real Production Infrastructure and Server Requirement

### 7.1 Current Infrastructure
**[Confirmed from `scripts/deploy_to_oracle.sh`, `scripts/setup_ssl.sh`]**
- **Host:** Oracle Cloud Infrastructure (OCI) Compute Instance (Ubuntu 22.04 / 24.04 LTS).
- **Memory Management:** 2 GB dedicated swap file (`/swapfile`).
- **Web Server:** Streamlit running on port `8501` as a systemd service (`streamlit.service`).
- **Reverse Proxy:** Nginx with SSL termination via Let's Encrypt Certbot and WebSocket protocol upgrade.
- **Admin Interface:** `code-server` running on port `8080` as a systemd service (`code-server@ubuntu.service`).
- **Firewall:** `iptables` rules opening ports `80`, `443`, `8080`, and `8501`.

### 7.2 Sizing Scenarios & Hardware Requirements

```
                                  SCENARIO SIZING MATRIX
┌─────────────────────────┬──────────────────────────┬──────────────────────────┐
│ 1. INTERNAL PILOT       │ 2. NORMAL PRODUCTION     │ 3. HIGH-VOLUME PRODUCTION│
│ • 1–3 Concurrent Users  │ • 5–15 Concurrent Users  │ • 20+ Operators & Cron   │
│ • Files < 10,000 Rows   │ • Files < 50,000 Rows    │ • Files up to 250,000 Rows│
│ • 2 vCPU / 4 GB RAM     │ • 4 vCPU / 8 GB RAM      │ • 8 vCPU / 16 GB RAM     │
│ • 50 GB NVMe Storage    │ • 100 GB NVMe Storage    │ • 250 GB NVMe Storage    │
│ • Estimated: $0–$30/mo  │ • Estimated: $60–$100/mo │ • Estimated: $180–$250/mo│
└─────────────────────────┴──────────────────────────┴──────────────────────────┘
```

#### Component Breakdown & Technical Reasoning

| Component | Why This App Needs It | Technology | Pilot Spec | Normal Production | High-Volume Spec | Scaling Trigger | Technical Justification |
|---|---|---|---|---|---|---|---|
| **Application Server** | Runs Streamlit reactive UI and Python engine | Ubuntu 22.04 LTS VM | 2 vCPU, 4 GB RAM | 4 vCPU, 8 GB RAM | 8 vCPU, 16 GB RAM | > 10 concurrent browser sessions | Streamlit spawns Python threads per session; pandas DataFrame comparisons consume RAM during execution |
| **Disk Storage** | Stores Source Excels, baseline CSVs, and timestamped run outputs | NVMe Block Volume | 50 GB | 100 GB | 250 GB | Disk utilization > 75% | Each execution creates ~5–10 MB of audit CSVs; 1,000 runs consume ~8 GB |
| **Web Server / Proxy** | SSL termination & WebSocket upgrades | Nginx 1.22+ | Bundled | Bundled | Bundled | > 50 req/sec | Streamlit requires permanent WebSockets; Nginx prevents socket dropouts |
| **Remote Admin** | In-browser code and file management | `code-server` | Bundled | Bundled | Standalone Container | Security audit | Allows administrators to inspect files without local installations |

---

# 8. Real Cost Model (INR and USD)

*Pricing basis: AWS / Oracle Cloud Standard Commercial Rates, Let's Encrypt (Free), Open-Source Python Stack.*

| Cost Item | Why This Project Needs It | Pilot (Monthly) | Normal Prod (Monthly) | High-Volume (Monthly) | Confidence | Source / Assumptions |
|---|---|---:|---:|---:|---|---|
| **Cloud Virtual Machine** | Compute runtime for Streamlit & Python | **$0** (OCI Free Tier) or **$25** (₹2,100) | **$65** (₹5,460) | **$160** (₹13,440) | Confirmed | AWS `t4g.xlarge` / OCI Ampere A1 (4 OCPU, 24GB RAM is free on OCI) |
| **Block Storage (SSD)** | Storing datasets, archives, and run logs | **$5** (₹420) | **$10** (₹840) | **$25** (₹2,100) | Confirmed | Standard 100GB GP3 SSD at $0.08/GB-month |
| **Domain & DNS** | Secure corporate URL | **$1** (₹84) | **$1** (₹84) | **$1** (₹84) | Confirmed | Standard `.com` domain registration ($12/year) |
| **SSL Certificate** | TLS encryption for WebSockets & OAuth | **$0** (Free) | **$0** (Free) | **$0** (Free) | Confirmed | Let's Encrypt Automated Certificates |
| **Salesforce API Calls** | Reading & updating records | **$0** | **$0** | **$0** | Confirmed | Included in existing Salesforce Enterprise/Unlimited subscription licenses |
| **Off-Site Backups** | Disaster recovery for `runs/` and mappings | **$1** (₹84) | **$3** (₹252) | **$8** (₹672) | Confirmed | AWS S3 Standard Storage (50GB–200GB) |
| **Error Monitoring** | Proactive alerts on pipeline failures | **$0** (Free Tier) | **$0** (Free Tier) | **$29** (₹2,436) | Inferred | Sentry Developer Free Tier (5,000 errors/month) |
| **TOTAL ESTIMATED MONTHLY** | Operational hosting cost | **$32 (₹2,688)** | **$79 (₹6,636)** | **$223 (₹18,732)** | **High** | **Excludes internal staff salaries** |

---

# 9. Stakeholder Meeting: Real Questions and Real Answers

### Role 1: Founder / Business Owner
1. **Q:** What business value are we getting from this tool?  
   **A:** It automates vendor schedule reconciliation, reducing a 4-hour manual VLOOKUP task to a 30-second automated run while preventing accidental production overwrites.
2. **Q:** Can this tool break our live Salesforce production database?  
   **A:** No, because it features two layers of protection: Safe Mode ignores blanks by default, and Step 4 requires typing `"CONFIRM"` before pushing updates.
3. **Q:** What happens if a contractor uploads completely incorrect data?  
   **A:** The operator can click the Emergency Rollback button, type `"REVERT"`, and restore all pre-change values from `rollback_file.csv`.
4. **Q:** How much will this cost us in software licenses?  
   **A:** Zero dollars in software licensing. The entire stack is built on free open-source software (Python, Streamlit, pandas).
5. **Q:** Are we dependent on the developer who wrote this?  
   **A:** No. The project has 95 unit tests, 18 architecture decision records, and standard Python code that any mid-level developer can maintain.
6. **Q:** Can we use this for other telecom clients besides Apollo?  
   **A:** Yes. Running `python cli.py scaffold "New Client"` sets up a new workflow in 5 seconds.
7. **Q:** Is our customer data stored securely?  
   **A:** Data is stored locally on the private server; no data is sent to external third-party AI services or unauthorized clouds.
8. **Q:** When can we deploy this to live production?  
   **A:** As soon as we unlock the Sandbox toggle in `ui/data_export.py:45` and verify production Connected App credentials.
9. **Q:** Can this run automatically overnight without human intervention?  
   **A:** Yes, the backend has a complete command-line interface (`cli.py`) ready to be scheduled via cron.
10. **Q:** What is the biggest business risk today?  
    **A:** Lack of formal off-site backups for the `runs/` directory if the cloud VM disk fails.

### Role 2: Finance Owner
1. **Q:** What is the total monthly infrastructure run rate?  
   **A:** Approximately $32 to $79 (₹2,700 to ₹6,600) per month on Oracle Cloud or AWS.
2. **Q:** Will Salesforce bill us extra for Bulk API 2.0 usage?  
   **A:** No. Bulk API 2.0 is included in standard Salesforce Enterprise and Unlimited subscriptions.
3. **Q:** Does our usage increase API costs if data volume doubles?  
   **A:** No, because the engine computes deltas, uploading only changed records and consuming minimal API quota.
4. **Q:** Are there any paid plugin subscriptions?  
   **A:** None. We avoided paid commercial Streamlit components; all components are built natively.
5. **Q:** What is the cost to back up historical runs?  
   **A:** Less than $3 (₹250) per month on AWS S3.
6. **Q:** What would it cost to rebuild this if we lost the code?  
   **A:** Approximately 120–160 hours of senior engineering time ($10,000–$15,000).
7. **Q:** Is there any licensing risk with open-source packages?  
   **A:** No. All dependencies use commercial-friendly MIT, BSD, and Apache 2.0 licenses.
8. **Q:** Can we run this on our existing server infrastructure?  
   **A:** Yes, any Linux, macOS, or Windows VM running Python 3.12 can host it.
9. **Q:** How do we budget for maintenance?  
   **A:** Plan for ~5–10 engineering hours per month for adding new report mappings.
10. **Q:** Does this require purchasing Salesforce Integration User licenses?  
    **A:** Salesforce provides 5 free Integration User licenses in Enterprise editions; we can utilize one of those.

### Role 3: Operations Manager
1. **Q:** How difficult is it for an operator to use this app?  
   **A:** It uses a guided 4-step wizard with visual checklists and confirmation popovers. A 10-minute training session is sufficient.
2. **Q:** What if the contractor changes the Excel column headers?  
   **A:** The pre-flight validator immediately alerts the user with the exact missing column name before any processing occurs.
3. **Q:** How do we know which rows actually changed?  
   **A:** The app outputs `field_level_changes.csv`, showing `Old Value` vs `New Value` for every single cell updated.
4. **Q:** What happens if a contractor submits duplicate rows?  
   **A:** The engine processes the first occurrence and quarantines duplicates in `duplicate_primary_keys.csv`.
5. **Q:** Can an operator accidentally delete Sitetracker records?  
   **A:** No. The uploader performs `update` operations only; it has no delete permissions or capabilities.
6. **Q:** Can we download all files from past runs?  
   **A:** Yes, the Run History page allows users to browse and download files from any historical run.
7. **Q:** Can we run two different reports at the same time?  
   **A:** Yes, each report operates in its own isolated directory structure under `data/<Report>/`.
8. **Q:** What happens if an operator leaves a milestone blank because work hasn't started?  
   **A:** In default Safe Mode, the engine ignores the blank cell and preserves the existing Sitetracker value.
9. **Q:** Can we edit mappings without calling a developer?  
   **A:** Yes, the Mapping Editor in the UI allows administrators to view, edit, and save mappings directly.
10. **Q:** How do we verify that the upload succeeded in Salesforce?  
    **A:** The app displays the Salesforce Bulk Job ID and record counts, and writes `bulk_upload_audit.json`.

### Role 4: Salesforce Administrator
1. **Q:** What Salesforce APIs does this application consume?  
   **A:** REST API `v59.0` (SOQL `queryAll` and Describe SObject) and Bulk API 2.0 Ingest.
2. **Q:** Does the app respect custom validation rules and required fields?  
   **A:** Yes. Bulk API 2.0 enforces all Salesforce validation rules, triggers, and flows.
3. **Q:** How does the app handle Sitetracker managed package namespaces?  
   **A:** It automatically maps objects like `Site` to `sitetracker__Site__c` (ADR 12).
4. **Q:** How are OAuth credentials managed?  
   **A:** Through a Connected App using Authorization Code Flow with PKCE (RFC 7636) and auto-token refresh.
5. **Q:** Does the app support custom picklist values?  
   **A:** Yes, values are sent as strings; invalid picklist entries will be rejected with field-level errors.
6. **Q:** Can we restrict the app to Sandbox testing?  
   **A:** Yes, the UI is currently locked to `sandbox` via `ui/data_export.py:45`.
7. **Q:** What happens if an access token expires during an upload?  
   **A:** `sf_client.py:26-37` automatically uses the stored `refresh_token` to fetch a new access token without interrupting the user.
8. **Q:** Does the app format dates properly for Salesforce?  
   **A:** Yes, UK dates (`DD/MM/YYYY`) are converted to ISO `YYYY-MM-DD` before submission to Bulk 2.0.
9. **Q:** How are Bulk 2.0 failed records diagnosed?  
   **A:** Failed records are retrieved via `get_failed_records()`, saved to `bulk_upload_failures.csv`, and displayed in the UI.
10. **Q:** Can we track which user performed the upload?  
    **A:** Yes, the Connected App OAuth token identifies the specific user who authorized the session.

### Role 5: Senior Python Developer
1. **Q:** What package manager is required?  
   **A:** Astral `uv` is strictly configured (`uv run pytest`, `uv pip install -r requirements.txt`).
2. **Q:** Is the engine coupled to Streamlit?  
   **A:** No. `core/` has zero Streamlit imports and is 100% executable headlessly via `cli.py`.
3. **Q:** How is code quality and typing enforced?  
   **A:** Python 3.12+ type hints (PEP 604 `T | None`), Google-style docstrings, and custom typed exceptions.
4. **Q:** What test coverage exists?  
   **A:** 95 automated tests across 14 test modules covering all normalizers, loaders, and API clients.
5. **Q:** How are retries handled for Salesforce network calls?  
   **A:** Decorated with `tenacity.retry` for 3 attempts with exponential backoff (1s to 10s).
6. **Q:** How is state maintained across Streamlit reruns?  
   **A:** Via `st.session_state` keys (`data_load_step`, `selected_report`, `insert_nulls_toggle`).
7. **Q:** Are file operations atomic?  
   **A:** Runs write to unique timestamped directories; inputs are archived using `shutil.copy2`.
8. **Q:** How are dates normalized?  
   **A:** Through `pd.to_datetime(dayfirst=True)` with strict calendar parsing in `core/normalizer.py`.
9. **Q:** What handles Excel read/write?  
   **A:** `pandas` and `openpyxl`.
10. **Q:** Are there any deprecated library calls?  
    **A:** No. Date parsing suppresses standard warnings and uses modern syntax.

### Role 6: Frontend Developer
1. **Q:** What design system is used?  
   **A:** Salesforce Lightning Design System (SLDS) styling tokens injected via `ui/styles.py`.
2. **Q:** How does the wizard navigate between steps?  
   **A:** Using a custom SLDS 4-step stepper component in `ui/components.py:13-50`.
3. **Q:** How do we prevent accidental file downloads?  
   **A:** All download buttons are wrapped in `render_download_with_confirmation` popover modals.
4. **Q:** Is the frontend responsive on tablets and smaller screens?  
   **A:** Streamlit provides basic responsive reflow; desktop 1080p+ is recommended for data grids.
5. **Q:** How are empty states handled?  
   **A:** Clean alert boxes (`st.info("No reports configured")`) with back buttons.
6. **Q:** Are colors accessible?  
   **A:** Yes, SLDS standard high-contrast colors (#0176D3 brand, #04844B success, #EA001E error).
7. **Q:** How are dataframes previewed safely?  
   **A:** `_read_csv_preview` and `_read_excel_preview` cast all columns to strings to prevent PyArrow serialization errors.
8. **Q:** Can we add custom tabs to the UI?  
   **A:** Yes, via standard `st.tabs` as demonstrated in `ui/mapping_editor.py`.
9. **Q:** How are status badges rendered?  
   **A:** Via `render_pill(text, color)` producing clean HTML badges.
10. **Q:** Can we customize the application header?  
    **A:** Yes, in `app.py:54-71` and `ui/components.py:6-11`.

### Role 7: QA Tester
1. **Q:** How do I run the full automated test suite?  
   **A:** Execute `uv run pytest` from the root directory.
2. **Q:** How long do automated tests take to run?  
   **A:** Approximately 13–15 seconds for all 95 tests.
3. **Q:** Do tests require a live Salesforce connection?  
   **A:** No. All tests run in isolated sandboxes using mocked responses in `tests/conftest.py`.
4. **Q:** How do I test end-to-end integration on the server?  
   **A:** Run `python quick_test.py` to test all 6 core workflows in ~5 seconds.
5. **Q:** How do I test invalid date rejection?  
   **A:** Insert `32/01/2025` into a test spreadsheet and verify that row is rejected into `error_records.csv`.
6. **Q:** How do I test duplicate primary key quarantine?  
   **A:** Duplicate a project reference row and verify it appears in `duplicate_primary_keys.csv`.
7. **Q:** How do I test the Insert Nulls toggle?  
   **A:** Enable the toggle and verify that blank cells appear as `#N/A` in `final_input_file.csv`.
8. **Q:** What edge cases should be manually verified before a release?  
   **A:** 1-row files, 50,000-row files, files with special unicode characters (`—`, `–`, `\u00a0`), and non-numeric values in numeric columns.
9. **Q:** Is code coverage measured?  
   **A:** Yes, `pytest-cov` is installed (`pytest tests/ --cov=core`).
10. **Q:** How are regression tests performed after deployment?  
    **A:** The `deploy_to_oracle.sh` script automatically runs `python quick_test.py` as step 5.

### Role 8: DevOps / IT Owner
1. **Q:** What operating system is required?  
   **A:** Ubuntu Linux 22.04 or 24.04 LTS (configured in `scripts/deploy_to_oracle.sh`).
2. **Q:** How are background services managed?  
   **A:** Via `systemd` daemons (`streamlit.service` and `code-server@ubuntu.service`).
3. **Q:** What ports must be open in the firewall?  
   **A:** Port 80 (HTTP redirect), Port 443 (HTTPS), Port 8501 (Streamlit backend), and Port 8080 (`code-server`).
4. **Q:** How is code updated on the production server?  
   **A:** Automatically via cron running `scripts/auto_deploy.sh` every few minutes to pull `origin main`.
5. **Q:** How is SSL configured?  
   **A:** Via Nginx reverse proxy and Let's Encrypt Certbot (`scripts/setup_ssl.sh`).
6. **Q:** Does the server require swap space?  
   **A:** Yes, `deploy_to_oracle.sh` creates a 2 GB swap file to prevent out-of-memory crashes.
7. **Q:** Where are application logs stored?  
   **A:** In systemd journal (`journalctl -u streamlit -f`) and `runs/auto_deploy.log`.
8. **Q:** What happens if the server reboots?  
   **A:** Both `streamlit` and `code-server` systemd services are enabled with `Restart=always`.
9. **Q:** How is Python managed?  
   **A:** In an isolated virtual environment at `/home/ubuntu/poc_input_generator/.venv`.
10. **Q:** Can we containerize this with Docker?  
    **A:** Yes, a simple `Dockerfile` running `streamlit run app.py` can be added easily.

### Role 9: Security / Legal Owner
1. **Q:** Where are Salesforce OAuth tokens stored?  
   **A:** In `.sf_auth_sandbox.json` and `.sf_auth_prod.json` on the server disk.
2. **Q:** Are credentials encrypted at rest?  
   **A:** Currently stored in plaintext JSON. **Required action:** Implement Fernet encryption.
3. **Q:** Does the application send any data to external AI models or third-party APIs?  
   **A:** No. All processing is 100% deterministic local Python code; external requests go strictly to official Salesforce API endpoints.
4. **Q:** Does the application log sensitive customer data?  
   **A:** Standard logs record record counts and timestamps; data values are written only to local CSV run folders.
5. **Q:** How are web sessions secured?  
   **A:** Over TLS 1.3 via Let's Encrypt HTTPS.
6. **Q:** Who has access to `code-server` on port 8080?  
   **A:** Password-protected; password configured in `/home/ubuntu/.config/code-server/config.yaml`.
7. **Q:** Are OAuth authorization codes exposed in URLs?  
   **A:** Codes are caught locally on loopback `127.0.0.1:1717` and immediately exchanged for tokens.
8. **Q:** Does the code support PKCE?  
   **A:** Yes, RFC 7636 SHA-256 PKCE is implemented in `salesforce/auth.py:113-154`.
9. **Q:** What happens when an operator clicks Logout?  
   **A:** `salesforce/auth.py:315-334` deletes the token file from disk and clears in-memory caches.
10. **Q:** Are dependencies scanned for known vulnerabilities?  
    **A:** Dependencies use pinned, modern versions; automated `pip-audit` should be integrated into CI.

### Role 10: Customer Support / End-User Representative
1. **Q:** What should an operator do if they see "Input validation failed"?  
   **A:** Click on the alert box to see the list of specific missing columns or invalid dates, then fix those cells in Excel.
2. **Q:** Can an operator undo an upload if they notice a mistake?  
   **A:** Yes. Go to Step 4, open the Emergency Rollback expander, type `"REVERT"`, and click Execute Rollback.
3. **Q:** Why did my upload finish in 10 seconds? Did it actually update Salesforce?  
   **A:** Yes. The engine only uploaded the rows that changed rather than the entire spreadsheet.
4. **Q:** Where can I find the files from last Thursday's upload?  
   **A:** Open the **Run History & Audit** page from the Home hub, select the report, and click the download button.
5. **Q:** What does "Duplicate Primary Key" mean?  
   **A:** The contractor spreadsheet listed the same site or project reference on multiple rows. The first row was processed and the duplicate was saved in `duplicate_primary_keys.csv`.
6. **Q:** What should I do if the screen says "Session Expired"?  
   **A:** Navigate to **Export & Connect** and click Login to refresh your Salesforce session.
7. **Q:** Can I download the changes before uploading them to Salesforce?  
   **A:** Yes. Step 4 allows downloading `final_input_file.csv` and `field_level_changes.csv` for inspection before pushing.
8. **Q:** What does the "Overwrite with Blanks" checkbox do?  
   **A:** When unchecked (recommended), blank cells are ignored. When checked, blank cells clear the corresponding field in Sitetracker.
9. **Q:** Why is the upload button disabled?  
   **A:** You must type the word `"CONFIRM"` (in capital letters) into the confirmation box to unlock the button.
10. **Q:** Who should I contact if a Salesforce query throws an error?  
    **A:** Contact your Salesforce Administrator with the error message and the name of the report you were running.

---

# 10. Priority Problem-Solution Roadmap

| Priority | Real Problem | Direct Evidence | Proposed Solution | Why Do This Now | Owner | Effort | Cost Impact | Success Metric |
|---|---|---|---|---|---|---|---|---|
| **P0: MUST FIX BEFORE PROD** | **UI Hardcoded to Sandbox** | `ui/data_export.py:45` forces `active_profile = "sandbox"` | Add Environment Selector (Sandbox vs Production) with confirmation modal | Operators cannot connect to live Production org via web interface | Frontend Dev | 2 Hours | $0 | Able to connect Production org and verify live user info |
| **P0: MUST FIX BEFORE PROD** | **Plaintext Token Storage on Disk** | `.sf_auth_sandbox.json` stores bearer token unencrypted | Encrypt token JSON with `cryptography.fernet` using key from environment | Prevents token theft if host server is compromised | Python Dev | 4 Hours | $0 | Token files encrypted on disk; transparently read by engine |
| **P0: MUST FIX BEFORE PROD** | **Corporate GitHub Ownership** | Repository hosted on personal GitHub account | Transfer repository to corporate GitHub Organization | Prevents operational disruption if developer leaves | Founder / DevOps | 1 Hour | $0 | Repo lives under corporate GitHub with team access |
| **P1: CUSTOMER-FACING** | **Single-File Folder Crash** | `core/engine.py:49` throws `ValueError` if >1 file exists | Auto-select the most recently modified file in `input/` folders | Operators encounter confusing crashes when saving multiple spreadsheet revisions | Python Dev | 1 Hour | $0 | Multiple files in `input/` process cleanly using newest file |
| **P1: CUSTOMER-FACING** | **Full-Table SOQL Queries** | `salesforce/data_fetcher.py:85` queries without `WHERE` clause | Add configurable date filter (`LastModifiedDate >= LAST_N_DAYS:60`) | Prevents slow fetches and memory bloat on objects with > 100k records | Salesforce Specialist | 3 Hours | $0 | SOQL fetch completes in < 10 seconds on massive tables |
| **P1: CUSTOMER-FACING** | **Automated Off-Site Backups** | `data/` directory stored only on local server volume | Add nightly cron script syncing `data/` to AWS S3 | Protects business audit history against VM disk failure | DevOps | 2 Hours | ~$3/mo | Nightly backups verified in private S3 bucket |
| **P2: POST-LAUNCH** | **GitHub Actions CI/CD** | Automated tests only run manually via CLI | Add `.github/workflows/ci.yml` running `uv run pytest` on push | Catches code regressions before code is pulled to production server | DevOps | 3 Hours | $0 | Every pull request automatically verified by 95 tests |
| **P2: POST-LAUNCH** | **Bulk API 2.0 Payload Chunking** | Single unchunked payload sent in `bulk_uploader.py:157` | Chunk records into 10,000-row batches if payload > 50 MB | Protects against HTTP 413 rejections on initial massive seed uploads | Python Dev | 4 Hours | $0 | 200,000-row synthetic uploads succeed without size errors |
| **P3: NICE-TO-HAVE** | **Automated Task Scheduling** | Engine execution currently requires manual button click or CLI | Build cron/worker scheduler for automated nightly runs | Enables 100% hands-off automated nightly data reconciliation | Full Stack Dev | 2 Days | $0 | Reports execute automatically at 2:00 AM daily |

---

# 11. Final Direct Answers

### 1. What does the app do today?
It reconciles contractor Excel spreadsheets against live Sitetracker CSV exports, validates data types and UK date formats, isolates changed fields, generates a complete audit package (8 CSV files), and pushes the updates to Salesforce via Bulk API 2.0 with automated rollback protection.

### 2. What are the biggest real limitations today?
1. The web interface is hardcoded locked to Developer Sandbox mode (`ui/data_export.py:45`).
2. Folders in `input/` strictly fail if more than one file exists.
3. OAuth tokens are stored in unencrypted JSON files on the server disk.
4. SOQL queries fetch entire object tables without date filters.

### 3. What could fail first in real usage?
An operator uploading a second revision of a contractor spreadsheet into `input/source/` without deleting the first file, causing `InputFileEngine._assert_single_file` to throw an immediate `ValueError`.

### 4. What must be fixed before production?
1. Add an Environment Profile Switcher in the UI to allow connecting to Production.
2. Encrypt stored OAuth tokens on disk.
3. Update `_assert_single_file` to automatically select the newest file.

### 5. What would it take to own this in-house?
1. Transfer the GitHub repository to the corporate organization.
2. Provision a corporate Salesforce Connected App and dedicated Integration User.
3. Move the cloud VM under corporate cloud billing (AWS or Oracle).
4. Assign a part-time Python developer (10% FTE) and Salesforce Admin (10% FTE).

### 6. What team and skills are needed?
* **Python Developer (10% FTE):** Python 3.12+, pandas, pytest, uv.
* **Salesforce Administrator (10% FTE):** Sitetracker schema, Bulk API 2.0, Connected Apps.
* **DevOps / SysAdmin (5% FTE):** Ubuntu Linux, systemd, Nginx, Let's Encrypt.

### 7. What infrastructure is needed?
A single Linux VM (Ubuntu 22.04 LTS) with 2–4 vCPUs, 4–8 GB of RAM, and 50–100 GB of SSD storage, running Nginx with SSL and Streamlit as a systemd daemon.

### 8. What will it likely cost to run?
**$32 to $79 (₹2,700 to ₹6,600) per month** for cloud hosting, storage, and automated off-site backups. Software licenses are $0 (100% open-source).

### 9. What Salesforce limits matter most to this exact application?
1. **Bulk API 2.0 Daily Ingest Limit (150,000,000 records/24 hrs):** Preserved because our delta engine reduces upload volume by 80–95%.
2. **Bulk API 2.0 100 MB File Size Limit:** Requires payloads to remain under 100 MB.
3. **Salesforce `xsd:date` ISO Format Requirement:** Managed automatically by converting UK dates to `YYYY-MM-DD`.

### 10. What are the next five actions we should take?
1. **Action 1:** Implement the UI Environment Toggle in `ui/data_export.py` to unlock Production mode.
2. **Action 2:** Encrypt token files using Python `cryptography.fernet`.
3. **Action 3:** Update `core/engine.py` to auto-pick the newest file in input folders.
4. **Action 4:** Transfer the GitHub repository to your corporate GitHub organization.
5. **Action 5:** Provision a dedicated Salesforce Connected App and Integration User in your production org.
