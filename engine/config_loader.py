import os
import yaml


class YamlConfigLoader:
    @staticmethod
    def load(report_name: str) -> dict:
        base_dir = os.getcwd()
        path = os.path.join(
            base_dir,
            "configs",
            report_name.lower().replace(" ", "_") + ".yml"
        )

        if not os.path.exists(path):
            raise Exception(f"YAML config not found: {path}")

        with open(path, "r") as f:
            cfg = yaml.safe_load(f)

        if not isinstance(cfg, dict):
            raise Exception(f"Invalid YAML config for report: {report_name}")

        return cfg