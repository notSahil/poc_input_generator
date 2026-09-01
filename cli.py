"""CLI entry point for the Sitetracker Input File Generator."""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.logging_config import setup_logging
from core.config_loader import YamlConfigLoader
from core.engine import InputFileEngine
from core.exceptions import EngineSkipError, InputGeneratorError, MappingError, ValidationError
from core.validator import InputValidator
from scripts.scaffold_report import scaffold


def cmd_run(args):
    """Execute the delta engine for a specific report."""
    print(f"\n🚀 Running Delta Engine for report: '{args.report}'...")
    engine = InputFileEngine(args.report)
    try:
        result = engine.run(skip_validation=args.skip_validation)
        print(f"\n✅ Delta Generation Complete:")
        print(f"   - Report:               {result.report_name}")
        print(f"   - Total Source Records: {result.total_source_records}")
        print(f"   - Valid Source Records: {result.valid_source_records}")
        print(f"   - Delta Upload Records: {result.delta_records}")
        print(f"   - Field-level Changes:  {result.field_changes_count}")
        print(f"   - Output Directory:     {result.run_dir}")

        if result.has_warnings:
            print("\n⚠️ Warnings:")
            if result.invalid_primary_keys:
                print(f"   - Invalid Primary Keys: {len(result.invalid_primary_keys)}")
            if result.duplicate_primary_keys:
                print(f"   - Duplicate Keys ({len(result.duplicate_primary_keys)}): {result.duplicate_primary_keys}")
            if result.invalid_dates:
                print(f"   - Invalid Date Values:  {len(result.invalid_dates)}")

    except EngineSkipError as e:
        print(f"\n⏭ Skipped execution: {e}")
        sys.exit(0)
    except ValidationError as e:
        print(f"\n❌ Validation Error: {e}")
        if hasattr(e, "errors"):
            for err in e.errors:
                print(f"   - {err}")
        sys.exit(1)
    except MappingError as e:
        print(f"\n❌ Mapping Error: {e}")
        sys.exit(1)
    except InputGeneratorError as e:
        print(f"\n❌ Application Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


def cmd_validate(args):
    """Validate report inputs without running the delta calculation."""
    print(f"\n🔍 Validating inputs for report: '{args.report}'...")
    try:
        validator = InputValidator(args.report)
        result = validator.validate_all()

        if result.is_valid:
            print("\n✅ All validation checks passed successfully!")
        else:
            print("\n❌ Validation Failed with the following errors:")
            for err in result.errors:
                print(f"   - {err}")

        if result.warnings:
            print("\n⚠️ Validation Warnings:")
            for warn in result.warnings:
                print(f"   - {warn}")

        sys.exit(0 if result.is_valid else 1)

    except Exception as e:
        print(f"\n❌ Validation execution error: {e}")
        sys.exit(1)


def cmd_list_reports(args):
    """List all configured reports and their input readiness status."""
    reports = YamlConfigLoader.list_reports()
    print(f"\n📋 Configured Reports ({len(reports)} found):\n")

    if not reports:
        print("   No reports found. Use 'python cli.py scaffold <name>' to create one.")
        return

    print(f"{'Report Name':<30} | {'Config':<25} | {'Source':<10} | {'Sitetracker':<12} | {'Status'}")
    print("-" * 95)

    for r in reports:
        src_status = "✅ Found" if r.has_source else "❌ Missing"
        st_status = "✅ Found" if r.has_sitetracker else "❌ Missing"
        ready_status = "🚀 Ready" if (r.has_source and r.has_sitetracker) else "⚠️ Inputs needed"
        print(f"{r.name:<30} | {r.config_path.name:<25} | {src_status:<10} | {st_status:<12} | {ready_status}")

    print("")


def cmd_scaffold(args):
    """Scaffold a new report configuration and directory structure."""
    scaffold(args.name)


def main():
    parser = argparse.ArgumentParser(
        description="Sitetracker Input File Generator — Production CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    subparsers = parser.add_subparsers(dest="command", required=True, help="Available subcommands")

    # Command: run
    p_run = subparsers.add_parser("run", help="Run the delta comparison engine for a report")
    p_run.add_argument("--report", required=True, help="Name of the report (e.g. 'Apollo 10G')")
    p_run.add_argument("--skip-validation", action="store_true", help="Skip pre-execution validation checks")
    p_run.set_defaults(func=cmd_run)

    # Command: validate
    p_validate = subparsers.add_parser("validate", help="Validate input files and mappings without executing")
    p_validate.add_argument("--report", required=True, help="Name of the report to validate")
    p_validate.set_defaults(func=cmd_validate)

    # Command: list-reports
    p_list = subparsers.add_parser("list-reports", help="List all configured reports and input statuses")
    p_list.set_defaults(func=cmd_list_reports)

    # Command: scaffold
    p_scaffold = subparsers.add_parser("scaffold", help="Scaffold a new report directory and YAML configuration")
    p_scaffold.add_argument("name", help="Name of the new report to create")
    p_scaffold.set_defaults(func=cmd_scaffold)

    args = parser.parse_args()
    setup_logging(level="WARNING")  # Keep CLI clean by default

    args.func(args)


if __name__ == "__main__":
    main()
