# ⚡ Sitetracker Data Hub & Input File Generator

Production-ready internal tool to generate Sitetracker/Salesforce update files by comparing source data against current exports, editing field mappings interactively, and managing Salesforce OAuth operations.

---

## 🏗 Features

- **🚀 Delta Calculation Engine**: Detects record-level & field-level changes between source Excel files and current Sitetracker CSV exports.
- **📝 Interactive Mapping Editor**: Edit mappings directly in the Streamlit UI with automatic version history and rollback support.
- **🔍 Automated Validation**: Verifies headers, data types, primary keys, and date formats before execution.
- **🧩 1-Command Extensibility**: Easily scaffold and configure new report workflows via `python cli.py scaffold <Name>`.
- **🔐 Salesforce OAuth Integration**: Connect to Salesforce instances, explore object metadata, and extract data.
- **🧪 Comprehensive Test Suite**: 38+ unit and integration tests with high code coverage.

---

## 📁 Project Structure

```
├── app.py                          # Streamlit entry point (router)
├── cli.py                          # CLI entry point (run, validate, list, scaffold)
├── requirements.txt                # Python dependencies
├── .env.example                    # Template for Salesforce OAuth credentials
│
├── config/
│   ├── settings.py                 # Central configuration and paths
│   ├── logging_config.py           # Structured logging
│   └── reports/                    # Per-report YAML configurations
│       ├── _template.yml           # Template for new reports
│       ├── apollo_10g.yml
│       └── master_site_listing.yml
│
├── core/                           # Business logic library (pure Python)
│   ├── engine.py                   # InputFileEngine (delta processing)
│   ├── validator.py                # InputValidator (pre-run validation)
│   ├── mapping_loader.py           # MappingLoader (Excel reader)
│   ├── mapping_editor.py           # MappingEditor (interactive editor + backups)
│   ├── normalizer.py               # DataNormalizer (dates, text, columns)
│   ├── config_loader.py            # YamlConfigLoader & report registry
│   ├── models.py                   # Dataclasses (RunResult, ReportInfo, etc.)
│   └── exceptions.py               # Typed exception hierarchy
│
├── salesforce/                     # Salesforce integration package
│   ├── auth.py                     # OAuth flow, token store & expiry check
│   ├── client.py                   # Salesforce REST API client
│   ├── metadata.py                 # Object metadata explorer
│   └── userinfo.py                 # Connected user info
│
├── ui/                             # Streamlit UI modules
│   ├── components.py               # Shared header/footer/navigation
│   ├── data_load.py                # Data Load & generation page
│   ├── mapping_editor.py           # Interactive mapping editor page
│   └── data_export.py              # Salesforce export & OAuth page
│
├── data/                           # Data directory (ignored in git)
│   ├── common/
│   │   ├── Mapping_file.xlsx       # Field mapping definitions
│   │   └── mapping_history/        # Versioned backups from Mapping Editor
│   ├── Apollo_10G/
│   │   ├── input/source/           # Source Excel file
│   │   ├── input/sitetracker/      # Sitetracker CSV export
│   │   ├── runs/                   # Timestamped output runs
│   │   └── archive/                # Archived input files
│   └── Master_Site_Listing/
│       └── ...
│
└── tests/                          # Automated test suite
    ├── conftest.py                 # Shared pytest fixtures & test sandbox
    ├── test_engine.py              # End-to-end integration test
    ├── test_normalizer.py          # Data normalizer unit tests
    ├── test_mapping_loader.py      # Mapping loader tests
    ├── test_mapping_editor.py      # Mapping editor tests
    ├── test_validator.py           # Pre-run validation tests
    └── test_config_loader.py       # Config loader & registry tests
```

---

## 🚀 Quick Start

### 1. Installation
```bash
# Setup virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Launch the Web UI
```bash
streamlit run app.py
```
Open [http://localhost:8501](http://localhost:8501) in your browser.

### 3. CLI Commands

```bash
# List all configured reports and file readiness
python cli.py list-reports

# Validate input files without executing
python cli.py validate --report "Apollo 10G"

# Run the delta engine
python cli.py run --report "Apollo 10G"

# Scaffold a new report workflow
python cli.py scaffold "Substation Upgrades"
```

### 4. Run Automated Tests
```bash
pytest tests/ -v --cov=core
```
