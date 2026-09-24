# File Structure Map & Architecture Decisions

This is a living document. **AI AGENTS:** You must update this file whenever you add, remove, or modify the purpose of a file in the codebase.

## 1. Directory Map

### `/core` (Backend Logic & Data Processing)
- `__init__.py`: Core business logic package for the Sitetracker input generator.
- `engine.py`: The master execution script. Orchestrates loading data, validating, normalizing, and writing the 5 standard output files.
- `manual_engine.py`: Standalone, headless ad-hoc engine for Manual Dataloader mode. Computes deltas, validates data types, handles duplicates, and generates the standard 5 output files + rollback file for arbitrary Salesforce objects.
- `validator.py`: Handles checking for missing or duplicate primary keys.
- `normalizer.py`: Data cleaning and transformations.
- `mapping_loader.py`: Reads the `Mapping_file.xlsx` to determine which columns to map.
- `config_loader.py`: Loads the YAML configurations.
- `models.py`: Data classes or Pydantic models for structured data holding.
- `audit_logger.py`: Thread-safe, non-blocking per-run audit and diagnostic logger producing `audit.log` across engine execution and background uploads.
- `post_validator.py`: Headless post-update validation engine comparing expected vs live values with semantic equivalence to detect trigger mutations, stale fields, and failed null wipes.
- `job_store.py`: SQLite-backed persistent job queue with WAL mode, atomic concurrency locking, chunk checkpointing, and in-app notifications.
- `scheduler.py`: Timezone-aware schedule engine (Europe/London) supporting recurring intervals (Hourly, Daily, Weekly, Monthly) and specific one-off datetimes, automated SOQL baseline pulling, and circuit breaking.
- `notifier.py`: Multi-channel notification dispatcher (In-App, SMTP HTML email, Slack Block Kit, and MS Teams cards) with defensive error boundaries and secret masking.
- `exceptions.py`: Custom error handling.


### `/ui` (Streamlit Frontend)
- `components.py`: Shared UI components including Dataloader.io 4-stage pipeline stepper, step navigation buttons, headers, and download confirmation popovers.
- `styles.py`: Salesforce Lightning Design System (SLDS) design tokens, CSS styling, executive KPI metric cards, and status pill badges.
- `data_load.py`: Guided 4-step Dataloader.io pipeline for pre-configured reports (Source & Object ➔ Visual Field Mapping Canvas ➔ Delta & Validation Engine ➔ Review, Downloads & Bulk API Ingest).
- `manual_loader.py`: Interactive 4-step wizard for Manual Dataloader mode (1. Upload CSV/Excel ➔ 2. Select Object & Key ➔ 3. Field Mapping & Selection ➔ 4. Review, Diff & Bulk API 2.0 Upload with 1-Click Rollback).
- `run_history.py`: UI page for browsing past engine runs, viewing execution metrics, re-downloading output files, and inspecting archived inputs.
- `mapping_editor.py`: Interactive UI allowing the user to view and edit mapping rules directly in the browser with history/rollback capabilities.
- `data_export.py`: Handles environment profile switching (Sandbox vs Production), Workbench session token connection, displaying authenticated user profile details, and logout.
- `task_scheduler.py`: Interactive management dashboard for active schedules, creating one-off datetime / recurring runs, safety gates, and job queue logs.
- `live_monitor.py`: Real-time session reconnection and active ingest telemetry monitor for background upload workers.



### `/salesforce` (Integrations)
- `job_manager.py`: Background Ingest Job Manager.
- `auth.py`: Handles OAuth, multi-environment profile token caching (`.sf_auth_sandbox.json`, `.sf_auth_prod.json`), Workbench session token sanitization, and automatic token refreshing.
- `client.py`: API wrapper for making legacy REST requests to SFDC with profile awareness.
- `sf_client.py`: Bridge module providing a `simple-salesforce` client (`Salesforce`) backed by active environment profile OAuth/session tokens with automatic expiration refresh.
- `data_fetcher.py`: Builds dynamic SOQL queries from `Mapping_file.xlsx` and fetches live Sitetracker records via `simple-salesforce`.
- `adhoc_fetcher.py`: Dynamic object discovery via `describeGlobal()`, field describe inspection, and parallel URL-safe SOQL querying for arbitrary Salesforce objects.
- `post_fetcher.py`: Live post-update SOQL query engine fetching records by ID in URL-safe batches to verify DML persistence against live Salesforce state.
- `bulk_uploader.py`: Uploads `final_input_file.csv` to Salesforce via Bulk API 2.0 with payload column sanitization and record-level error logging.
- `composite_uploader.py`: High-speed REST Composite SObject Collections uploader (~15-50s) with micro-batching and in-flight progress callbacks.
- `csv_sanitizer.py`: Sanitizes raw Bulk API 2.0 failure CSVs repairing unescaped internal double quotes and multiline stack traces.
- `field_discovery.py`: Discovers Salesforce object metadata via `describe()`, filters updateable fields, and maps types to text/date/number/boolean.
- `metadata.py` & `userinfo.py`: Utilities for fetching SFDC objects.

### `/config` (Settings)
- `settings.py`: Global environment variables and paths.
- `logging_config.py`: Standardized logging setup.
- `/reports`: Contains YAML files (`apollo_10g.yml`, `master_site_listing.yml`) defining the specific Primary Keys and settings for different report types.

