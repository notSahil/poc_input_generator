"""Utility script to prune historical run logs, source archives, and mapping history.

Keeps the latest N runs per report/object, ensuring disk usage remains lean while
preserving recent execution audits and rollback safety nets.
"""

import argparse
import logging
import shutil
import sqlite3
import sys
from pathlib import Path

# Ensure root directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import settings
from core.config_loader import YamlConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("prune_runs")


def prune_guided_runs(keep: int = 10, dry_run: bool = False) -> dict:
    """Prune historical guided report runs and archive folders."""
    reports = YamlConfigLoader.list_reports()
    summary = {}

    for r in reports:
        try:
            yaml_cfg = YamlConfigLoader.load(r.name)
            work_dir = settings.DATA_DIR / yaml_cfg["folders"]["work_dir"]
            runs_dir = work_dir / yaml_cfg["folders"]["runs_dir"]
            archive_dir = work_dir / yaml_cfg["folders"]["archive_dir"]
        except Exception:
            continue

        if not runs_dir.exists():
            continue

        scanned_runs = []
        for date_dir in sorted(runs_dir.iterdir(), reverse=True):
            if not date_dir.is_dir() or date_dir.name.startswith("."):
                continue
            for run_dir in sorted(date_dir.iterdir(), reverse=True):
                if not run_dir.is_dir() or run_dir.name.startswith("."):
                    continue
                matching_archive = archive_dir / date_dir.name / run_dir.name
                scanned_runs.append({
                    "date": date_dir.name,
                    "time": run_dir.name.replace("run_", "").replace("-", ":"),
                    "run_dir": run_dir,
                    "archive_dir": matching_archive if matching_archive.exists() else None,
                })

        scanned_runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)

        keep_runs = scanned_runs[:keep]
        delete_runs = scanned_runs[keep:]

        logger.info(
            "Guided Report '%s': %d total runs -> Keeping %d, Deleting %d",
            r.name, len(scanned_runs), len(keep_runs), len(delete_runs)
        )

        deleted_count = 0
        if not dry_run:
            for item in delete_runs:
                r_dir = item["run_dir"]
                a_dir = item["archive_dir"]
                try:
                    if r_dir.exists():
                        shutil.rmtree(r_dir)
                    if a_dir and a_dir.exists():
                        shutil.rmtree(a_dir)
                    deleted_count += 1
                except Exception as e:
                    logger.error("Failed to delete run %s: %s", r_dir, e)

            # Clean up empty date folders
            for parent_dir in [runs_dir, archive_dir]:
                if not parent_dir.exists():
                    continue
                for d in list(parent_dir.iterdir()):
                    if d.is_dir() and not list(d.iterdir()):
                        try:
                            d.rmdir()
                            logger.info("Removed empty date directory: %s", d)
                        except Exception as e:
                            logger.warning("Could not remove %s: %s", d, e)

        # Prune source input archives (e.g. data/<Report>/input/source/archive)
        src_arch_dir = work_dir / "input" / "source" / "archive"
        if src_arch_dir.exists():
            arch_files = sorted(
                [f for f in src_arch_dir.iterdir() if f.is_file() and not f.name.startswith(".")],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            del_arch = arch_files[keep:]
            logger.info("  Input source archive: %d files -> Keeping %d, Deleting %d", len(arch_files), min(len(arch_files), keep), len(del_arch))
            if not dry_run:
                for af in del_arch:
                    try:
                        af.unlink()
                    except Exception as e_af:
                        logger.warning("Could not delete archive %s: %s", af, e_af)

        summary[r.name] = {
            "total": len(scanned_runs),
            "kept": len(keep_runs),
            "deleted": deleted_count if not dry_run else len(delete_runs),
        }

    return summary


def prune_manual_runs(keep: int = 10, dry_run: bool = False) -> dict:
    """Prune historical manual dataloader runs per object."""
    manual_dir = settings.DATA_DIR / "manual_runs"
    summary = {}
    if not manual_dir.exists():
        return summary

    for obj_dir in sorted(manual_dir.iterdir()):
        if not obj_dir.is_dir() or obj_dir.name.startswith("."):
            continue

        scanned_runs = []
        for date_dir in sorted(obj_dir.iterdir(), reverse=True):
            if not date_dir.is_dir() or date_dir.name.startswith("."):
                continue
            for run_dir in sorted(date_dir.iterdir(), reverse=True):
                if not run_dir.is_dir() or run_dir.name.startswith("."):
                    continue
                scanned_runs.append({
                    "date": date_dir.name,
                    "time": run_dir.name.replace("run_", "").replace("-", ":"),
                    "run_dir": run_dir,
                })

        scanned_runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
        keep_runs = scanned_runs[:keep]
        delete_runs = scanned_runs[keep:]

        logger.info(
            "Manual Ingest Object '%s': %d total runs -> Keeping %d, Deleting %d",
            obj_dir.name, len(scanned_runs), len(keep_runs), len(delete_runs)
        )

        deleted_count = 0
        if not dry_run:
            for item in delete_runs:
                r_dir = item["run_dir"]
                try:
                    if r_dir.exists():
                        shutil.rmtree(r_dir)
                    deleted_count += 1
                except Exception as e:
                    logger.error("Failed to delete manual run %s: %s", r_dir, e)

            # Clean up empty date folders
            for d in list(obj_dir.iterdir()):
                if d.is_dir() and not list(d.iterdir()):
                    try:
                        d.rmdir()
                        logger.info("Removed empty date directory: %s", d)
                    except Exception as e:
                        logger.warning("Could not remove %s: %s", d, e)

        summary[obj_dir.name] = {
            "total": len(scanned_runs),
            "kept": len(keep_runs),
            "deleted": deleted_count if not dry_run else len(delete_runs),
        }

    return summary


def prune_mapping_history(keep: int = 5, dry_run: bool = False) -> int:
    """Prune historical mapping editor backups, keeping latest N."""
    history_dir = settings.DATA_DIR / "common" / "mapping_history"
    if not history_dir.exists():
        return 0

    all_backups = sorted(
        [f for f in history_dir.glob("*.xlsx") if f.is_file()],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    keep_files = all_backups[:keep]
    delete_files = all_backups[keep:]

    logger.info(
        "Mapping History: %d total backups -> Keeping %d, Deleting %d",
        len(all_backups), len(keep_files), len(delete_files)
    )

    deleted_count = 0
    if not dry_run:
        for f in delete_files:
            try:
                f.unlink()
                deleted_count += 1
            except Exception as e:
                logger.warning("Failed to delete mapping backup %s: %s", f, e)

    return deleted_count if not dry_run else len(delete_files)


def vacuum_job_store() -> None:
    """Optimize SQLite database if present."""
    db_path = settings.DATA_DIR / "jobs.db"
    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("VACUUM;")
            logger.info("Optimized SQLite database: %s", db_path)
        except Exception as e:
            logger.warning("Could not vacuum %s: %s", db_path, e)


def prune_all(keep_runs: int = 10, keep_backups: int = 5, dry_run: bool = False) -> None:
    """Execute complete cleanup across guided runs, manual runs, archives, and mapping history."""
    mode_str = "[DRY-RUN] " if dry_run else ""
    logger.info("%sStarting cleanup: keeping %d latest runs and %d latest mapping backups...", mode_str, keep_runs, keep_backups)

    guided_summary = prune_guided_runs(keep=keep_runs, dry_run=dry_run)
    manual_summary = prune_manual_runs(keep=keep_runs, dry_run=dry_run)
    deleted_backups = prune_mapping_history(keep=keep_backups, dry_run=dry_run)

    if not dry_run:
        vacuum_job_store()

    logger.info("%sCleanup complete!", mode_str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prune historical runs, keeping latest N per report/object.")
    parser.add_argument("--keep", type=int, default=10, help="Number of latest runs to keep (default: 10)")
    parser.add_argument("--keep-backups", type=int, default=5, help="Number of latest mapping backups to keep (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions without deleting anything")
    args = parser.parse_args()

    prune_all(keep_runs=args.keep, keep_backups=args.keep_backups, dry_run=args.dry_run)
