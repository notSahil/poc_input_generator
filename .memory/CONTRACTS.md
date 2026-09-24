# Output File Contracts & Data Schemas

> **CRITICAL CONTRACT — READ BEFORE TOUCHING OUTPUT CODE**  
> Any code modification that changes column names, formats, or file names of these artifacts will break downstream integrations, Sitetracker dataloads, or UI downloads. Follow the specifications below strictly.

---

## Quick Redirection
- **Data Flow Logic** → [`.memory/PIPELINE_FLOW.md`](PIPELINE_FLOW.md)
- **Module & Function Directory** → [`.memory/MODULE_INDEX.md`](MODULE_INDEX.md)
- **System Invariants** → [`.memory/SYSTEM_ARCHITECTURE.md`](SYSTEM_ARCHITECTURE.md)
- **Engine ADRs** → [`.memory/adrs/core_engine_adrs.md`](adrs/core_engine_adrs.md)

---

## 1. The 5 Inviolable Output Files (Per Run Contract)

Every execution of `core/engine.py` (Guided Pipeline) and `core/manual_engine.py` (Manual Dataloader) **MUST** produce these 5 core files in the active run directory. Do NOT alter these file names or core structures without explicit user instruction.

### 1.1 `final_input_file.csv`
* **Purpose:** The exact payload file ready for Sitetracker / Salesforce Bulk API 2.0 or REST Composite ingest. Contains ONLY records that have at least one modified field.
* **Location:** `runs/<date>/run_<time>/final_input_file.csv` or `data/manual_runs/<obj>/<date>/run_<time>/final_input_file.csv`
* **Rules:**
  - Header Row 1: Contains `Id`, `<Primary_Key>`, and all mapped target columns.
  - No blank rows. Unmodified rows are excluded.
  - Dates must be UK formatted (`DD/MM/YYYY`) in CSV, converted to ISO (`YYYY-MM-DD`) only at API submission time.
  - Cleared/wiped fields contain `#N/A` if `insert_nulls=True`.
* **Schema:**
  | Column Name | Type | Constraints | Description |
  |---|---|---|---|
  | `Id` | String | Exactly 15 or 18 chars, non-null | Salesforce unique Record ID |
  | `<Primary_Key>` | String | Non-null, valid format | Unique business key (e.g. `Project Reference`, `Site ID`) |
  | `<Mapped_Target_Fields>` | String/Num/Date | Varies | All other mapped Sitetracker/Salesforce columns |

---

### 1.2 `field_level_changes.csv`
* **Purpose:** Cell-by-cell audit trail showing every exact change detected between the baseline and source input.
* **Location:** `runs/.../field_level_changes.csv`
* **Schema:**
  | Column Name | Type | Example | Description |
  |---|---|---|---|
  | `Project Reference` / `Primary_Key` | String | `GL0042` | The primary business key |
  | `Id` | String (18-char) | `a0i8d000004XYZwAAG` | Target Salesforce record ID |
  | `Source Column` / `Source_Column` | String | `Order Placed Actual` | Column name in source spreadsheet |
  | `Sitetracker Column` / `Field_Name`| String | `Order Placed (Actual)` | Field name in Sitetracker |
  | `API Field` / `Salesforce_Field` | String | `Order_Placed_Actual__c` | Salesforce API field name |
  | `Old Value` / `Old_Value` | String | `10/09/2026` | Baseline value before upload |
  | `New Value` / `New_Value` | String | `25/09/2026` | Formatted new value to set |

---

### 1.3 `invalid_primary_key.csv`
* **Purpose:** Quarantines rows where the Primary Key was empty, null, whitespace, or invalid format (contains spaces or illegal characters).
* **Location:** `runs/.../invalid_primary_key.csv`
* **Schema:** Exact copy of original raw source spreadsheet rows that failed the primary key validation check, with no column alterations.

---

### 1.4 `duplicate_primary_keys.csv`
* **Purpose:** Quarantines duplicate occurrences of the same Primary Key in the source file. The system enforces **"First Occurrence Wins"** (Row N processed, Rows N+1 quarantined).
* **Location:** `runs/.../duplicate_primary_keys.csv`
* **Schema:**
  | Column Name | Type | Example | Description |
  |---|---|---|---|
  | `Row_Number` | Integer | `45` | Row number in raw spreadsheet |
  | `Primary_Key` | String | `GL0005` | The duplicated match key value |
  | `First_Occurrence_Row` | Integer | `3` | Original row that was processed |
  | `Status` | String | `DUPLICATE_SKIPPED` | Processing status flag |
  | `Reason` | String | `Duplicate of Primary Key 'GL0005' (Row 3 processed)` | Human explanation |
  | *`<Source Columns...>`* | Any | *(Raw values)* | Full copy of the raw source spreadsheet row |

---

