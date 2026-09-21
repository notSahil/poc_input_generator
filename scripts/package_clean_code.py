"""Create a clean, lightweight zip archive of the codebase for company laptop deployment."""

import os
import zipfile
from pathlib import Path

def create_clean_zip(output_zip_path: Path, root_dir: Path):
    """Package the codebase excluding heavy cache, virtual environments, git history, and run data."""
    output_zip_path = Path(output_zip_path).resolve()
    root_dir = Path(root_dir).resolve()

    excluded_dirs = {
        ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
        "node_modules", "htmlcov", "archive", "runs", "manual_runs",
        "mapping_history", ".cache", ".local", "backup", "backup_test_data",
        "backup_original", ".agents", "docs"
    }

    excluded_extensions = {
        ".pyc", ".pyo", ".pyd", ".zip", ".tar", ".gz", ".pdf",
        ".db", ".db-wal", ".db-shm", ".DS_Store", ".numbers"
    }

    excluded_files = {
        ".coverage", ".env", ".cursorrules", ".DS_Store",
        "AI_ONBOARDING_PROMPT.md",
        "PROJECT_AUDIT.md",
        "PROJECT_AUDIT.pdf",
        "PROJECT_OWNERSHIP_AND_PRODUCTION_REPORT.md",
        "PROJECT_OWNERSHIP_AND_PRODUCTION_REPORT.pdf",
        "DOMAIN_MANAGER_PROJECT_OVERVIEW.md",
        "IN_HOUSE_PRODUCT_FLOW_AND_ARCHITECTURE.md",
        "FILE_STRUCTURE_MAP.md",
        "ProtoType.html",
        "README.md",
        "quick_test.py",
        "deploy_to_oracle.sh",
        "auto_deploy.sh",
        "setup_ssl.sh",
    }

    print(f"Creating clean zip archive at: {output_zip_path}")
    count = 0

    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            rel_dir = Path(dirpath).relative_to(root_dir)

            # Prune excluded directories in-place
            dirnames[:] = [
                d for d in dirnames
                if d not in excluded_dirs
                and not d.startswith(".venv")
                and not (rel_dir.parts and rel_dir.parts[0] == "data" and d in ("runs", "archive", "manual_runs"))
            ]

            # Don't descend into data/**/runs or data/**/archive
            if len(rel_dir.parts) >= 2 and rel_dir.parts[0] == "data" and rel_dir.parts[-1] in ("runs", "archive", "manual_runs"):
                continue

            for fn in filenames:
                file_path = Path(dirpath) / fn
                rel_file = file_path.relative_to(root_dir)

                # Skip output zip itself
                if file_path.resolve() == output_zip_path:
                    continue

                # Skip credentials, temporary live data, and excluded extensions
                if file_path.suffix in excluded_extensions:
                    continue
                if fn.endswith("_live.csv"):
                    continue
                if fn in excluded_files:
                    continue
                if fn.startswith(".sf_auth") or fn.startswith(".sf_creds") or fn.startswith(".sf_pkce") or fn.startswith(".sf_profile"):
                    continue

                zf.write(file_path, arcname=str(rel_file))
                count += 1

        # Add empty placeholder directories for runtime outputs
        placeholders = [
            "data/Apollo_10G/runs/.gitkeep",
            "data/Apollo_10G/archive/.gitkeep",
            "data/Master_Site_Listing/runs/.gitkeep",
            "data/Master_Site_Listing/archive/.gitkeep",
            "data/manual_runs/.gitkeep",
            "runs/.gitkeep",
        ]
        for p in placeholders:
            zf.writestr(p, "")

    size_mb = output_zip_path.stat().st_size / (1024 * 1024)
    print(f"Successfully packaged {count} files into {output_zip_path.name} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    import sys
    proj_root = Path(__file__).resolve().parent.parent
    target_zip = proj_root / "poc_code_clean.zip"
    if len(sys.argv) > 1:
        target_zip = Path(sys.argv[1])
    create_clean_zip(target_zip, proj_root)
