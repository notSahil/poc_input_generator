# POC Input Generator - Project Memory & Architecture

This document serves as the master reference guide for the `poc_input_generator` project. It defines the system architecture, the required data formats (inputs), the mapping logic, and strictly defines the output file formats so the system remains consistent.

## 1. System Architecture

The application is modularized into four distinct layers:

*   **`core/`**: The processing engine. Contains the logic for loading configurations (`config_loader.py`), loading mappings (`mapping_loader.py`), normalizing data (`normalizer.py`), validating data (`validator.py`), and the main execution engine (`engine.py`).
*   **`ui/`**: The frontend layer built with Streamlit. Contains the web app (`app.py`), the interactive mapping editor (`mapping_editor.py`), and the data export/download views.
*   **`salesforce/`**: Integration layer. Handles authentication (`auth.py`), API client requests (`client.py`), fetching metadata (`metadata.py`), and fetching user info (`userinfo.py`).
*   **`config/`**: Configuration layer. Contains YAML files defining each report type (e.g., `apollo_10g.yml`, `master_site_listing.yml`) and environment settings.

---

## 2. Input Data Formats

The system requires three specific inputs to generate an output.

### A. Source Data File
*   **Format:** Excel (`.xlsx`) or CSV (`.csv`).
*   **Purpose:** The raw data provided by external teams or vendors.
*   **Structure:** Can contain any number of columns. However, it **must** contain a "Primary Key" column (defined in the YAML config, e.g., `Site ID` or `Project ID`) to uniquely identify every row.

### B. Sitetracker Current Data File
*   **Format:** CSV (`.csv`).
*   **Purpose:** The current state of the database downloaded directly from Sitetracker. Used to compare against the Source Data to determine what actually changed.
*   **Structure:** Must contain the exact column names expected by the Sitetracker system (the "Target Columns" in the mapping). Must also contain the Primary Key column.

### C. Mapping File
*   **Format:** Excel (`Mapping_file.xlsx`).
*   **Purpose:** The rules engine dictating how Source columns translate to Sitetracker columns.
*   **Structure:** 
    *   `Source Column`: The name of the column in the Source Data.
    *   `Target Column`: The exact API name / Column name required by Sitetracker.
    *   `Default Value`: (Optional) A hardcoded value to apply if the source is blank.

---

## 3. Output Data Formats (The Resulting Files)

When the engine runs, it strictly generates **five (5)** consistent files inside a timestamped folder (e.g., `data/<Report_Name>/runs/YYYY-MM-DD/run_HH-MM-SS/`). 

Here is the exact format and content expectation for each file:

### 1. `final_input_file.csv` (The Main Output)
*   **Format:** CSV
*   **What data is in it:** This is the clean, validated data ready to be uploaded to Sitetracker. It contains **only** the rows that passed validation.
*   **Columns:** Contains the Primary Key and the mapped `Target Columns` defined in the `Mapping_file.xlsx`. 
*   **Consistency Rule:** No unmapped source columns will appear here. Blank rows are removed. 

### 2. `field_level_changes.csv` (Audit Log)
*   **Format:** CSV
*   **What data is in it:** A highly granular tracking of exactly what changed between the Source Data and the Sitetracker Current Data.
*   **Columns:** 
    *   `Primary_Key`: The ID of the record.
    *   `Column`: The specific target field name that changed.
    *   `Old_Value`: The value as it existed in the Sitetracker Current Data file.
    *   `New_Value`: The new mapped value from the Source Data file.
*   **Consistency Rule:** If a value didn't change (Old_Value == New_Value), it is NOT recorded in this file.

### 3. `invalid_primary_key.csv` (Errors)
*   **Format:** CSV
*   **What data is in it:** A collection of failed rows from the Source Data where the Primary Key was entirely missing, null, or blank. 
*   **Columns:** An exact copy of all the original columns from the Source Data file.
*   **Consistency Rule:** These rows are dropped and do NOT make it into the `final_input_file.csv`. This file is used by users to fix their raw data.

### 4. `duplicate_primary_keys.csv` (Errors)
*   **Format:** CSV
*   **What data is in it:** A collection of failed rows from the Source Data where the same Primary Key appeared more than once.
*   **Columns:** An exact copy of all the original columns from the Source Data file.
*   **Consistency Rule:** Sitetracker cannot accept duplicate IDs. All instances of the duplicate row are quarantined here and excluded from the `final_input_file.csv`.

### 5. `run_summary.txt` (Execution Summary)
*   **Format:** Plain Text (`.txt`)
*   **What data is in it:** A high-level, human-readable summary of the job metrics.
*   **Content Structure:**
    *   Timestamp of the run.
    *   Total records processed.
    *   Total successful records (rows in final_input_file).
    *   Total errors (sum of invalid + duplicate primary keys).
    *   Total field-level changes detected.
*   **Consistency Rule:** This file serves as the quick dashboard snapshot for a specific run.
