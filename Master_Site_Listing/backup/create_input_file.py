import pandas as pd
import os
import re
import shutil
import sys
from datetime import datetime
import warnings

# CONFIGURATION

REPORT_NAME = "Master Site Listing"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INPUT_SOURCE_DIR = os.path.join(BASE_DIR, "input", "source")
INPUT_ST_DIR = os.path.join(BASE_DIR, "input", "sitetracker")
RUNS_DIR = os.path.join(BASE_DIR, "runs")
ARCHIVE_DIR = os.path.join(BASE_DIR, "archive")

# MAPPING_FILE = os.path.join(BASE_DIR, "Mapping_file.xlsx")
MAPPING_FILE = os.path.join(os.path.dirname(BASE_DIR), "Common", "Mapping_file.xlsx")

warnings.filterwarnings("ignore",message="Parsing dates", category=UserWarning)
# UTILITY FUNCTIONS
def normalize_columns(df):
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)  # BOM Char replaced by Blank
        .str.replace("\u00a0", "", regex=False)  # Null replace by Blank
        .str.strip()
    )
    return df


def normalize_value(v):
    if pd.isna(v):
        return ""
    return str(v).strip()


def comparable_text(v):
    if pd.isna(v):
        return ""
    text = str(v).replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def valid_project_ref(v):
    return bool(re.match(r"^[A-Za-z0-9_-]+$", v))


def detect_salesforce_id_column(df):
    for col in df.columns:
        if "id" in col.lower():
            for v in df[col].dropna().astype(str).head(20):
                if re.match(r"^a[0-9A-Za-z]{17}$", v):
                    return col
    raise Exception("Salesforce Id column not found")


def normalize_date_uk(v):
   """
    Empty is allowed
    Accept real date types
    Accept date-like strings
    Reject random text
   """
   if pd.isna(v) or str(v).strip() == "":
       return "", True  # empty allowed
   # If already a datetime/date object
   if isinstance(v, (pd.Timestamp, datetime)):
       return v.strftime("%d/%m/%Y"), True
   text = str(v).strip()
   try:
       # STRICT parsing: only succeeds if its truly a date
       dt = pd.to_datetime(text, errors="raise",  dayfirst=True)
       #dt = pd.to_datetime(text,format="%d/%m/%Y" ) #Not working with string
       return dt.strftime("%d/%m/%Y"), True
   except Exception:
       return "", False

def assert_single_file_or_exit(folder, label):
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


#def normalize_yes_no_column(df, column_name):
 #   if column_name not in df.columns:
    #    return df
  #     df[column_name]
   #     .astype(str)
    #    .str.strip()
     #   .str.lower()
      #  .map({
       ##    "no": "No"
        #})
        #.fillna("")
    #)
    #return df
def normalize_text_case(v):
   if pd.isna(v):
       return ""
   v = str(v).strip()
   if v == "":
       return ""
   return v.title()

# LOCATE INPUT FILES (FAIL FAST)

SOURCE_FILE = assert_single_file_or_exit(INPUT_SOURCE_DIR, "Source")
SITETRACKER_FILE = assert_single_file_or_exit(INPUT_ST_DIR, "Sitetracker")

# RUN FOLDER (DATE → RUN)

run_day = datetime.now().strftime("%Y-%m-%d")
run_time = datetime.now().strftime("run_%H-%M-%S")

run_dir = os.path.join(RUNS_DIR, run_day, run_time)
os.makedirs(run_dir, exist_ok=True)


def out(name):
    return os.path.join(run_dir, name)


# LOAD MAPPING FILE

mapping_df = normalize_columns(pd.read_excel(MAPPING_FILE, dtype=str))
mapping_df = mapping_df[mapping_df["Report Name"] == REPORT_NAME]

if mapping_df.empty:
    raise Exception(f"No mapping found for report: {REPORT_NAME}")

pk_row = mapping_df[mapping_df["Primary Key?"].str.upper() == "YES"]
if pk_row.empty:
    raise Exception("Primary key not defined in mapping file")

PRIMARY_KEY_SOURCE = pk_row.iloc[0]["Source File Column Name"]
PRIMARY_KEY_ST = pk_row.iloc[0]["Sitetracker Field Name"]

FIELD_MAPPING = [
    (
        r["Source File Column Name"],
        r["Sitetracker Field Name"],
        r["API Name"],
        str(r["Data Type"]).lower()
    )
    for _, r in mapping_df.iterrows()
]

# READ DATA FILES

source_df = normalize_columns(pd.read_excel(SOURCE_FILE, dtype=str))
#Add the Column name where the records Upper case
# NOKIA -> Nokia
TEXT_CASE_COLUMNS = [
   "Site on Master Site List"
]
for col in TEXT_CASE_COLUMNS:
   if col in source_df.columns:
       source_df[col] = source_df[col].apply(normalize_text_case)


st_df = normalize_columns(pd.read_csv(
    SITETRACKER_FILE,
    dtype=str,
    encoding="latin1",
    engine="python",
    on_bad_lines="skip"
))
# Upper case FIX
#source_df = normalize_yes_no_column(source_df, "Site on Master Site List")
#source_df = normalize_text_case(source_df, "Site on Master Site List")

SF_ID_COLUMN = detect_salesforce_id_column(st_df)

# NORMALIZE PRIMARY KEYS

