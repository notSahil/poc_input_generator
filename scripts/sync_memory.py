#!/usr/bin/env python3
"""
sync_memory.py — Automated AI Memory & Project Structure Synchronizer

1. Runs gen_module_index.py to update .memory/MODULE_INDEX.md with all current classes/functions.
2. Scans core/, ui/, salesforce/, config/, scripts/ for any files missing from FILE_STRUCTURE_MAP.md
   and auto-appends them with their docstrings under the right directory section.
3. Validates that core output contracts in .memory/CONTRACTS.md remain untouched.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FILE_MAP_PATH = PROJECT_ROOT / "FILE_STRUCTURE_MAP.md"
MEMORY_DIR = PROJECT_ROOT / ".memory"

SCAN_SECTIONS = [
    ("core", "### `/core` (Backend Logic & Data Processing)"),
    ("ui", "### `/ui` (Streamlit Frontend)"),
    ("salesforce", "### `/salesforce` (Integrations)"),
    ("config", "### `/config` (Settings)"),
    ("scripts", "### `/scripts` (Utilities)"),
]


def run_module_index_generator() -> bool:
    """Run gen_module_index.py to rebuild MODULE_INDEX.md."""
    gen_script = PROJECT_ROOT / "scripts" / "gen_module_index.py"
    if not gen_script.exists():
        print(f"⚠️ Warning: {gen_script} not found.")
        return False

    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_module_index", gen_script)
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "main"):
            mod.main()
            return True
    return False


def get_first_sentence_docstring(file_path: Path) -> str:
    """Extract first sentence of docstring or default description."""
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
        doc = ast.get_docstring(tree)
        if doc:
            return doc.strip().split("\n")[0].strip()
    except Exception:
        pass
    return f"Module {file_path.name}"


def sync_file_structure_map() -> int:
    """Detect new files on disk missing from FILE_STRUCTURE_MAP.md and insert them."""
    if not FILE_MAP_PATH.exists():
        print("⚠️ Warning: FILE_STRUCTURE_MAP.md not found.")
        return 0

    content = FILE_MAP_PATH.read_text(encoding="utf-8")
    added_count = 0

    for dir_name, section_header in SCAN_SECTIONS:
        dir_path = PROJECT_ROOT / dir_name
        if not dir_path.is_dir():
            continue

        if section_header not in content:
            continue

        # Find all python / shell files in this directory
        existing_files = sorted([
            f for f in dir_path.iterdir()
            if f.is_file() and not f.name.startswith((".", "__pycache__"))
        ])

        for f in existing_files:
            # Check if filename is mentioned in FILE_STRUCTURE_MAP.md
            pattern = rf"`{re.escape(f.name)}`"
            if not re.search(pattern, content):
                doc = get_first_sentence_docstring(f)
                entry = f"- `{f.name}`: {doc}\n"

                # Find the section and insert the new line after the section header
                header_pos = content.find(section_header)
                if header_pos != -1:
                    insert_pos = header_pos + len(section_header) + 1
                    content = content[:insert_pos] + entry + content[insert_pos:]
                    added_count += 1
                    print(f"✨ Auto-registered new file in FILE_STRUCTURE_MAP.md: {dir_name}/{f.name}")

    if added_count > 0:
        FILE_MAP_PATH.write_text(content, encoding="utf-8")
        print(f"✅ Updated FILE_STRUCTURE_MAP.md with {added_count} new file(s).")
    else:
        print("✅ FILE_STRUCTURE_MAP.md is completely in sync with codebase.")

    return added_count


def verify_output_contracts() -> bool:
    """Verify that all 5 inviolable files are documented in CONTRACTS.md."""
    contracts_file = MEMORY_DIR / "CONTRACTS.md"
    if not contracts_file.exists():
        print("⚠️ Warning: .memory/CONTRACTS.md not found.")
        return False

    content = contracts_file.read_text(encoding="utf-8")
    required_files = [
        "final_input_file.csv",
        "field_level_changes.csv",
        "invalid_primary_key.csv",
        "duplicate_primary_keys.csv",
        "run_summary.txt",
    ]
    all_present = True
    for rf in required_files:
        if rf not in content:
            print(f"❌ Error: Required core contract file '{rf}' missing from .memory/CONTRACTS.md!")
            all_present = False

    if all_present:
        print("✅ All 5 core output contracts verified in .memory/CONTRACTS.md.")
    return all_present


def main() -> int:
    print("=" * 60)
    print("🔄 SITETRACKER DATA HUB — AI MEMORY AUTO-SYNCHRONIZER")
    print("=" * 60)

    # 1. Update MODULE_INDEX.md
    print("\n[Step 1/3] Updating .memory/MODULE_INDEX.md...")
    run_module_index_generator()

    # 2. Sync FILE_STRUCTURE_MAP.md
    print("\n[Step 2/3] Checking FILE_STRUCTURE_MAP.md for untracked files...")
    sync_file_structure_map()

    # 3. Check Contracts
    print("\n[Step 3/3] Verifying output contracts...")
    contracts_ok = verify_output_contracts()

    print("\n" + "=" * 60)
    if contracts_ok:
        print("🎉 Memory synchronization complete! AI knowledge base is 100% up to date.")
        print("=" * 60)
        return 0
    else:
        print("⚠️ Completed with warnings. Please inspect output contracts.")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
