---
name: python-pro
description: Enforces professional Python 3.12+ best practices, strict type hinting (PEP 604), clean architecture, and modern idioms.
---

# Python 3.12+ Professional Guidelines

When this skill is activated, enforce modern Python standards across all modules:

## 1. Type Hinting & Annotations (Python 3.12+)
- Use modern union syntax `T | None` instead of `Optional[T]` (PEP 604).
- Use built-in generics directly: `list[str]`, `dict[str, Any]`, `tuple[int, ...]`, `set[str]`. Avoid importing from `typing` when built-ins are available.
- Annotate all function parameters and return types explicitly.
- Use `Path` from `pathlib` for all filesystem operations instead of `os.path`.

## 2. Style & Idioms (PEP 8+)
- Follow PEP 8 strictly: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for module constants.
- Use f-strings for all string interpolation and formatting.
- Prefer `dataclasses` or `pydantic.BaseModel` for structured data models over untyped dicts.

## 3. Clean Architecture & Separation of Concerns
- **Single Responsibility**: Keep functions small, testable, and focused on one task.
- **Strict Decoupling**: Backend logic (`core/`, `salesforce/`) must NEVER import from frontend frameworks (`streamlit`, `ui/`).
- **Defensive Invariants**: Keep public APIs backwards-compatible. When adding optional parameters, use keyword-only arguments with sensible defaults (e.g., `def run(*, new_param: str | None = None)`).

## 4. Robust Error Handling
- Never write bare `except:` or catch generic `Exception` without re-raising or logging context.
- Use or extend project-specific exceptions in `core/exceptions.py`.
- Preserve tracebacks with `raise CustomError(...) from err`.

## 5. Documentation & Intent
- Write concise Google-style docstrings for public classes and functions.
- Add explanatory comments focusing on **why** a non-obvious choice was made (e.g., edge-case mitigations, Salesforce API limits), not **what** the code does.
