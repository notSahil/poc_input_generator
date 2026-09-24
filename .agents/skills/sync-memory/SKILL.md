---
name: sync-memory
description: Automatically synchronizes AI memory files (.memory/MODULE_INDEX.md, FILE_STRUCTURE_MAP.md, and CONTRACTS.md) with the actual codebase state. Run whenever files or functions are added, modified, or deleted.
---

# Sync Memory Skill

Automatically updates the project's AI memory architecture and file maps to ensure future AI agents and developers have 100% accurate, up-to-date context without manual editing.

---

## When to Execute This Skill
- After adding or modifying any Python file in `core/`, `ui/`, `salesforce/`, `config/`, or `scripts/`.
- After creating a new report configuration or UI view.
- Before committing changes to Git or deploying to the Oracle server.

---

## 1. Automated Execution (Recommended)
Run the automated synchronizer:

```bash
uv run python scripts/sync_memory.py
```

This single command automatically:
1. **Rebuilds `.memory/MODULE_INDEX.md`**: Parses AST across all `.py` files, documenting every class, method, function, and docstring.
2. **Updates `FILE_STRUCTURE_MAP.md`**: Detects any newly created files on disk and automatically adds them under their proper directory section with their docstrings.
3. **Verifies Output Contracts**: Confirms that all 5 required output files in `.memory/CONTRACTS.md` remain intact.

---

## 2. Manual Checklist (If Architecture Changed)
If the changes involved high-level architectural decisions or schema updates:
1. **Did you add or change an output CSV schema?**  
   ➔ Update the corresponding table in `.memory/CONTRACTS.md`.
2. **Did you change the end-to-end data/delta flow?**  
   ➔ Update the stage description in `.memory/PIPELINE_FLOW.md`.
3. **Did you make a significant architectural design choice?**  
   ➔ Append a new numbered ADR to the appropriate file in `.memory/adrs/` (`core_engine_adrs.md`, `salesforce_adrs.md`, `ui_ux_adrs.md`, or `infra_ops_adrs.md`).
4. **Did you change server ports or deployment steps?**  
   ➔ Update `.memory/INFRASTRUCTURE.md`.

---

## 3. Verification
Confirm memory sync succeeded:
```bash
git status
```
Stage the updated memory files alongside your code changes:
```bash
git add .memory/ FILE_STRUCTURE_MAP.md
```
