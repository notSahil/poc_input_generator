# System Architecture, Invariants & New Feature Checklist

> **CORE SYSTEM INVARIANTS & STANDARDS**  
> Must be read before modifying code or adding features to ensure zero breakage of existing workflows.

---

## Quick Redirection
- **Module & Function Directory** → [`.memory/MODULE_INDEX.md`](MODULE_INDEX.md)
- **Output Contracts** → [`.memory/CONTRACTS.md`](CONTRACTS.md)
- **Data Flow Logic** → [`.memory/PIPELINE_FLOW.md`](PIPELINE_FLOW.md)
- **Salesforce APIs & Auth** → [`.memory/SALESFORCE_INTEGRATION.md`](SALESFORCE_INTEGRATION.md)
- **Infrastructure & Deployment** → [`.memory/INFRASTRUCTURE.md`](INFRASTRUCTURE.md)

---

## 1. High-Level Architecture & Layer Dependency Rules

```text
┌────────────────────────────────────────────────────────┐
│                   ui/ (Streamlit Frontend)             │
│   Components, Stepper Wizards, Dashboards, Live Monitor │
└─────────────┬───────────────────────────┬──────────────┘
              │                           │
              ▼                           ▼
┌───────────────────────────┐   ┌────────────────────────┐
│ core/ (Headless Engine)   │   │ salesforce/ (Cloud)    │
│ Engine, Normalizer, Delta │   │ Auth, Composite, Bulk  │
└─────────────┬─────────────┘   └───────────┬────────────┘
              │                             │
              └──────────────┬──────────────┘
                             ▼
┌────────────────────────────────────────────────────────┐
│                config/ (Settings & Leaf YAMLs)          │
│          Global Paths, Report YAMLs, Logging Setup     │
└────────────────────────────────────────────────────────┘
```

### The Strict Decoupling Invariants
1. **`core/` MUST NEVER import from `ui/`:** The processing engine is 100% headless. It can run in CLI (`cli.py`), cron, or unit tests without Streamlit installed.
2. **`salesforce/` is standalone:** It interfaces with Salesforce APIs and imports configuration/settings, never UI components.
3. **`config/` is a leaf module:** It does not import from `core/`, `salesforce/`, or `ui/`.

---

## 2. Senior Python 3.12+ Coding Standards

1. **Modern Type Hinting (PEP 604):**
   - Use `str | None`, `int | float`, `list[str]`, `dict[str, Any]`.
   - Never use `Optional[...]` or `Union[...]` from `typing`.
2. **Path Manipulation:**
   - Always use `pathlib.Path`.
   - Never use `os.path.join`, `os.path.exists`, or raw string path concatenation.
3. **Vectorized Pandas Operations:**
   - Never iterate with `.iterrows()` or `.itertuples()`.
   - Use vectorized boolean masking, `.apply()`, or `np.where()`.
4. **Domain Exception Hierarchy:**
   - Raise custom exceptions from `core/exceptions.py` (e.g. `ValidationError`, `MappingError`, `SalesforceAuthError`), never bare `Exception`.
5. **Defensive Logging & Error Boundaries:**
   - Background tasks, logging, and notifications must never crash core data processing. Wrap auxiliary operations in safe try/except boundaries.

---

## 3. Directory Layout & Run Structure

* **Guided Reports:** `data/<Report_Name>/runs/<YYYY-MM-DD>/run_<HH-MM-SS>/`
* **Manual Dataloader:** `data/manual_runs/<Object_Name>/<YYYY-MM-DD>/run_<HH-MM-SS>/`
* **Common Assets:** `data/common/Mapping_file.xlsx`
* **Persistent Job Queue:** `data/jobs.db` (SQLite with WAL mode)
* **Saved Manual Profiles:** `data/mapping_profiles/<Profile_Name>.json`

---

## 4. 🛡️ How to Add a New Feature Safely (Step-by-Step Checklist)

Follow this 6-step checklist whenever building a new feature to ensure zero regressions:

### Step 1: Pre-Flight Check & Anti-Duplication
* [ ] Search `.memory/MODULE_INDEX.md` to see if a similar class, helper function, or module already exists.
* [ ] Check `.memory/CONTRACTS.md` to verify whether the feature touches any output file schemas.
* [ ] Review relevant ADRs in `.memory/adrs/` to understand historical constraints.

### Step 2: Architectural Isolation Strategy
* [ ] Adhere to the **Open-Closed Principle**: Extend functionality by adding new functions or backward-compatible keyword arguments (`new_param: str | None = None`).
* [ ] NEVER alter existing function signatures, return types, or default behaviors used by production reports (`Apollo 10G`, `Master Site Listing`).

### Step 3: Implement in `core/` First (Decoupled)
* [ ] Write headless business logic in `core/` or `salesforce/`.
* [ ] Keep it testable without a browser or UI session state.

### Step 4: Wire to `ui/`
* [ ] Import the backend logic into Streamlit views (`ui/data_load.py` or `ui/manual_loader.py`).
* [ ] Use SLDS tokens from `ui/styles.py` and reusable components from `ui/components.py`.

### Step 5: Test Verification
* [ ] Write new unit tests in `tests/` following Arrange-Act-Assert (AAA) pattern.
* [ ] Mock all external API or network calls.
* [ ] Run `uv run pytest tests/` — all existing and new tests **MUST PASS**.
* [ ] Run `uv run python quick_test.py` for end-to-end smoke verification.

### Step 6: Update Memory (Self-Healing Rule)
* [ ] Run `uv run python scripts/gen_module_index.py` to refresh `.memory/MODULE_INDEX.md`.
* [ ] If a major design decision was made, append an ADR to `.memory/adrs/`.
