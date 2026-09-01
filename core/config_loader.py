"""YAML Configuration loader and report registry."""

import logging
from pathlib import Path
import yaml

from config import settings
from core.exceptions import ConfigInvalidError, ConfigNotFoundError
from core.models import ReportInfo

logger = logging.getLogger(__name__)


class YamlConfigLoader:
    @staticmethod
    def load(report_name: str) -> dict:
        """Load YAML configuration for a specified report name."""
        slug = report_name.lower().replace(" ", "_")
        path = settings.CONFIG_DIR / f"{slug}.yml"

        if not path.exists():
            raise ConfigNotFoundError(
                f"YAML config not found for report '{report_name}'.\n"
                f"Expected path: {path}\n"
                f"To create it, run: python scripts/scaffold_report.py \"{report_name}\""
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
        except Exception as e:
            raise ConfigInvalidError(f"Error parsing YAML file {path}: {e}")

        if not isinstance(cfg, dict):
            raise ConfigInvalidError(f"Invalid YAML config for report: {report_name} (root must be a dictionary)")

        return cfg

    @staticmethod
    def list_reports() -> list[ReportInfo]:
        """Auto-discover all configured reports from config/reports/."""
        reports: list[ReportInfo] = []

        if not settings.CONFIG_DIR.exists():
            return reports

        for yml_path in sorted(settings.CONFIG_DIR.glob("*.yml")):
            if yml_path.name.startswith("_"):  # Skip templates like _template.yml
                continue

            try:
                with open(yml_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)

                if not isinstance(cfg, dict) or "report" not in cfg:
                    continue

                name = cfg["report"].get("name", yml_path.stem.replace("_", " ").title())
                work_dir_name = cfg.get("folders", {}).get("work_dir", name.replace(" ", "_"))
                work_dir = settings.DATA_DIR / work_dir_name

                source_rel = cfg.get("folders", {}).get("source_dir", "input/source")
                st_rel = cfg.get("folders", {}).get("sitetracker_dir", "input/sitetracker")

                source_dir = work_dir / source_rel
                st_dir = work_dir / st_rel

                src_files = [f for f in source_dir.glob("*") if not f.name.startswith(".")] if source_dir.exists() else []
                st_files = [f for f in st_dir.glob("*") if not f.name.startswith(".")] if st_dir.exists() else []

                reports.append(ReportInfo(
                    name=name,
                    config_path=yml_path,
                    work_dir=work_dir,
                    has_source=len(src_files) == 1,
                    has_sitetracker=len(st_files) == 1,
                    source_file=src_files[0].name if len(src_files) == 1 else None,
                    sitetracker_file=st_files[0].name if len(st_files) == 1 else None,
                ))
            except Exception as e:
                logger.warning("Failed to parse config %s: %s", yml_path, e)
                continue

        return reports