source_df[PRIMARY_KEY_SOURCE] = source_df[PRIMARY_KEY_SOURCE].apply(normalize_value)
st_df[PRIMARY_KEY_ST] = st_df[PRIMARY_KEY_ST].apply(normalize_value)

# INVALID PRIMARY KEYS

source_df["VALID"] = source_df[PRIMARY_KEY_SOURCE].apply(valid_project_ref)

invalid_df = source_df[~source_df["VALID"]]
invalid_df.to_csv(out("invalid_primary_key.csv"), index=False)

valid_source = source_df[source_df["VALID"]]

# DUPLICATE PRIMARY KEYS (IGNORE EMPTY)

non_empty_pk_df = source_df[
    source_df[PRIMARY_KEY_SOURCE].notna() &
    (source_df[PRIMARY_KEY_SOURCE].str.strip() != "")
    ]

duplicate_pk_df = non_empty_pk_df[
    non_empty_pk_df.duplicated(subset=[PRIMARY_KEY_SOURCE], keep=False)
]

duplicate_pk_values = sorted(duplicate_pk_df[PRIMARY_KEY_SOURCE].unique())
duplicate_pk_count = len(duplicate_pk_values)
duplicate_pk_record_count = len(duplicate_pk_df)

if duplicate_pk_count > 0:
    duplicate_pk_df.to_csv(out("duplicate_primary_keys.csv"), index=False)

# CORE LOGIC

st_index = st_df.set_index(PRIMARY_KEY_ST)

update_rows = []
change_rows = []
invalid_date_summary = []
for _, src in valid_source.iterrows():

    pr = src[PRIMARY_KEY_SOURCE]
    if pr not in st_index.index:
        continue

    st = st_index.loc[pr]
    if isinstance(st, pd.DataFrame):
        st = st.iloc[0]

    update = {
        "Id": st[SF_ID_COLUMN],
        PRIMARY_KEY_SOURCE: pr
        #"Update Reason": "One or more mapped fields changed"
    }

    changed = False

    for src_col, st_col, api_col, dtype in FIELD_MAPPING:

        if src_col == PRIMARY_KEY_SOURCE:
            continue

        src_val = normalize_value(src.get(src_col))
        st_val = normalize_value(st.get(st_col))

        if dtype == "date":
            src_val_fmt, is_valid = normalize_date_uk(src_val)
            st_val_cmp, _ = normalize_date_uk(st_val)
            if not is_valid:
                invalid_date_summary.append(
                    f"- Project: {pr} | Column: {src_col} | Invalid Value: '{src_val}'"
                )
                continue  # 🚫 do NOT update or compare
        else:
            src_val_fmt = src_val
            st_val_cmp = st_val

        update[api_col] = src_val_fmt

        if comparable_text(src_val_fmt) != comparable_text(st_val_cmp):
            changed = True
            change_rows.append({
                "Project Reference": pr,
                "Id": st[SF_ID_COLUMN],
                "Source Column": src_col,
                "Sitetracker Column": st_col,
                "API Field": api_col,
                "Old Value": st_val,
                "New Value": src_val_fmt
            })

    if changed:
        update_rows.append(update)

# OUTPUT FILES


pd.DataFrame(update_rows).to_csv(out("final_input_file.csv"), index=False)
pd.DataFrame(change_rows).to_csv(out("field_level_changes.csv"), index=False)

# RUN SUMMARY

with open(out("run_summary.txt"), "w", encoding="utf-8") as f:
    f.write(f"Report Name: {REPORT_NAME}\n")
    f.write(f"Run time: {run_day} {run_time}\n\n")

    f.write("==== COUNTS ====\n")
    f.write(f"Valid source records: {len(valid_source)}\n")
    f.write(f"Delta Records: {len(update_rows)}\n")
    f.write(f"Fields updated: {len(change_rows)}\n\n")

    f.write("==== PRIMARY KEY ====\n")
    f.write(f"Source: {PRIMARY_KEY_SOURCE}\n")
    f.write(f"Sitetracker: {PRIMARY_KEY_ST}\n\n")

    f.write("==== FIELD MAPPING USED ====\n")
    for src_col, st_col, api_col, dtype in FIELD_MAPPING:
        f.write(f"- {src_col} → {st_col} → {api_col} (type={dtype})\n")

    f.write("\n==== DUPLICATE PRIMARY KEYS (SOURCE) ====\n")
    f.write(f"Duplicate keys found: {duplicate_pk_count}\n")
    f.write(f"Total duplicate records: {duplicate_pk_record_count}\n")
    for v in duplicate_pk_values:
        f.write(f"- {v}\n")

    if invalid_date_summary:
        f.write("\n==== INVALID DATE FIELDS (SOURCE) ====\n")
        f.write(f"Total invalid date values: {len(invalid_date_summary)}\n")
        for line in invalid_date_summary:
            f.write(line + "\n")

# ARCHIVE INPUT FILES (AFTER SUCCESS)


archive_path = os.path.join(ARCHIVE_DIR, run_day, run_time)
os.makedirs(archive_path, exist_ok=True)

shutil.move(SOURCE_FILE, os.path.join(archive_path, os.path.basename(SOURCE_FILE)))
shutil.move(SITETRACKER_FILE, os.path.join(archive_path, os.path.basename(SITETRACKER_FILE)))

print(f"SUCCESS. Output written to {run_dir}")
print(f"Archived input files to {archive_path}")
