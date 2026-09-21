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
    engine = InputFileEngine(args.report, insert_nulls=args.insert_nulls)
    try:
        result = engine.run(skip_validation=args.skip_validation)
        print(f"\n✅ Delta Generation Complete:")
        print(f"   - Report:               {result.report_name}")
        print(f"   - Insert Nulls Mode:    {'ENABLED (#N/A wipes)' if args.insert_nulls else 'DISABLED (Safe mode)'}")
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


def cmd_scheduler(args):
    """Handle scheduler CLI subcommands."""
    from core import job_store, scheduler

    job_store.init_db()

    action = args.sched_action

    if action == "list":
        schedules = job_store.list_schedules()
        print(f"\n⏰ Configured Task Schedules ({len(schedules)} found):\n")
        if not schedules:
            print("   No schedules configured. Create one in the UI or via API.")
            return

        print(f"{'Name':<24} | {'Report':<18} | {'Profile':<8} | {'Type / Freq':<16} | {'Next Run (UK)':<20} | {'Status':<8} | {'Last Result'}")
        print("-" * 115)
        for s in schedules:
            active_str = "🟢 Active" if s["is_active"] else "⏸ Paused"
            type_str = f"📌 One-Off" if s["schedule_type"] == "one_off" else f"🔄 {s.get('frequency', 'daily').title()}"
            last_stat = s.get("last_run_status") or "Never Run"
            next_run = s.get("next_run_at", "N/A")[:16].replace("T", " ")
            print(f"{s['name']:<24} | {s['report_name']:<18} | {s['profile']:<8} | {type_str:<16} | {next_run:<20} | {active_str:<8} | {last_stat}")
        print("")

    elif action == "run-due":
        print("\n🔍 Checking for due scheduled tasks...")
        results = scheduler.run_due_tasks()
        if not results:
            print("   No scheduled tasks are currently due.")
        else:
            print(f"\n✅ Executed {len(results)} task(s):")
            for r in results:
                print(f"   - Schedule ID: {r.get('schedule_id')} | Status: {r.get('status')}")

    elif action == "run-now":
        sched_id = args.id
        print(f"\n🚀 Triggering immediate execution for schedule ID: {sched_id}...")
        res = scheduler.execute_scheduled_task(sched_id)
        print(f"   - Status: {res.get('status')}")
        if "total_records" in res:
            print(f"   - Total records: {res.get('total_records')} | Updated: {res.get('successful_records')}")
        if "error" in res:
            print(f"   - Error: {res.get('error')}")

    elif action == "pause":
        job_store.update_schedule(args.id, is_active=0)
        print(f"\n⏸ Schedule {args.id} paused.")

    elif action == "resume":
        job_store.update_schedule(args.id, is_active=1)
        print(f"\n▶ Schedule {args.id} resumed.")

    elif action == "delete":
        if job_store.delete_schedule(args.id):
            print(f"\n🗑 Schedule {args.id} deleted.")
        else:
            print(f"\n❌ Schedule {args.id} not found.")

    elif action == "daemon":
        print("\n⏰ Starting Sitetracker Data Hub Scheduler Daemon (Ctrl+C to stop)...")
        job_store.mark_interrupted_on_startup()
        try:
            scheduler.start_scheduler_loop(poll_interval=args.interval)
        except KeyboardInterrupt:
            print("\nScheduler daemon stopped by user.")


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
    p_run.add_argument("--insert-nulls", action="store_true", help="Overwrite existing Sitetracker values with #N/A if source cell is blank")
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

    # Command: scheduler
    p_sched = subparsers.add_parser("scheduler", help="Manage and execute automated background schedules")
    sched_sub = p_sched.add_subparsers(dest="sched_action", required=True, help="Scheduler actions")

    sched_sub.add_parser("list", help="List all configured schedules and their next run times")
    sched_sub.add_parser("run-due", help="Run all due schedules immediately (ideal for cron)")

    p_s_now = sched_sub.add_parser("run-now", help="Trigger a schedule immediately by ID")
    p_s_now.add_argument("--id", required=True, help="Schedule UUID")

    p_s_pause = sched_sub.add_parser("pause", help="Pause a schedule")
    p_s_pause.add_argument("--id", required=True, help="Schedule UUID")

    p_s_resume = sched_sub.add_parser("resume", help="Resume a paused schedule")
    p_s_resume.add_argument("--id", required=True, help="Schedule UUID")

    p_s_del = sched_sub.add_parser("delete", help="Delete a schedule")
    p_s_del.add_argument("--id", required=True, help="Schedule UUID")

    p_s_daemon = sched_sub.add_parser("daemon", help="Run foreground scheduler loop for systemd")
    p_s_daemon.add_argument("--interval", type=int, default=60, help="Polling interval in seconds (default: 60)")

    p_sched.set_defaults(func=cmd_scheduler)

    args = parser.parse_args()
    setup_logging(level="WARNING")  # Keep CLI clean by default

    args.func(args)


if __name__ == "__main__":
    main()

