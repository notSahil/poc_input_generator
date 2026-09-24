#!/usr/bin/env python3
"""
gen_module_index.py — Auto-generates .memory/MODULE_INDEX.md

Scans all Python files across core/, ui/, salesforce/, config/, scripts/, and root,
parsing AST to extract module docstrings, classes, methods, and functions.
Produces a clean, searchable index for AI agents and developers.
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_ROOT / ".memory"
TARGET_FILE = MEMORY_DIR / "MODULE_INDEX.md"

SCAN_DIRS = [
    ("core", "core/ — Backend Logic, Data Processing, Validation, Normalization"),
    ("ui", "ui/ — Streamlit Frontend Views, Stepper Wizards, Dashboard Components"),
    ("salesforce", "salesforce/ — Salesforce OAuth, REST Composite, Bulk API 2.0, SOQL"),
    ("config", "config/ — Application Configuration, Logging, Report YAMLs"),
    ("scripts", "scripts/ — Deployment, Maintenance, and Code Generation Scripts"),
]

ROOT_FILES = ["app.py", "cli.py", "quick_test.py"]


def parse_python_file(file_path: Path) -> dict[str, any]:
    """Parse a Python file using AST to extract metadata."""
    try:
        content = file_path.read_text(encoding="utf-8")
        line_count = len(content.splitlines())
    except Exception:
        return {"lines": 0, "doc": "", "classes": [], "functions": []}

    try:
        tree = ast.parse(content, filename=str(file_path))
    except Exception:
        return {"lines": line_count, "doc": "(Syntax error in AST parsing)", "classes": [], "functions": []}

    module_doc = ast.get_docstring(tree) or ""
    # Truncate doc to first sentence or first 120 chars
    if module_doc:
        module_doc = module_doc.strip().split("\n")[0].strip()

    classes: list[dict[str, any]] = []
    functions: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_methods = [
                m.name for m in node.body
                if isinstance(m, ast.FunctionDef) and not m.name.startswith("__")
            ]
            class_doc = ast.get_docstring(node) or ""
            if class_doc:
                class_doc = class_doc.strip().split("\n")[0].strip()
            classes.append({
                "name": node.name,
                "doc": class_doc,
                "methods": class_methods[:6],  # Top methods
            })
        elif isinstance(node, ast.FunctionDef):
            functions.append(node.name)

    return {
        "lines": line_count,
        "doc": module_doc,
        "classes": classes,
        "functions": functions,
    }


def generate_index() -> str:
    """Generate markdown index content."""
    lines: list[str] = [
        "# Project Module & Function Index",
        "",
        "> **Auto-Generated Reference Document**  ",
        "> *Update this file anytime after adding or changing code by running:*  ",
        "> `uv run python scripts/gen_module_index.py`",
        "",
        "This catalog gives any AI agent or developer an instant, searchable reference of **all existing classes, functions, and files** to prevent reinventing existing logic and ensure anti-duplication.",
        "",
        "---",
        "",
        "## Quick Navigation",
        "- [Root Files](#root-files)",
        "- [core/ (Backend Logic)](#core--backend-logic-data-processing-validation-normalization)",
        "- [ui/ (Streamlit Frontend)](#ui--streamlit-frontend-views-stepper-wizards-dashboard-components)",
        "- [salesforce/ (Cloud & APIs)](#salesforce--salesforce-oauth-rest-composite-bulk-api-20-soql)",
        "- [config/ (Settings & YAMLs)](#config--application-configuration-logging-report-yamls)",
        "- [scripts/ (DevOps & Tools)](#scripts--deployment-maintenance-and-code-generation-scripts)",
        "",
        "---",
        "",
    ]

    # 1. Root Files
    lines.append("## Root Files")
    lines.append("| File | Lines | Description | Key Exports / Functions |")
    lines.append("|---|---|---|---|")
    for fname in ROOT_FILES:
        fpath = PROJECT_ROOT / fname
        if fpath.exists():
            meta = parse_python_file(fpath)
            cls_names = [f"`{c['name']}`" for c in meta["classes"]]
            fn_names = [f"`{fn}()`" for fn in meta["functions"] if not fn.startswith("_")][:5]
            exports = ", ".join(cls_names + fn_names) or "—"
            doc = meta["doc"] or "Top-level script"
            lines.append(f"| [`{fname}`]({fname}) | {meta['lines']} | {doc} | {exports} |")
    lines.append("")

    # 2. Directory Modules
    for dir_name, section_title in SCAN_DIRS:
        dir_path = PROJECT_ROOT / dir_name
        if not dir_path.is_dir():
            continue

        lines.append(f"## {section_title}")
        lines.append("")
        lines.append("| File | Lines | Summary / Role | Classes | Exported Functions / Helpers |")
        lines.append("|---|---|---|---|---|")

        py_files = sorted(dir_path.glob("*.py"))
        for py_file in py_files:
            rel_path = py_file.relative_to(PROJECT_ROOT)
            meta = parse_python_file(py_file)
            doc = meta["doc"] or "—"

            cls_strs = []
            for c in meta["classes"]:
                cls_strs.append(f"**`{c['name']}`**")
            classes_cell = "<br>".join(cls_strs) if cls_strs else "—"

            fn_strs = [f"`{fn}()`" for fn in meta["functions"] if not fn.startswith("_")][:6]
            # include critical private helpers if no public functions
            if not fn_strs:
                fn_strs = [f"`{fn}()`" for fn in meta["functions"][:4]]
            functions_cell = ", ".join(fn_strs) if fn_strs else "—"

            lines.append(f"| [`{py_file.name}`]({rel_path}) | {meta['lines']} | {doc} | {classes_cell} | {functions_cell} |")

        lines.append("")

        # Add detailed class breakdown for core & salesforce
        if dir_name in ("core", "salesforce"):
            lines.append(f"### Detailed Class & Method Directory (`{dir_name}/`)")
            lines.append("")
            for py_file in py_files:
                meta = parse_python_file(py_file)
                if meta["classes"]:
                    for c in meta["classes"]:
                        methods_str = ", ".join([f"`{m}()`" for m in c["methods"]]) if c["methods"] else "Data-only / Attributes"
                        lines.append(f"- **`{c['name']}`** in [`{py_file.name}`]({py_file.relative_to(PROJECT_ROOT)}): {c['doc'] or 'No docstring'}")
                        lines.append(f"  - *Methods:* {methods_str}")
            lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    md_content = generate_index()
    TARGET_FILE.write_text(md_content, encoding="utf-8")
    print(f"✅ Successfully generated module index at: {TARGET_FILE}")


if __name__ == "__main__":
    main()