### `/scripts` (Utilities)
- `sync_memory.py`: sync_memory.py — Automated AI Memory & Project Structure Synchronizer
- `prune_runs.py`: Utility script to prune historical run logs, source archives, and mapping history.
- `package_clean_code.py`: Create a clean, lightweight zip archive of the codebase for company laptop deployment.
- `gen_module_index.py`: gen_module_index.py — Auto-generates .memory/MODULE_INDEX.md
- `auto_deploy.sh`: Bash script run via cron on the Oracle server to automatically pull git updates.
- `deploy_to_oracle.sh`: Bash script setting up VM, swap, iptables, uv, code-server, and systemd services on Oracle Cloud.
- `nginx_sitetracker.conf`: Hardened Nginx reverse proxy configuration with TLS 1.3, security headers, Streamlit WebSocket proxying, and 100M upload limit.
- `scaffold_report.py`: CLI generator script for scaffolding new report configs.
- `setup_ssl.sh`: Automated script for configuring Nginx reverse proxy with WebSocket support and Let's Encrypt HTTPS via DuckDNS or custom domain.
- `setup_ssl_nginx.sh`: Automated provisioning script for Nginx, Let's Encrypt SSL (`161-118-182-20.sslip.io`), and iptables firewall rules on Oracle Cloud Ubuntu VM.

### Root Files
- `cli.py`: Command-line interface for scaffolding or running reports without the UI.
- `quick_test.py`: End-to-end integration test script.
- `app.py`: Symlink or wrapper to `ui/app.py` for running Streamlit from root.

### `/.agents/skills` (AI Agent Custom Skills)
- `security-engineer/`: Enforces application security (AppSec), OWASP Top 10 defenses, credential safety, and secure coding across Python, Salesforce, and Streamlit.
- `senior-architect-review/`: Multi-pass architectural review & iterative plan refinement with anti-duplication audits.
- `new-feature-add/`: Senior developer feature workflow with isolation, ADR logging, and zero-regression tests.
- `python-pro/`: Python 3.12+ type annotations (PEP 604), pathlib, and PEP 8 standards.
- `data-engineer/`: Pandas vectorization, memory optimization, and defensive data processing.
- `unit-testing-test-generate/`: Pytest AAA pattern, fixtures, and external mock standards.
- `uv-package-manager/`: Fast package and environment management via `uv`.

---

## 2. Architecture Decision Records (ADRs)

All 39 Architecture Decision Records have been organized by domain into the [`.memory/adrs/`](.memory/adrs/) knowledge base for fast, context-efficient AI lookup:

- 🛠️ **[Infrastructure & Operations ADRs](.memory/adrs/infra_ops_adrs.md)** (ADRs 3, 28, 39)
  - Covers Oracle Cloud VM setup, code-server on port 8080, SQLite WAL persistent job store, and ADR 39 (Nginx TLS 1.3 Reverse Proxy & AppSec Skill).

- ⚙️ **[Core Engine ADRs](.memory/adrs/core_engine_adrs.md)** (ADRs 1, 9, 10, 15, 17, 23, 25, 31, 32, 33, 35, 38)
  - Covers file archiving, 8 output files, 1-click rollback, null wipe `#N/A`, multi-object handling, self-healing aliasing, ISO dates, and 2-tier post-audit.
- ☁️ **[Salesforce Integration ADRs](.memory/adrs/salesforce_adrs.md)** (ADRs 2, 4, 5, 6, 7, 8, 11, 12, 13, 14, 18, 20, 21, 22, 27, 30, 34)
  - Covers OAuth PKCE, profile caching, REST Composite key-omission, Bulk API 2.0 25-record micro-batching, governor limit protection, and token re-hydration.
- 🖥️ **[Streamlit UI & UX ADRs](.memory/adrs/ui_ux_adrs.md)** (ADRs 16, 19, 24, 26, 29, 36, 37)
  - Covers 4-step stepper wizard, manual dataloader screens, live telemetry reconnection, and run history audit replay.
- 🛠️ **[Infrastructure & Operations ADRs](.memory/adrs/infra_ops_adrs.md)** (ADRs 3, 28)
  - Covers Oracle Cloud VM setup, code-server on port 8080, and SQLite WAL persistent job store.

---

## 3. Dedicated Knowledge Modules (`.memory/`)

Before adding new features or modifying existing workflows, consult these dedicated guides:
- 🔍 **[Module & Function Directory](.memory/MODULE_INDEX.md)** — Complete catalog of all classes, functions, and lines of code.
- 📋 **[Output Contracts & Schemas](.memory/CONTRACTS.md)** — Inviolable 5 core files and complete schema specifications.
- 🔄 **[End-to-End Pipeline Flow](.memory/PIPELINE_FLOW.md)** — Ingestion, deduplication, delta comparison, and post-audit flow.
- 🖥️ **[Infrastructure & DevOps](.memory/INFRASTRUCTURE.md)** — Oracle server IP, SSH keys, ports, code-server password, and git workflows.
- ☁️ **[Salesforce Integration](.memory/SALESFORCE_INTEGRATION.md)** — Auth flows, API limits, Sitetracker conventions, and gotchas.
- 🏛️ **[System Architecture & Invariants](.memory/SYSTEM_ARCHITECTURE.md)** — Architecture rules and safe feature checklist.
