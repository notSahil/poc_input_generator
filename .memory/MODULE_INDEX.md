# Project Module & Function Index

> **Auto-Generated Reference Document**  
> *Update this file anytime after adding or changing code by running:*  
> `uv run python scripts/gen_module_index.py`

This catalog gives any AI agent or developer an instant, searchable reference of **all existing classes, functions, and files** to prevent reinventing existing logic and ensure anti-duplication.

---

## Quick Navigation
- [Root Files](#root-files)
- [core/ (Backend Logic)](#core--backend-logic-data-processing-validation-normalization)
- [ui/ (Streamlit Frontend)](#ui--streamlit-frontend-views-stepper-wizards-dashboard-components)
- [salesforce/ (Cloud & APIs)](#salesforce--salesforce-oauth-rest-composite-bulk-api-20-soql)
- [config/ (Settings & YAMLs)](#config--application-configuration-logging-report-yamls)
- [scripts/ (DevOps & Tools)](#scripts--deployment-maintenance-and-code-generation-scripts)

---

## Root Files
| File | Lines | Description | Key Exports / Functions |
|---|---|---|---|
| [`app.py`](app.py) | 269 | Main Streamlit Application Router with Salesforce Lightning Design System styling. | `go()`, `render_home()` |
| [`cli.py`](cli.py) | 245 | CLI entry point for the Sitetracker Input File Generator. | `cmd_run()`, `cmd_validate()`, `cmd_list_reports()`, `cmd_scaffold()`, `cmd_scheduler()` |
| [`quick_test.py`](quick_test.py) | 195 | End-to-end quick test runner for Sitetracker Input File Generator. | `print_header()`, `test_normalizer()`, `test_apollo_10g_run()`, `test_master_site_listing_run()`, `test_config_and_mapping()` |

## core/ — Backend Logic, Data Processing, Validation, Normalization

| File | Lines | Summary / Role | Classes | Exported Functions / Helpers |
|---|---|---|---|---|
| [`__init__.py`](core/__init__.py) | 22 | Core business logic package for the Sitetracker input generator. | — | — |
| [`audit_logger.py`](core/audit_logger.py) | 255 | Simple, reliable per-run audit and diagnostic logger. | **`AuditLogger`** | `mask_secrets()`, `resolve_user_identity()` |
| [`config_loader.py`](core/config_loader.py) | 87 | YAML Configuration loader and report registry. | **`YamlConfigLoader`** | — |
| [`engine.py`](core/engine.py) | 705 | Core Input File Engine for computing delta changes between source and sitetracker. | **`InputFileEngine`** | — |
| [`exceptions.py`](core/exceptions.py) | 69 | Custom exception hierarchy for the input generator. | **`InputGeneratorError`**<br>**`ConfigNotFoundError`**<br>**`ConfigInvalidError`**<br>**`MappingError`**<br>**`MappingFileNotFoundError`**<br>**`PrimaryKeyNotFoundError`**<br>**`ValidationError`**<br>**`EngineSkipError`**<br>**`SalesforceAuthError`**<br>**`SalesforceAPIError`**<br>**`SchedulerError`**<br>**`ConcurrencyLockError`** | — |
| [`job_store.py`](core/job_store.py) | 686 | SQLite-backed persistent job queue, atomic locking, checkpointing, and notifications. | — | `get_db()`, `init_db()`, `create_job()`, `mark_job_running()`, `update_job_progress()`, `complete_job()` |
| [`manual_engine.py`](core/manual_engine.py) | 1173 | Ad-Hoc / Manual Dataloader Processing Engine. | **`OperationType`**<br>**`MappingStatus`**<br>**`AdhocFieldMapping`**<br>**`MappingProfile`**<br>**`AdhocEngineConfig`**<br>**`AdhocRunResult`**<br>**`ManualLoadEngine`** | `normalize_header()`, `detect_target_object()`, `suggest_field_mappings()`, `resolve_pk_from_mapping()`, `detect_source_duplicates()`, `detect_salesforce_duplicates()` |
| [`mapping_editor.py`](core/mapping_editor.py) | 168 | Read, edit, and save the mapping file with version history. | **`MappingEditor`** | — |
| [`mapping_loader.py`](core/mapping_loader.py) | 142 | Mapping configuration loader for Excel mapping files. | **`MappingLoader`** | — |
| [`models.py`](core/models.py) | 117 | Data models for engine inputs and outputs. | **`FieldChange`**<br>**`RunResult`**<br>**`ValidationResult`**<br>**`ReportInfo`**<br>**`PostUpdateFieldResult`**<br>**`PostUpdateValidationResult`** | — |
| [`normalizer.py`](core/normalizer.py) | 242 | Data normalization utilities. | **`DataNormalizer`** | — |
| [`notifier.py`](core/notifier.py) | 335 | Multi-channel notification dispatcher (In-App, Email/SMTP, Slack, MS Teams). | — | `build_notification_payload()`, `dispatch_notification()` |
| [`post_validator.py`](core/post_validator.py) | 285 | Post-Update Live Salesforce Validation & Discrepancy Reconciliation Engine. | — | `evaluate_field_match()`, `reconcile_post_update()` |
| [`scheduler.py`](core/scheduler.py) | 477 | Core Task Scheduler Engine. | — | `get_uk_timezone()`, `get_current_uk_time()`, `compute_next_run()`, `execute_scheduled_task()`, `run_due_tasks()`, `start_scheduler_loop()` |
| [`validator.py`](core/validator.py) | 174 | Input validation pipeline. Runs before the engine to catch problems early. | **`InputValidator`** | — |

### Detailed Class & Method Directory (`core/`)

- **`AuditLogger`** in [`audit_logger.py`](core/audit_logger.py): Thread-safe, non-blocking per-run audit logger.
  - *Methods:* `_format_details()`, `_write_line()`, `start_run()`, `info()`, `warning()`, `error()`
- **`YamlConfigLoader`** in [`config_loader.py`](core/config_loader.py): No docstring
  - *Methods:* `load()`, `list_reports()`
- **`InputFileEngine`** in [`engine.py`](core/engine.py): No docstring
  - *Methods:* `_assert_single_file()`, `run()`
- **`InputGeneratorError`** in [`exceptions.py`](core/exceptions.py): Base exception for all application errors.
  - *Methods:* Data-only / Attributes
- **`ConfigNotFoundError`** in [`exceptions.py`](core/exceptions.py): YAML config file for a report was not found.
  - *Methods:* Data-only / Attributes
- **`ConfigInvalidError`** in [`exceptions.py`](core/exceptions.py): YAML config file is malformed or missing required fields.
  - *Methods:* Data-only / Attributes
- **`MappingError`** in [`exceptions.py`](core/exceptions.py): Error in the mapping file (missing columns, bad data, etc.).
  - *Methods:* Data-only / Attributes
- **`MappingFileNotFoundError`** in [`exceptions.py`](core/exceptions.py): The Excel mapping file does not exist.
  - *Methods:* Data-only / Attributes
- **`PrimaryKeyNotFoundError`** in [`exceptions.py`](core/exceptions.py): No primary key mapping was found for the selected object and no match key was specified.
  - *Methods:* Data-only / Attributes
- **`ValidationError`** in [`exceptions.py`](core/exceptions.py): Input data failed validation checks.
  - *Methods:* Data-only / Attributes
- **`EngineSkipError`** in [`exceptions.py`](core/exceptions.py): Engine skipped execution because input files are missing.
  - *Methods:* Data-only / Attributes
- **`SalesforceAuthError`** in [`exceptions.py`](core/exceptions.py): Salesforce authentication failed or token is expired.
  - *Methods:* Data-only / Attributes
- **`SalesforceAPIError`** in [`exceptions.py`](core/exceptions.py): Salesforce API returned an error response.
  - *Methods:* Data-only / Attributes
- **`SchedulerError`** in [`exceptions.py`](core/exceptions.py): Error during task scheduler configuration or execution.
  - *Methods:* Data-only / Attributes
- **`ConcurrencyLockError`** in [`exceptions.py`](core/exceptions.py): A conflicting job is already executing for the same resource.
  - *Methods:* Data-only / Attributes
- **`OperationType`** in [`manual_engine.py`](core/manual_engine.py): No docstring
  - *Methods:* Data-only / Attributes
- **`MappingStatus`** in [`manual_engine.py`](core/manual_engine.py): No docstring
  - *Methods:* Data-only / Attributes
- **`AdhocFieldMapping`** in [`manual_engine.py`](core/manual_engine.py): Individual field mapping definition.
  - *Methods:* Data-only / Attributes
- **`MappingProfile`** in [`manual_engine.py`](core/manual_engine.py): Persistent mapping configuration for the Dataloader flow.
  - *Methods:* `to_dict()`, `from_dict()`, `save_to_file()`, `load_from_file()`, `check_compatibility()`
- **`AdhocEngineConfig`** in [`manual_engine.py`](core/manual_engine.py): Configuration for an ad-hoc dataloader execution.
  - *Methods:* Data-only / Attributes
- **`AdhocRunResult`** in [`manual_engine.py`](core/manual_engine.py): Summary and artifact locations for an ad-hoc run.
  - *Methods:* Data-only / Attributes
- **`ManualLoadEngine`** in [`manual_engine.py`](core/manual_engine.py): Executes delta comparisons, validates constraints, and produces
  - *Methods:* `_out()`, `run()`
- **`MappingEditor`** in [`mapping_editor.py`](core/mapping_editor.py): No docstring
  - *Methods:* `load()`, `get_reports()`, `get_rows_for_report()`, `add_row()`, `add_rows()`, `replace_from_upload()`
- **`MappingLoader`** in [`mapping_loader.py`](core/mapping_loader.py): No docstring
  - *Methods:* `load()`, `primary_keys()`, `all_primary_keys()`, `objects()`, `field_mapping()`
- **`FieldChange`** in [`models.py`](core/models.py): A single field-level change detected between source and sitetracker.
  - *Methods:* Data-only / Attributes
- **`RunResult`** in [`models.py`](core/models.py): Structured result of an engine run.
  - *Methods:* `has_warnings()`, `has_errors()`
- **`ValidationResult`** in [`models.py`](core/models.py): Result of input validation checks.
  - *Methods:* Data-only / Attributes
- **`ReportInfo`** in [`models.py`](core/models.py): Metadata about an available report.
  - *Methods:* Data-only / Attributes
- **`PostUpdateFieldResult`** in [`models.py`](core/models.py): Detailed result of a single field comparison after Salesforce update.
  - *Methods:* Data-only / Attributes
- **`PostUpdateValidationResult`** in [`models.py`](core/models.py): Aggregated results of post-update verification across all records and fields.
  - *Methods:* Data-only / Attributes
- **`DataNormalizer`** in [`normalizer.py`](core/normalizer.py): No docstring
  - *Methods:* `normalize_columns()`, `resolve_source_column()`, `normalize_value()`, `comparable_text()`, `normalize_date_uk()`, `valid_project_ref()`
- **`InputValidator`** in [`validator.py`](core/validator.py): No docstring
  - *Methods:* `validate_all()`, `_check_directories()`, `_check_files()`, `_get_single_file()`

## ui/ — Streamlit Frontend Views, Stepper Wizards, Dashboard Components

| File | Lines | Summary / Role | Classes | Exported Functions / Helpers |
|---|---|---|---|---|
| [`__init__.py`](ui/__init__.py) | 0 | — | — | — |
| [`components.py`](ui/components.py) | 361 | Shared UI components used across pages with Salesforce Lightning Design System styling. | — | `render_header()`, `render_pipeline_stepper()`, `render_step_navigation()`, `render_footer()`, `render_back_button()`, `render_download_with_confirmation()` |
| [`data_export.py`](ui/data_export.py) | 36 | Streamlit UI page for Salesforce Data Export. | — | `render()` |
| [`data_load.py`](ui/data_load.py) | 1617 | Streamlit UI page for Data Load / Input File Generation with Dataloader.io guided pipeline. | — | `render()` |
| [`live_monitor.py`](ui/live_monitor.py) | 262 | Universal Live Ingest Telemetry Monitor. | — | `render()` |
| [`login.py`](ui/login.py) | 311 | Dedicated Enterprise Login Gateway for Sitetracker Data Hub with Salesforce Lightning Design System styling. | — | `render_login_gateway()` |
| [`manual_loader.py`](ui/manual_loader.py) | 1268 | Manual / Ad-Hoc Dataloader UI Module (Dataloader.io Mode). | — | `render()` |
| [`mapping_editor.py`](ui/mapping_editor.py) | 365 | Streamlit UI page for the Interactive Mapping Editor. | — | `render()` |
| [`run_history.py`](ui/run_history.py) | 1038 | Streamlit UI page for Historical Runs and Audit Log. | — | `parse_run_summary()`, `scan_guided_runs()`, `scan_manual_runs()`, `scan_all_runs()`, `render()` |
| [`styles.py`](ui/styles.py) | 419 | Salesforce Lightning Design System (SLDS) and Dataloader.io styling tokens for Streamlit. | — | `apply_slds_theme()`, `render_kpi_card()`, `render_pill()` |
| [`task_scheduler.py`](ui/task_scheduler.py) | 333 | Streamlit UI page for Task Scheduler and Automated Ingest Operations. | — | `render()` |

## salesforce/ — Salesforce OAuth, REST Composite, Bulk API 2.0, SOQL

| File | Lines | Summary / Role | Classes | Exported Functions / Helpers |
|---|---|---|---|---|
| [`__init__.py`](salesforce/__init__.py) | 1 | Salesforce integration package. | — | — |
| [`adhoc_fetcher.py`](salesforce/adhoc_fetcher.py) | 286 | Salesforce Ad-Hoc Metadata and Live Data Fetcher. | — | `chunk_identifiers()`, `fetch_all_objects()`, `fetch_object_fields()`, `is_valid_salesforce_id()`, `fetch_adhoc_live_data()` |
| [`auth.py`](salesforce/auth.py) | 745 | Salesforce OAuth: token exchange, local callback server, token persistence. | **`OAuthHandler`** | `get_active_profile()`, `set_active_profile()`, `get_token_file()`, `sanitize_session_token()`, `get_profile_credentials()`, `is_oauth_configured()` |
| [`bulk_uploader.py`](salesforce/bulk_uploader.py) | 542 | Salesforce Bulk API 2.0 uploader for pushing delta input files directly to Sitetracker. | **`BulkUploadResult`** | `clean_payload_for_salesforce()`, `push_delta_to_sitetracker()`, `push_multi_object_deltas_to_sitetracker()` |
| [`client.py`](salesforce/client.py) | 71 | Salesforce REST API client. | **`SalesforceClient`** | — |
| [`composite_uploader.py`](salesforce/composite_uploader.py) | 340 | Salesforce REST Composite SObject Collections Uploader. | — | `push_delta_via_composite()` |
| [`csv_sanitizer.py`](salesforce/csv_sanitizer.py) | 188 | Pre-sanitization utilities for Salesforce Bulk API 2.0 failure CSV responses. | — | `is_valid_salesforce_id()`, `sanitize_failure_csv()` |
| [`data_fetcher.py`](salesforce/data_fetcher.py) | 405 | Fetch live Sitetracker data using SOQL queries generated from field mappings. | — | `normalize_salesforce_object_name()`, `build_soql_for_report()`, `fetch_sitetracker_data()` |
| [`field_discovery.py`](salesforce/field_discovery.py) | 78 | Discover available fields on a Salesforce object using describe metadata. | — | `map_sf_type()`, `discover_object_fields()` |
| [`job_manager.py`](salesforce/job_manager.py) | 624 | Background Ingest Job Manager. | — | `simplify_salesforce_error()`, `get_progress_file()`, `get_job_progress()`, `clear_job_progress()`, `is_job_active()`, `start_background_ingest()` |
| [`metadata.py`](salesforce/metadata.py) | 12 | Salesforce metadata operations. | — | `list_objects()` |
| [`post_fetcher.py`](salesforce/post_fetcher.py) | 85 | Live Post-Update Salesforce Data Fetcher. | — | `fetch_live_records_by_ids()` |
| [`sf_client.py`](salesforce/sf_client.py) | 52 | Bridge: Create a simple-salesforce Salesforce instance from stored OAuth token. | — | `get_sf_connection()` |
| [`userinfo.py`](salesforce/userinfo.py) | 83 | — | — | `get_user_info()`, `get_extended_user_and_org_details()` |

### Detailed Class & Method Directory (`salesforce/`)

- **`OAuthHandler`** in [`auth.py`](salesforce/auth.py): No docstring
  - *Methods:* `do_GET()`, `log_message()`
- **`BulkUploadResult`** in [`bulk_uploader.py`](salesforce/bulk_uploader.py): Structured result of a Bulk API 2.0 upload job.
  - *Methods:* Data-only / Attributes
- **`SalesforceClient`** in [`client.py`](salesforce/client.py): No docstring
  - *Methods:* `_refresh_and_update()`, `get()`

## config/ — Application Configuration, Logging, Report YAMLs

| File | Lines | Summary / Role | Classes | Exported Functions / Helpers |
|---|---|---|---|---|
| [`__init__.py`](config/__init__.py) | 1 | Configuration package. | — | — |
| [`logging_config.py`](config/logging_config.py) | 31 | Logging configuration for the application. | — | `setup_logging()` |
| [`settings.py`](config/settings.py) | 102 | Central application settings. Single source of truth for all config. | — | `reload_settings()` |

## scripts/ — Deployment, Maintenance, and Code Generation Scripts

| File | Lines | Summary / Role | Classes | Exported Functions / Helpers |
|---|---|---|---|---|
| [`gen_module_index.py`](scripts/gen_module_index.py) | 173 | gen_module_index.py — Auto-generates .memory/MODULE_INDEX.md | — | `parse_python_file()`, `generate_index()`, `main()` |
| [`package_clean_code.py`](scripts/package_clean_code.py) | 104 | Create a clean, lightweight zip archive of the codebase for company laptop deployment. | — | `create_clean_zip()` |
| [`prune_runs.py`](scripts/prune_runs.py) | 248 | Utility script to prune historical run logs, source archives, and mapping history. | — | `prune_guided_runs()`, `prune_manual_runs()`, `prune_mapping_history()`, `vacuum_job_store()`, `prune_all()` |
| [`scaffold_report.py`](scripts/scaffold_report.py) | 95 | Scaffold a new report with YAML configuration and standard data directory structure. | — | `scaffold()`, `main()` |
| [`sync_memory.py`](scripts/sync_memory.py) | 165 | sync_memory.py — Automated AI Memory & Project Structure Synchronizer | — | `run_module_index_generator()`, `get_first_sentence_docstring()`, `sync_file_structure_map()`, `verify_output_contracts()`, `main()` |

