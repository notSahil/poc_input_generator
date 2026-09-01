"""Scaffold a new report with YAML configuration and standard data directory structure."""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings

TEMPLATE_FILE = settings.CONFIG_DIR / "_template.yml"


def scaffold(report_name: str) -> None:
    """Create directory structure and YAML configuration for a new report."""
    report_name = report_name.strip()
    if not report_name:
        print("❌ Error: Report name cannot be empty.")
        sys.exit(1)

    slug = report_name.lower().replace(" ", "_")
    folder_name = report_name.replace(" ", "_")

    # 1. Create YAML configuration
    settings.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_path = settings.CONFIG_DIR / f"{slug}.yml"

    if config_path.exists():
        print(f"⚠️ Warning: Config file already exists at {config_path}")
    else:
        if TEMPLATE_FILE.exists():
            template_text = TEMPLATE_FILE.read_text(encoding="utf-8")
            config_text = (
                template_text
                .replace("Your Report Name Here", report_name)
                .replace("Your_Report_Name_Here", folder_name)
            )
        else:
            config_text = f"""report:
  name: "{report_name}"
  sf_id_column: "Id"

folders:
  work_dir: "{folder_name}"
  source_dir: "input/source"
  sitetracker_dir: "input/sitetracker"
  runs_dir: "runs"
  archive_dir: "archive"

date:
  format: UK
  dayfirst: true
  allow_empty: true

text_case_columns: []

behavior:
  archive_after_success: true
"""
        config_path.write_text(config_text, encoding="utf-8")
        print(f"✅ Created report config: {config_path}")

    # 2. Create data directories
    data_dir = settings.DATA_DIR / folder_name
    for sub in ["input/source", "input/sitetracker", "runs", "archive"]:
        (data_dir / sub).mkdir(parents=True, exist_ok=True)

    print(f"✅ Created report data directories under: {data_dir}")

    # 3. Print next steps
    print(f"\n📋 Next Steps:")
    print(f"   1. Open the Mapping Editor in the UI or edit `data/common/Mapping_file.xlsx`")
    print(f"      and add rows with Report Name = \"{report_name}\"")
    print(f"   2. Place your source Excel spreadsheet in:")
    print(f"      {data_dir / 'input/source/'}")
    print(f"   3. Place your Sitetracker CSV export in:")
    print(f"      {data_dir / 'input/sitetracker/'}")
    print(f"   4. Validate inputs:")
    print(f"      python cli.py validate --report \"{report_name}\"")
    print(f"   5. Run the generator:")
    print(f"      python cli.py run --report \"{report_name}\"")


def main():
    parser = argparse.ArgumentParser(description="Scaffold a new Sitetracker report workflow")
    parser.add_argument("name", help="Name of the report (e.g. 'Apollo 10G', 'Substation Upgrades')")
    args = parser.parse_args()
    scaffold(args.name)


if __name__ == "__main__":
    main()
