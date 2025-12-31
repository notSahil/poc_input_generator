# engine/mapping_loader.py

import pandas as pd


class MappingLoader:
    def __init__(self, mapping_file: str, report_name: str):
        self.mapping_file = mapping_file
        self.report_name = report_name
        self.mapping_df = None

    def load(self):
        df = pd.read_excel(self.mapping_file, dtype=str)
        df.columns = df.columns.astype(str).str.strip()
        df = df[df["Report Name"] == self.report_name]

        if df.empty:
            raise Exception(f"No mapping found for report: {self.report_name}")

        self.mapping_df = df
        return df

    def primary_keys(self):
        pk_row = self.mapping_df[
            self.mapping_df["Primary Key?"].str.upper() == "YES"
        ]

        if pk_row.empty:
            raise Exception("Primary key not defined in mapping file")

        return (
            pk_row.iloc[0]["Source File Column Name"],
            pk_row.iloc[0]["Sitetracker Field Name"]
        )

    def field_mapping(self):
        return [
            (
                r["Source File Column Name"],
                r["Sitetracker Field Name"],
                r["API Name"],
                str(r["Data Type"]).lower()
            )
            for _, r in self.mapping_df.iterrows()
        ]