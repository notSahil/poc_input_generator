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
- `mapping_editor.py`: Interactive UI allowing the user to view and edit mapping rules directly in the browser with history/rollback capabilities.
- `data_export.py`: Handles downloading the output files and interfacing with Salesforce.

### `/salesforce` (Integrations)
- `auth.py`: Handles OAuth and manual token authentication with Salesforce.
- `client.py`: API wrapper for making requests to SFDC.
- `metadata.py` & `userinfo.py`: Utilities for fetching SFDC objects.

### `/config` (Settings)
- `settings.py`: Global environment variables and paths.
- `logging_config.py`: Standardized logging setup.
- `/reports`: Contains YAML files (`apollo_10g.yml`, `master_site_listing.yml`) defining the specific Primary Keys and settings for different report types.

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
