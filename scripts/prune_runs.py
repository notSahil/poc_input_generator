"""Utility script to prune historical run logs, keeping the latest N runs per report."""

import argparse
import logging
import shutil
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


def prune_runs(keep: int = 5, dry_run: bool = False) -> dict:
    """Prune historical run logs, keeping the newest N runs per report."""
    reports = YamlConfigLoader.list_reports()
    summary = {}

    for r in reports:
        yaml_cfg = YamlConfigLoader.load(r.name)
        work_dir = settings.DATA_DIR / yaml_cfg["folders"]["work_dir"]
        runs_dir = work_dir / yaml_cfg["folders"]["runs_dir"]
        archive_dir = work_dir / yaml_cfg["folders"]["archive_dir"]

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
            "Report '%s': %d total runs -> Keeping %d, Deleting %d",
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

        summary[r.name] = {
            "total": len(scanned_runs),
            "kept": len(keep_runs),
            "deleted": deleted_count if not dry_run else len(delete_runs),
        }

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prune historical runs, keeping latest N per report.")
    parser.add_argument("--keep", type=int, default=5, help="Number of latest runs to keep per report (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()

    prune_runs(keep=args.keep, dry_run=args.dry_run)
