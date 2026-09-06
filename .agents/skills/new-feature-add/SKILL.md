---
name: new-feature-add
description: Senior developer workflow for adding new features safely. Enforces codebase research, architectural isolation, backwards compatibility, user review gating, self-healing documentation, and test verification.
---

# Senior Developer: New Feature Workflow

When adding any new feature, execute this disciplined, phased workflow to deliver production-grade code without regressions.

---

## Phase 1: Pre-Flight Discovery & Anti-Duplication
1. **Check Existing Logic**:
   - Inspect `FILE_STRUCTURE_MAP.md` and search `core/`, `salesforce/`, and `config/`.
   - Never reinvent existing utilities, helpers, data models, or client connections.
2. **Identify Invariants & Contracts**:
   - **Output Contract**: Never alter or break the 5 standard output files in `runs/` (`final_input_file.csv`, `field_level_changes.csv`, `invalid_primary_key.csv`, `duplicate_primary_keys.csv`, `run_summary.txt`) without explicit user instruction.
   - **Decoupling Rule**: `core/` backend logic must NEVER import from `ui/` (Streamlit). All core capabilities must be runnable headlessly via `cli.py`.

---

## Phase 2: Architectural Isolation Strategy
To guarantee existing functionality remains intact:
1. **Open-Closed Principle (OCP)**: Prefer creating new modules, helper classes, or pure functions rather than modifying battle-tested core routines.
2. **Backwards-Compatible Signatures**: When extending existing functions, add keyword-only arguments with sensible defaults (e.g., `def process(*, new_option: bool = False)`).
3. **Graceful Fault Tolerance**: Wrap non-critical supplementary features in error boundaries so that unexpected failures never halt the primary processing pipeline.

---

## Phase 3: Implementation Plan & Mandatory Review Gate
Before modifying or creating any code, prepare a concise implementation plan:
- **Summary**: What the feature does and why.
- **Files Affected**: Exact list of files to [CREATE] or [MODIFY].
- **Isolation Plan**: How the new code is decoupled from existing logic.
- **Risk Assessment**: Potential edge cases or regression vectors.
- **STOP & WAIT**: Pause and wait for explicit user approval before proceeding to implementation.

---

## Phase 4: Senior Execution Standards
Upon user approval, implement the feature applying these project standards:
- **Modern Python (3.12+)**:
  - Use `T | None` for optional types (PEP 604) and built-in generics (`list[str]`, `dict[str, Any]`).
  - Use `pathlib.Path` for file handling instead of `os.path`.
  - Use `dataclasses` or `pydantic` models for structured data.
  - Catch explicit exceptions and raise domain errors from `core/exceptions.py`.
- **Data Engineering Standards**:
  - Vectorize all Pandas transformations (`np.where`, `.apply()`, avoid `.iterrows()`).
  - Handle `NaN` / missing data defensively.
- **Meaningful Documentation**:
  - Add Google-style docstrings with types and descriptions.
  - Add inline comments only for non-obvious logic, business rules, or Salesforce API workarounds.

---

## Phase 5: Self-Healing Memory (Documentation Sync)
Keep project memory in sync immediately after code changes:
- Update `FILE_STRUCTURE_MAP.md` with any newly added, removed, or repurposed files.
- If a significant architectural trade-off was made, record an Architecture Decision Record (ADR) in `FILE_STRUCTURE_MAP.md`.
- If new packages were introduced, install with `uv add` and document in `README.md` / `requirements.txt`.

---

## Phase 6: Automated Verification & Testing
1. **Isolated Unit Tests**:
   - Write tests in `tests/` using `pytest` following the **Arrange-Act-Assert (AAA)** pattern.
   - Mock all external I/O, network requests, and Salesforce APIs (`simple-salesforce`). No real network calls in tests.
   - Cover happy paths, boundary conditions, empty datasets, and expected failure modes.
2. **Execute Test Suite**:
   - Run `uv run pytest` to confirm new tests pass AND existing tests have zero regressions.
