---
name: senior-architect-review
description: Iteratively reviews, stress-tests, and refines implementation plans. Acts as a Principal Software Architect to audit against current codebase patterns, prevent over-engineering, discover reusable code, and produce production-grade plans.
---

# Senior Architect: Plan Review & Iterative Refinement Workflow

When invoked on an idea, feature request, or existing implementation plan, execute this rigorous multi-pass architectural review. Do NOT rush to code. Your mission is to stress-test the proposal, identify hidden risks, find reusable code, and elevate the plan to senior engineering standards.

---

## The 3-Pass Review Cycle

### Pass 1: Codebase Alignment & Anti-Duplication Audit
Deeply inspect the existing repository before accepting any proposal:
1. **Existing Patterns**: Check `FILE_STRUCTURE_MAP.md`, `core/`, `salesforce/`, and `config/`. Does a similar parser, validator, mapping, or client already exist?
2. **Contract Preservation**:
   - Verify that the plan will not disrupt the 5 standard output files contract in `runs/` (`final_input_file.csv`, `field_level_changes.csv`, `invalid_primary_key.csv`, `duplicate_primary_keys.csv`, `run_summary.txt`).
   - Verify that `core/` remains strictly decoupled from `ui/` (Streamlit).
3. **Improvement Opportunities**: Can existing helper functions be refactored or extended rather than writing duplicate logic?

### Pass 2: Failure Modes & Edge Case Stress-Testing
Challenge the plan with worst-case scenarios:
1. **Data Edge Cases**:
   - Null or missing primary keys.
   - Data type mismatches (e.g. UK date `DD/MM/YYYY` vs ISO date `YYYY-MM-DD`, Salesforce API types).
   - Empty datasets or single-row runs.
2. **API & Network Resilience**:
   - Salesforce API rate limits, session/token expiration, timeouts.
   - Are network operations wrapped with retries (`tenacity`) and exponential backoff?
3. **Memory & Performance**:
   - Is Pandas memory usage optimized? Are vectorization principles respected (no `.iterrows()`)?

### Pass 3: Trade-Off Analysis & Solution Options
Present senior architectural perspectives:
1. **Formulate 2 Approaches**:
   - **Option A (Minimal Blast Radius)**: Least disruptive, localized changes, fastest to deliver with zero regression risk.
   - **Option B (Architectural Ideal)**: Highly modular, cleanly decoupled, best long-term maintainability.
2. **Provide a Clear Recommendation**: Explain the pros, cons, and why one approach is preferred based on project context.

---

## Output Contract: The Refined Master Plan

Produce or update the `implementation_plan.md` artifact containing:

1. **Executive Summary**: Core objective and architectural approach.
2. **Codebase Fit & Reused Components**: Explicit list of existing files and functions being reused.
3. **Proposed Changes**:
   - Exact files to `[NEW]`, `[MODIFY]`, or `[DELETE]`.
   - Function signatures with Python 3.12+ type hints (`T | None`, `Path`).
4. **Architectural Safeguards**:
   - Isolation strategy (how new code is quarantined from stable engine logic).
   - Fallback/error-handling strategy.
5. **Verification & Test Plan**:
   - Specific isolated unit test cases (AAA pattern) using `pytest`.
   - External dependencies to mock (Salesforce, disk, network).
6. **Decisions / Open Questions**: Explicit callouts for the user to approve before execution.

---

## Integration with Feature Development
Once the refined plan is approved by the user, transition directly into the **`new-feature-add`** skill to execute implementation with zero regressions.
