# Sitetracker Data Hub & Automation Platform
## Executive Project Overview & Business Impact Document

**Document Purpose:** Presentation & Handover Document for Domain Manager & Engineering Leadership  
**Project:** `poc_input_generator` — Sitetracker Data Hub & Input File Generator  
**Author / Presenter:** Project Engineering Team  
**Date:** September 2026  
**Format:** Fully Editable Markdown with Native Mermaid Visuals (Compatible with GitHub, Notion, Obsidian, and [Mermaid Live Editor](https://mermaid.live))

---

## 1. Executive Summary: The Elevator Pitch

### What We Built
The **Sitetracker Data Hub** is an internal enterprise automation platform that automates the ingestion, validation, reconciliation, and loading of contractor spreadsheet updates into **Sitetracker (Salesforce)**.

### The Business Transformation
| Metric | Before (Manual Process) | Now (Sitetracker Data Hub) | Business Value |
|---|---|---|---|
| **Processing Time** | **2 to 4 hours** per weekly report | **Under 60 seconds** (1-Click Pipeline) | **95%+ time savings** for data operations |
| **Error Rate** | High (human copy-paste, date mismatches) | **0% programmatic errors** (pre-flight validation) | Eliminates contractor data rework |
| **Salesforce Quota Usage** | Uploaded entire 100,000-row file | Uploads **only modified rows** (e.g. 50–200 rows) | **80%–95% reduction** in API call volume |
| **Data Safety & Rollback** | **Zero rollback** (native tools have no undo) | **1-Click Automated Rollback** to pre-change state | **Zero risk** of corrupting live production |
| **Audit Compliance** | Fragmented spreadsheets in email threads | **8 standardized audit CSVs** stored per run | Full audit trail for finance & governance |

---

## 2. Before vs. Now: Process Transformation

```mermaid
flowchart TD
    subgraph BEFORE["❌ BEFORE: Legacy Manual Process (2 - 4 Hours)"]
        direction TB
        B1["1. Contractor emails Excel file"] --> B2["2. Operator downloads live data from Sitetracker manually"]
        B2 --> B3["3. Operator creates VLOOKUPs & compares rows in Excel"]
        B3 --> B4["⚠️ High Human Error: Date format errors (DD/MM/YYYY vs YYYY-MM-DD), blank cell overwrites"]
        B4 --> B5["4. Operator manually prepares upload file & opens Dataloader.io"]
        B5 --> B6["5. Uploads ALL 100k rows (slow queue, high API usage)"]
        B6 --> B7["🚨 NO ROLLBACK: If data is wrong, production is corrupted"]
    end

    subgraph NOW["✅ NOW: Sitetracker Data Hub (Under 60 Seconds)"]
        direction TB
        N1["1. Drop contractor Excel into Data Hub"] --> N2["2. ⚡ 1-Click Live SOQL Fetch directly from Sitetracker"]
        N2 --> N3["3. Automated Normalization & Validation (UK dates, schema types, regex)"]
        N3 --> N4["4. Delta Engine isolates ONLY changed fields (e.g. 42 out of 1,500 rows)"]
        N4 --> N5["5. Generates 8-file audit package (including automatic rollback backup)"]
        N5 --> N6["6. 🚀 1-Click Bulk API 2.0 Ingest (safe, validated, type-to-confirm)"]
        N6 --> N7["🛡️ 1-Click Emergency Rollback: Revert to original state anytime"]
    end

    style BEFORE fill:#FFF5F5,stroke:#E53E3E,stroke-width:2px;
    style NOW fill:#F0FFF4,stroke:#38A169,stroke-width:2px;
```

---

## 3. Detailed "Before vs. Now" Comparison

### The Legacy Workflow (What We Did Before)
1. **Email-Based Receipt:** Contractors sent weekly Excel workbooks (`.xlsx`) containing 1,500 to 100,000 project milestones over email.
2. **Manual Salesforce Report Export:** An operator logged into Sitetracker, navigated to Salesforce Reports, exported a CSV, and saved it locally.
3. **Manual Spreadsheet Comparison (VLOOKUP / Cell Diffing):**
   - The operator created manual Excel formulas to match rows by Primary Key (`Project Ref` or `Site ID`).
   - The operator scanned hundreds of columns manually to determine which dates or status fields were updated.
   - **Time Spent:** 2 to 4 hours of tedious, repetitive work per report.
4. **The Critical Pitfalls of Native Dataloader.io:**
   - **The Blank Cell Danger (Null Wipes):** In Excel, an uncompleted milestone is blank. When uploading via standard Dataloader.io, blank cells can accidentally **wipe out existing live dates** in Sitetracker.
   - **UK Date Rejections:** Sitetracker contractors use UK calendar dates (`DD/MM/YYYY`). Salesforce Bulk API strictly rejects UK formats with fatal deserialization errors.
   - **Full-File Upload Inefficiency:** Dataloader.io updates every record in the file, triggering unnecessary Salesforce Apex triggers, workflows, and cluttering the field audit history.
   - **Zero Safety Net:** Once an upload finishes in Dataloader.io, there is **no undo button**.

---

### The Modern Workflow (How the Sitetracker Data Hub Works Now)

```mermaid
graph LR
    A["Contractor Excel<br/>(Source File)"] --> C["Sitetracker Data Hub<br/>(Engine)"]
    B["Live Sitetracker<br/>(SOQL API)"] --> C
    
    C --> D["Validation & Normalization<br/>• UK Dates to ISO<br/>• Type verification<br/>• Primary Key regex"]
    D --> E["Delta Calculation<br/>• Isolate modified fields<br/>• Skip unedited rows"]
    
    E --> F["8 Audit CSV Files<br/>• Final upload file<br/>• Rollback backup<br/>• Field change log"]
    F --> G["Salesforce Bulk API 2.0<br/>• Type 'CONFIRM'<br/>• Push to Sitetracker"]
    F --> H["Emergency Rollback<br/>• Type 'REVERT'<br/>• 1-Click Undo"]

    style C fill:#EBF8FF,stroke:#3182CE,stroke-width:2px;
    style E fill:#FEFCBF,stroke:#D69E2E,stroke-width:2px;
    style G fill:#C6F6D5,stroke:#38A169,stroke-width:2px;
    style H fill:#FED7D7,stroke:#E53E3E,stroke-width:2px;
```

---

## 4. End-to-End Operational Pipeline: 4 Guided Steps

The application organizes the entire operational lifecycle into a 4-step guided wizard based on the **Salesforce Lightning Design System (SLDS)**:

```mermaid
stateDiagram-v2
    [*] --> Step1_Source_and_SOQL
    Step1_Source_and_SOQL: Step 1. Ingest & Live Fetch
    note right of Step1_Source_and_SOQL
      • Discovers source Excel file
      • ⚡ 1-Click Live SOQL Fetch pulls real-time
        records directly from Sitetracker
    end note

    Step1_Source_and_SOQL --> Step2_Mapping_and_Validation
    Step2_Mapping_and_Validation: Step 2. Mapping & Pre-Flight Validation
    note right of Step2_Mapping_and_Validation
      • Aligns spreadsheet headers to Salesforce API names
      • Validates UK date formats, text lengths, & IDs
      • Displays interactive preview
    end note

    Step2_Mapping_and_Validation --> Step3_Delta_Engine
    Step3_Delta_Engine: Step 3. Delta Reconciliation
    note right of Step3_Delta_Engine
      • Compares Source vs Sitetracker
      • Calculates field-level differences
      • Creates 8 audit artifacts + Rollback file
    end note

    Step3_Delta_Engine --> Step4_Bulk_Upload
    Step4_Bulk_Upload: Step 4. Safe Push & Rollback
    note right of Step4_Bulk_Upload
      • Type 'CONFIRM' to push via Bulk API 2.0
      • Type 'REVERT' for instant 1-click rollback
    end note

    Step4_Bulk_Upload --> [*]
```

### Detailed Breakdown of Each Step:

#### Step 1: Input Discovery & 1-Click Live SOQL Fetch
- **What Happens:** Instead of manually exporting reports from Salesforce, the user selects their report model (e.g. *Apollo 10G* or *Master Site Listing*) and clicks **"⚡ 1-Click Live SOQL Fetch"**.
- **Under the Hood:** The app dynamically reads `Mapping_file.xlsx`, generates a clean SOQL query (`SELECT Id, Name, sitetracker__Status__c... FROM sitetracker__Site__c`), connects to Salesforce via `simple-salesforce`, and downloads the live baseline records in seconds.

#### Step 2: Intelligent Field Mapping & Schema Validation
- **What Happens:** The system cross-references the contractor's spreadsheet headers against Salesforce API field names.
- **Under the Hood:**
  - **Date Normalization:** UK dates (`DD/MM/YYYY`) are validated and serialized to Salesforce-compliant ISO dates (`YYYY-MM-DD`).
  - **Type Safety:** Ensures boolean fields (`TRUE/FALSE`), numbers, and text lengths conform to Salesforce object metadata.
  - **Duplicate Detection:** Flag duplicate Primary Keys automatically before touching Salesforce.

#### Step 3: High-Performance Delta Engine
- **What Happens:** The user clicks **"Run Delta Engine"**. In 3–5 seconds, the engine compares thousands of rows.
- **Under the Hood:**
  - Performs an in-memory hash join indexed on the Primary Key (`Project Ref` or `Site ID`).
  - Evaluates row-level and field-level changes.
  - Generates an executive KPI dashboard:
    - **Total Records:** `1,500`
    - **Unchanged Records (Skipped):** `1,458`
    - **Updated Records (Delta):** `42`
    - **Validation Errors:** `0`
  - Generates the complete **8-File Audit Package**.

#### Step 4: Secure Bulk API 2.0 Push & Emergency Rollback Gate
- **What Happens:** The operator reviews the delta preview. To prevent accidental clicks, the operator types `"CONFIRM"` to unlock the upload button.
- **Under the Hood:**
  - Submits an asynchronous Bulk API 2.0 Ingest job directly to Salesforce.
  - Monitors job status until complete and logs success/failure records.
  - **Emergency Rollback Net:** If an operator ever makes an error, they expand the Rollback panel, type `"REVERT"`, and push `rollback_file.csv` to instantly restore pre-change values.

---

## 5. The 8 Audit Artifacts Generated Per Run

Every single pipeline execution automatically produces a timestamped, immutable folder (`data/<Report>/runs/YYYY-MM-DD/run_HH-MM-SS/`) containing 8 auditable files:

| File Name | Purpose | What It Contains |
|---|---|---|
| 📄 **`final_input_file.csv`** | **Production Ingest Payload** | Only the records and fields that actually changed, formatted with Salesforce API names. |
| 🛡️ **`rollback_file.csv`** | **Disaster Recovery Backup** | The pre-change baseline values for every record being updated. Enables 1-click revert. |
| 🔍 **`field_level_changes.csv`** | **Granular Change Log** | Every individual field change showing: `Record ID`, `Field Name`, `Old Value`, `New Value`. |
| ✅ **`success_records.csv`** | **Clean Records** | Records that passed all schema and validation rules. |
| ❌ **`error_records.csv`** | **Invalid Records** | Records rejected during validation (e.g. malformed date or missing primary key). |
| ⏭️ **`skipped_records.csv`** | **Unchanged Records** | Records checked where contractor data was identical to Sitetracker. |
| 📋 **`validation_report.csv`** | **Field Health Report** | Detailed diagnostics on column types, missing fields, or pattern mismatches. |
| 📊 **`run_summary.txt`** | **Executive Summary** | Timestamped run statistics, processing duration, operator details, and row counts. |

---

## 6. Key Business Problems Solved

```mermaid
graph TD
    subgraph P1["1. The 'Blank Cell' Overwrite Trap"]
        direction LR
        PA["Contractor leaves cell blank"] --> PB["Native Tool: Erases live Salesforce data!"]
        PA --> PC["Our Hub: Safe Mode ignores blanks unless explicit #N/A"]
    end

    subgraph P2["2. UK Date Serialization Failures"]
        direction LR
        PD["UK Spreadsheet: 14/08/2026"] --> PE["Salesforce API: Fatal Error (Invalid Date)"]
        PD --> PF["Our Hub: Automatically converted to 2026-08-14"]
    end

    subgraph P3["3. Trigger & Flow Overload"]
        direction LR
        PG["Upload all 100k rows"] --> PH["Fires 100k Apex triggers & exhausts limits"]
        PG --> PI["Our Hub: Uploads only 42 changed rows (99% reduction)"]
    end

    style PB fill:#FFD2D2,stroke:#D32F2F;
    style PC fill:#D4EDDA,stroke:#28A745;
    style PE fill:#FFD2D2,stroke:#D32F2F;
    style PF fill:#D4EDDA,stroke:#28A745;
    style PH fill:#FFD2D2,stroke:#D32F2F;
    style PI fill:#D4EDDA,stroke:#28A745;
```

1. **Elimination of Null Wipes:** Contractors often submit spreadsheets with empty cells for milestones that haven't occurred yet. Our app defaults to "Safe Mode," ignoring blanks so live Sitetracker dates are never accidentally wiped out.
2. **Automated UK Date Normalization:** Eliminates the #1 cause of upload failures by converting UK calendar formats (`DD/MM/YYYY`) into Salesforce ISO `YYYY-MM-DD` behind the scenes.
3. **Trigger & Audit History Protection:** Updating unchanged rows causes unnecessary Apex triggers, workflow rules, and clutter in Salesforce Field History Tracking. By isolating only true deltas, we preserve Salesforce API limits and trigger budgets.
4. **Guaranteed Rollback Safety:** Native tools offer zero rollback. Our platform creates a point-in-time snapshot before every upload, providing peace of mind to operations.

---

## 7. Technical Architecture: Decoupled & Enterprise-Ready

```mermaid
flowchart TB
    subgraph UI_LAYER["Presentation Layer (Streamlit 1.52)"]
        U1["Guided 4-Step Pipeline (ui/data_load.py)"]
        U2["Interactive Mapping Editor (ui/mapping_editor.py)"]
        U3["Historical Audit Browser (ui/run_history.py)"]
        U4["Export & Connect (ui/data_export.py)"]
    end

    subgraph CORE_ENGINE["Core Python Engine (Decoupled, Headless)"]
        C1["Delta Calculation Engine (core/engine.py)"]
        C2["Data Normalizer (core/normalizer.py)"]
        C3["Schema Validator (core/validator.py)"]
        C4["Mapping Loader & Config (core/mapping_loader.py)"]
    end

    subgraph INTEGRATION_LAYER["Salesforce Integration Layer"]
        S1["Dynamic SOQL Query Fetcher (salesforce/data_fetcher.py)"]
        S2["Bulk API 2.0 Ingest & Rollback (salesforce/bulk_uploader.py)"]
        S3["OAuth 2.0 PKCE & Session Auth (salesforce/auth.py)"]
        S4["Metadata Field Auto-Discovery (salesforce/field_discovery.py)"]
    end

    UI_LAYER --> CORE_ENGINE
    CORE_ENGINE --> INTEGRATION_LAYER
    INTEGRATION_LAYER <--> SF_CLOUD["☁️ Salesforce / Sitetracker Cloud"]

    style UI_LAYER fill:#E3F2FD,stroke:#1976D2;
    style CORE_ENGINE fill:#FFF9C4,stroke:#FBC02D;
    style INTEGRATION_LAYER fill:#E8F5E9,stroke:#388E3C;
    style SF_CLOUD fill:#EDE7F6,stroke:#512DA8;
```

> [!NOTE]
> **Key Architectural Strength:**  
> The core engine ([`core/`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/core/)) and Salesforce integrations ([`salesforce/`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/salesforce/)) have **zero Streamlit dependencies**. They can be run via CLI (`python cli.py run --report "Apollo 10G"`), scheduled via automated cron jobs, or wrapped in FastAPI/React in the future.

---

## 8. Automated Test & Code Quality Metrics

- **Total Automated Tests:** **95 tests** passing in **13.78 seconds** ([`tests/`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/tests/)).
- **Test Coverage:** Unit and integration tests covering the Delta Engine, UK date parsing, normalizers, mapping editor, SOQL query builder, and Bulk API 2.0 handlers.
- **Python Version:** Python 3.12+ modern strict typing, `pathlib.Path` cross-platform support (runs identically on Windows PowerShell, Mac, and Linux).

---

## 9. How to Edit and Use These Diagrams

All diagrams in this document are authored using **Mermaid**, the international standard for markdown diagrams.

### How to Modify or Export Diagrams:
1. **Copy the code block:** Copy any ` ```mermaid ... ``` ` block from this document.
2. **Open Mermaid Live Editor:** Go to **[https://mermaid.live](https://mermaid.live)**.
3. **Paste & Edit:** Paste the code into the left pane. You can edit text, add steps, or change colors in real time.
4. **Export for Slides:** Click **Actions** $\rightarrow$ **Download PNG** or **SVG** to insert high-resolution graphics directly into Microsoft PowerPoint, Word, or Google Slides!
