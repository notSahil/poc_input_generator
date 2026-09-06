---
name: uv-package-manager
description: Enforces the use of Astral's `uv` for modern, fast Python package and environment management.
---

# UV Package Manager Guidelines

When managing packages or running scripts/tests in this project:

## 1. Modern Execution via UV
- **Run commands & tests**: Always execute through `uv run` to ensure correct virtual environment context:
  - Tests: `uv run pytest`
  - CLI: `uv run python cli.py ...`
  - App: `uv run streamlit run app.py`
- Do NOT invoke raw `pip` or activate virtual environments manually unless explicitly required.

## 2. Dependency Management
- **Add packages**: Use `uv add <package>` (or `uv pip install <package>` if using a legacy venv workflow).
- **Requirements sync**: Use `uv pip sync requirements.txt` or `uv pip install -r requirements.txt`.
- **Locking/Export**: Use `uv pip compile requirements.in -o requirements.txt` when freezing deterministic dependencies.
