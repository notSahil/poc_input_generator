# End-to-End Data Pipeline Flow & Conventions

> **ARCHITECTURE REFERENCE**  
> Explains how raw data is ingested, transformed, compared, validated, uploaded to Salesforce, and verified via post-upload ground truth reconciliation.

---

## Quick Redirection
- **Output File Schemas** → [`.memory/CONTRACTS.md`](CONTRACTS.md)
- **Module Index** → [`.memory/MODULE_INDEX.md`](MODULE_INDEX.md)
- **Salesforce APIs & Auth** → [`.memory/SALESFORCE_INTEGRATION.md`](SALESFORCE_INTEGRATION.md)
- **Infrastructure & Ports** → [`.memory/INFRASTRUCTURE.md`](INFRASTRUCTURE.md)

---

## 1. High-Level Flow Diagram

```text
[ Raw Contractor Spreadsheet ] (Excel .xlsx / CSV)
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 1: INGESTION & SELF-HEALING COLUMN RESOLUTION     │
│ • Unicode cleaning (\ufeff, \u00a0, BOM characters)    │
│ • Universal resolver: Source Header ➔ ST Label ➔ API   │
│ • Leading zero preservation on text/ID columns         │
└────────────────────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 2: MAPPING RESOLUTION & SCHEMA BINDING           │
│ • Guided Mode: data/common/Mapping_file.xlsx           │
│ • Manual Mode: Schema auto-discovery & JSON profiles   │
│ • Multi-object schema resolution (e.g. Apollo 10G)     │
└────────────────────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 3: DELTA ENGINE & ROW VALIDATION                 │
│ • Primary Key validation (regex, no spaces, not null)  │
│ • Smart Deduplication ("First Occurrence Wins")        │
│ • Ambiguous Salesforce match quarantine                │
│ • UK Date format validation (DD/MM/YYYY vs ISO)        │
│ • Smart blank handling: Preserve vs. '#N/A' Null Wipe  │
│ • Semantic equivalence (DataNormalizer.comparable_text)│
└────────────────────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 4: ARTIFACT GENERATION & COMPILATION             │
│ • Compile final_input_file.csv (records with deltas)   │
│ • Compile rollback_file.csv (pre-change values)        │
│ • Compile diagnostic CSVs (skipped, errors, diffs)     │
│ • Write audit.log checkpoints                          │
└────────────────────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 5: CLOUD INGESTION (SALESFORCE)                  │
│ • Detached background thread with SQLite locking       │
│ • Engine A: REST Composite SObjects (15-rec batches)   │
│ • Engine B: Bulk API 2.0 (25-rec micro-batches)        │
│ • Key-Omission Safeguard (prevent accidental wipes)    │
│ • Real-time progress telemetry in ingest_progress.json │
└────────────────────────────────────────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────────────────────┐
│ STAGE 6: 2-TIER POST-UPDATE RECONCILIATION             │
│ • Tier 1: Transaction CSVs (success/error records)     │
│ • Tier 2: Live SOQL ground truth query via post_fetcher│
│ • Reconcile expected vs. live values via post_validator│
│ • Detect Apex trigger mutations & unmodified fields    │
└────────────────────────────────────────────────────────┘
```

---

## 2. Guided vs. Manual Flow Comparison

| Feature | Guided Flow (`ui/data_load.py`) | Manual Flow (`ui/manual_loader.py`) |
|---|---|---|
| **Primary Use Case** | Regular, pre-configured contractor reports | Ad-hoc one-off loads into any Salesforce object |
| **Engine Used** | `core/engine.py` (`InputFileEngine`) | `core/manual_engine.py` (`ManualLoadEngine`) |
| **Mapping Source** | Master Excel (`data/common/Mapping_file.xlsx`) | Dynamic `describe()` + `data/mapping_profiles/*.json` |
| **Multi-Object** | Supported (e.g. Apollo 10G updates BT Project + Project) | Single target object per upload |
| **Baseline Data** | Offline Sitetracker CSV export or Live SOQL fetch | Live on-the-fly SOQL query (`WHERE <PK> IN (...)`) |
| **Output Directory** | `data/<Report>/runs/<Date>/run_<Time>/` | `data/manual_runs/<Object>/<Date>/<run_Time>/` |
| **1-Click Rollback** | Generated automatically in run directory | Generated automatically in run directory |

