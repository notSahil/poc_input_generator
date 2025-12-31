# engine/input_file_engine.py

import pandas as pd
import os
import shutil
import sys
from datetime import datetime
import warnings

from engine.config_loader import YamlConfigLoader
from engine.mapping_loader import MappingLoader
from engine.normalizer import DataNormalizer

warnings.filterwarnings("ignore", message="Parsing dates", category=UserWarning)

class InputFileEngine:
    def __init__(self, report_name: str):
        self.report_name = report_name
        self.yaml_cfg = YamlConfigLoader.load(report_name)

        folders = self.yaml_cfg["folders"]

        self.base_dir = os.path.join(os.getcwd(), folders["work_dir"])
        self.source_dir = os.path.join(self.base_dir, folders["source_dir"])
        self.sitetracker_dir = os.path.join(self.base_dir, folders["sitetracker_dir"])
        self.runs_dir = os.path.join(self.base_dir, folders["runs_dir"])
        self.archive_dir = os.path.join(self.base_dir, folders["archive_dir"])

        self.mapping_file = os.path.join(
            os.path.dirname(self.base_dir),
            "Common",
            "Mapping_file.xlsx"
        )

        self.text_case_columns = self.yaml_cfg.get("text_case_columns", [])

    def _assert_single_file(self, folder, label):
        if not os.path.exists(folder):
            print(f"[SKIP] {label} folder does not exist: {folder}")
            sys.exit(0)

        files = [f for f in os.listdir(folder) if not f.startswith(".")]

        if len(files) == 0:
            print(f"[SKIP] No files found in {label} folder")
            sys.exit(0)

        if len(files) > 1:
            raise Exception(f"{label} folder must contain exactly ONE file")

        return os.path.join(folder, files[0])

    def run(self):
        print("ENGINE STARTED")
        source_file = self._assert_single_file(self.source_dir, "Source")
        st_file = self._assert_single_file(self.sitetracker_dir, "Sitetracker")

        run_day = datetime.now().strftime("%Y-%m-%d")
        run_time = datetime.now().strftime("run_%H-%M-%S")
        run_dir = os.path.join(self.runs_dir, run_day, run_time)
        os.makedirs(run_dir, exist_ok=True)

        def out(name):
            return os.path.join(run_dir, name)

        mapping = MappingLoader(self.mapping_file, self.report_name)
        mapping.load()
        pk_src, pk_st = mapping.primary_keys()
        field_map = mapping.field_mapping()

        src_df = DataNormalizer.normalize_columns(
            pd.read_excel(source_file, dtype=str)
        )

        for col in self.text_case_columns:
            if col in src_df.columns:
                src_df[col] = src_df[col].apply(DataNormalizer.normalize_text_case)

        st_df = DataNormalizer.normalize_columns(
            pd.read_csv(
                st_file,
                dtype=str,
                encoding="latin1",
                engine="python",
                on_bad_lines="skip"
            )
        )

        sf_id_col = next(
            col for col in st_df.columns
            if st_df[col].astype(str).str.match(r"^a[0-9A-Za-z]{17}$").any()
        )

        src_df[pk_src] = src_df[pk_src].apply(DataNormalizer.normalize_value)
        st_df[pk_st] = st_df[pk_st].apply(DataNormalizer.normalize_value)

        src_df["VALID"] = src_df[pk_src].apply(DataNormalizer.valid_project_ref)
        src_df[~src_df["VALID"]].to_csv(out("invalid_primary_key.csv"), index=False)

        valid_src = src_df[src_df["VALID"]]
        st_index = st_df.set_index(pk_st)

        non_empty_pk_df = valid_src[
            valid_src[pk_src].notna() &
            (valid_src[pk_src].str.strip() != "")
        ]

        duplicate_pk_df = non_empty_pk_df[
            non_empty_pk_df.duplicated(subset=[pk_src], keep=False)
        ]

        duplicate_pk_values = sorted(duplicate_pk_df[pk_src].unique())

        if duplicate_pk_values:
            duplicate_pk_df.to_csv(out("duplicate_primary_keys.csv"), index=False)

        updates, changes, invalid_dates = [], [], []

        for _, src in valid_src.iterrows():
            pr = src[pk_src]
            if pr not in st_index.index:
                continue

            st = st_index.loc[pr]
            if isinstance(st, pd.DataFrame):
                st = st.iloc[0]

            update = {"Id": st[sf_id_col], pk_src: pr}
            changed = False

            for src_col, st_col, api_col, dtype in field_map:
                if src_col == pk_src:
                    continue

                src_val = DataNormalizer.normalize_value(src.get(src_col))
                st_val = DataNormalizer.normalize_value(st.get(st_col))

                if dtype == "date":
                    src_fmt, ok = DataNormalizer.normalize_date_uk(src_val)
                    st_fmt, _ = DataNormalizer.normalize_date_uk(st_val)
                    if not ok:
                        invalid_dates.append(f"{pr} | {src_col}: {src_val}")
                        continue
                else:
                    src_fmt, st_fmt = src_val, st_val

                update[api_col] = src_fmt

                if DataNormalizer.comparable_text(src_fmt) != DataNormalizer.comparable_text(st_fmt):
                    changed = True
                    changes.append({
                        "Project Reference": pr,
                        "Id": st[sf_id_col],
                        "Source Column": src_col,
                        "Sitetracker Column": st_col,
                        "API Field": api_col,
                        "Old Value": st_val,
                        "New Value": src_fmt
                    })

            if changed:
                updates.append(update)

        pd.DataFrame(updates).to_csv(out("final_input_file.csv"), index=False)
        pd.DataFrame(changes).to_csv(out("field_level_changes.csv"), index=False)

        with open(out("run_summary.txt"), "w", encoding="utf-8") as f:
            f.write(f"Report Name: {self.report_name}\n")
            f.write(f"Run time: {run_day} {run_time}\n\n")

            f.write("==== COUNTS ====\n")
            f.write(f"Valid source records: {len(valid_src)}\n")
            f.write(f"Delta Records: {len(updates)}\n")
            f.write(f"Fields updated: {len(changes)}\n\n")

            f.write("==== PRIMARY KEY ====\n")
            f.write(f"Source: {pk_src}\n")
            f.write(f"Sitetracker: {pk_st}\n\n")

            f.write("==== FIELD MAPPING USED ====\n")
            for src_col, st_col, api_col, dtype in field_map:
                f.write(f"- {src_col} → {st_col} → {api_col} (type={dtype})\n")

            f.write("\n==== DUPLICATE PRIMARY KEYS (SOURCE) ====\n")
            f.write(f"Duplicate keys found: {len(duplicate_pk_values)}\n")
            for v in duplicate_pk_values:
                f.write(f"- {v}\n")

            if invalid_dates:
                f.write("\n==== INVALID DATE FIELDS (SOURCE) ====\n")
                f.write(f"Total invalid date values: {len(invalid_dates)}\n")
                for line in invalid_dates:
                    f.write(line + "\n")

        if self.yaml_cfg.get("behavior", {}).get("archive_after_success", True):
            archive = os.path.join(self.archive_dir, run_day, run_time)
            os.makedirs(archive, exist_ok=True)
            shutil.move(source_file, archive)
            shutil.move(st_file, archive)

        print(f"SUCCESS. Output written to {run_dir}")
    # =====================================================
# CLI ENTRY POINT
# =====================================================

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "--report":
        print("Usage: python -m engine.input_file_engine --report <REPORT_NAME>")
        sys.exit(1)

    report_name = sys.argv[2]

    engine = InputFileEngine(report_name)
    engine.run()