### 1.5 `run_summary.txt`
* **Purpose:** Human-readable text report containing summary statistics of the run for executive sign-off or email attachments.
* **Location:** `runs/.../run_summary.txt`
* **Contents:**
  ```text
  =======================================================
  SITETRACKER INPUT FILE GENERATOR - RUN SUMMARY
  =======================================================
  Timestamp: 2026-09-24 16:30:00
  Report: Apollo 10G
  Mode: Guided Pipeline
  
  [DATA METRICS]
  Total Source Rows Processed: 531
  Valid Primary Keys: 531
  Invalid Primary Keys: 0
  Duplicate Primary Keys: 0
  
  [DELTA RESULTS]
  Records With Changes: 42
  Records Skipped (Unchanged): 489
  Total Field-Level Changes: 84
  
  [STATUS]
  Status: SUCCESS
  Output Files Generated: 5 Core Files + Rollback
  =======================================================
  ```

---

## 2. Disaster Recovery & Rollback Files

### 2.1 `rollback_file.csv`
* **Purpose:** Instant 1-click restore payload. Contains exact pre-change baseline values for every record that was modified.
* **Location:** `runs/.../rollback_file.csv`
* **Format:** Identical structure to `final_input_file.csv`, but populated with `Old Value`. If a field was previously blank/null, it is populated with `#N/A` so Salesforce clears it upon revert.
* **Per-Object Payloads (Multi-Object Reports):**
  - `rollback_file_<Object_Name>.csv` (e.g. `rollback_file_BT_Project.csv`, `rollback_file_Project.csv`)
  - Ensures clean separation so fields are never submitted to the wrong Salesforce object.

---

## 3. Dataloader.io Supplementary & Diagnostic Files

These files provide Dataloader.io parity for validation and filtering:

| Filename | Purpose | Key Columns |
|---|---|---|
| `success_records.csv` | Summary of rows with changes ready for upload | `Primary_Key`, `Id`, `Fields_Changed`, `Change_Summary` |
| `error_records.csv` | Quarantined rows failing type/date validation | `Row_Number`, `Primary_Key`, `Error_Code`, `Error_Message`, `Error_Field`, `sf__Error` |
| `skipped_records.csv` | Valid rows skipped because old == new or PK not found | `Row_Number`, `Primary_Key`, `Id`, `Reason` |
| `validation_report.csv` | Master row-by-row audit matrix | `Row_Number`, `Primary_Key`, `PK_Valid`, `Date_Fields_Valid`, `Data_Types_OK`, `Has_Changes`, `Final_Status` |

---

## 4. Salesforce Cloud Ingestion Results

Generated during/after REST Composite or Bulk API 2.0 execution:

### 4.1 `salesforce_success_records.csv`
* **Purpose:** Cloud transaction receipt showing records confirmed updated by Salesforce.
* **Columns:** `Record_Id` (single unified 18-char ID), `Primary_Key`, `Status` (`SUCCESS`), plus the updated fields.

### 4.2 `salesforce_error_records.csv`
* **Purpose:** Cloud transaction error log showing records rejected by Salesforce validation rules or triggers.
* **Columns:** `Record_Id`, `Primary_Key`, `Simplified_Cause` (human-friendly message), `sf__Error` (raw Salesforce error string), `sf__Fields`.

### 4.3 `bulk_upload_failures.csv`
* **Purpose:** Combined Bulk API 2.0 raw failure dump sanitized by `salesforce/csv_sanitizer.py`.

---

## 5. Post-Update Verification & Discrepancy Reports

Generated by `core/post_validator.py` following live SOQL query against Salesforce:

### 5.1 `post_update_validation_report.csv`
* **Purpose:** Deep ground-truth audit comparing expected values vs. live Salesforce database state.
* **Columns:**
  - `Record_Id`: Salesforce 18-character ID
  - `Primary_Key`: Source match key
  - `Object`: Target SObject API name
  - `API_Field`: Salesforce field API name
  - `Field_Label`: Human column label
  - `Old_Value`: Value before upload
  - `Expected_Value`: Value sent in payload
  - `Live_Salesforce_Value`: Live value queried back from Salesforce
  - `Status`: Outcome classification:
    - `VERIFIED_MATCH`: Live value exactly matches expected value.
    - `TRIGGER_MUTATION`: Apex trigger / workflow altered value after save.
    - `UNMODIFIED_STALE`: Value did not update; remains at old value.
    - `NULL_WIPE_FAILED`: `#N/A` was sent, but field was not cleared.
    - `RECORD_NOT_FOUND`: Record could not be retrieved via SOQL.
  - `Notes`: Forensic diagnostic message explaining discrepancy.

### 5.2 `post_update_discrepancies.csv`
* **Purpose:** Filtered subset of `post_update_validation_report.csv` containing **ONLY rows where `Status != 'VERIFIED_MATCH'`**. Ideal for immediate triage.

---

## 6. Operational Telemetry & State Files

| Filename | Format | Purpose | Managed By |
|---|---|---|---|
| `audit.log` | Plain text (bracket tags) | Thread-safe, non-blocking execution log with secret masking | `core/audit_logger.py` |
| `ingest_progress.json` | JSON | Live background upload progress (`active_chunk`, `total_chunks`, `records_completed`) | `salesforce/job_manager.py` |
| `run_metadata.json` | JSON | Run summary metadata for UI Run History browser | `core/manual_engine.py` / `core/engine.py` |