---

## 3. Core Delta Engine Rules & Business Logic

### 3.1 Primary Key & Deduplication Rules
1. **Primary Key Validation:**
   - Must not be null, empty, or whitespace.
   - Must match alphanumeric format: `^[A-Za-z0-9_-]+$`.
   - Rows failing PK validation are copied directly to `invalid_primary_key.csv` without mutation.
2. **"First Occurrence Wins" Deduplication:**
   - If a source file has multiple rows with the exact same Primary Key, the **first row** encountered is processed.
   - All subsequent occurrences are quarantined into `duplicate_primary_keys.csv` with metadata recording the `First_Occurrence_Row`.
3. **Ambiguous Salesforce Match Detection (Manual Mode):**
   - If a live SOQL query finds more than one record in Salesforce sharing the same business key, the system halts and quarantines those records to `duplicate_salesforce_records.csv` to prevent updating the wrong cloud record.

---

### 3.2 Smart Blank Handling & `#N/A` Null Wipes
Salesforce APIs handle blanks very differently from regular databases. To prevent data loss:
- **Default Mode (`insert_nulls=False`):**
  - If a source spreadsheet cell is empty/blank, the field is **skipped**. Existing Salesforce values are kept untouched.
- **Explicit Null Wipe Mode (`insert_nulls=True` / UI Toggle On):**
  - If a user explicitly turns on "Overwrite with Blanks", empty cells are formatted as the literal string **`#N/A`**.
  - In Bulk API 2.0, Salesforce treats `#N/A` as a command to clear the field.
  - In REST Composite API, empty fields are omitted from the JSON dictionary to prevent wiping live data unless explicitly marked `#N/A` or during a rollback.

---

### 3.3 Date Normalization & Strict UK/ISO Handling
- Source contractor files use **UK date format (`DD/MM/YYYY`)**.
- Sitetracker baseline exports often use **ISO date format (`YYYY-MM-DD`)**.
- **Normalization Rule:**
  - `DataNormalizer.comparable_text()` converts both sides into a unified representation before comparison to eliminate false-positive deltas.
  - If an ISO date (`^\d{4}-\d{2}-\d{2}`) is encountered, it is parsed with `dayfirst=False`.
  - When writing `final_input_file.csv`, dates are kept in human UK format (`DD/MM/YYYY`).
  - At upload time, `bulk_uploader.py` converts UK dates into ISO `YYYY-MM-DD` (`xsd:date`).

---

## 4. Background Job Concurrency & Disconnect Safety

1. **Detached Worker (`salesforce/job_manager.py`):**
   - When an upload starts, it spawns a Python daemon thread on the server.
   - If the operator closes the browser tab, locks their phone, or disconnects VPN, the upload continues running on the Oracle server.
2. **Persistent Concurrency Lock (`core/job_store.py`):**
   - Concurrency lock key: `(report_name, profile, target_object)`.
   - Stored in SQLite database (`data/jobs.db`) with WAL mode.
   - Prevents two operators from accidentally running concurrent uploads against the same target object.
3. **Telemetry & Re-Attachment (`ui/live_monitor.py`):**
   - Background worker writes progress every chunk to `ingest_progress.json`.
   - Operators can refresh or re-open the UI and click `[Re-attach to Live Progress]` to resume monitoring live metrics.

---

## 5. Post-Update Ground Truth Reconciliation (2-Tier Audit)

1. **Tier 1 (Transaction-Level):**
   - Captures immediate API response from Salesforce.
   - Generates `salesforce_success_records.csv` and `salesforce_error_records.csv`.
2. **Tier 2 (Deep Ground-Truth Verification):**
   - Calls `salesforce/post_fetcher.py` to query live Salesforce records via SOQL (`SELECT Id, ... FROM SObject WHERE Id IN (...)`).
   - Compares live values against expected upload values using `core/post_validator.py`.
   - Flags discrepancies:
     - `TRIGGER_MUTATION`: Sitetracker Apex triggers changed a value after upload.
     - `UNMODIFIED_STALE`: Value was not updated by Salesforce (e.g. locked field).
     - `NULL_WIPE_FAILED`: `#N/A` was sent, but field still holds data.
