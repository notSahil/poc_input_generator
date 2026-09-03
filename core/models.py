"""Data models for engine inputs and outputs."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FieldChange:
    """A single field-level change detected between source and sitetracker."""
    project_reference: str
    salesforce_id: str
    source_column: str
    sitetracker_column: str
    api_field: str
    old_value: str
    new_value: str


@dataclass
class RunResult:
    """Structured result of an engine run."""
    success: bool
    report_name: str
    run_dir: Path

    # Counts
    total_source_records: int = 0
    valid_source_records: int = 0
    delta_records: int = 0         # Records with at least one changed field
    field_changes_count: int = 0   # Total individual field changes

    # Quality issues — existing
    invalid_primary_keys: list[str] = field(default_factory=list)
    duplicate_primary_keys: list[str] = field(default_factory=list)
    invalid_dates: list[str] = field(default_factory=list)

    # New classification counters (Dataloader.io style)
    error_records: int = 0          # Rows rejected for any validation failure
    skipped_records: int = 0        # Rows with no changes detected
    not_found_records: int = 0      # PKs not found in Sitetracker CSV
    date_error_records: int = 0     # Rows rejected for invalid date values
    type_error_records: int = 0     # Rows rejected for wrong data type

    # Mapping used
    primary_key_source: str = ""
    primary_key_sitetracker: str = ""
    field_mappings: list[tuple[str, str, str, str]] = field(default_factory=list)

    # Error info (if success=False)
    error_message: str | None = None

    @property
    def has_warnings(self) -> bool:
        return bool(self.invalid_primary_keys or self.duplicate_primary_keys or self.invalid_dates)

    @property
    def has_errors(self) -> bool:
        """True if any rows were rejected due to validation failures."""
        return self.error_records > 0


@dataclass
class ValidationResult:
    """Result of input validation checks."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ReportInfo:
    """Metadata about an available report."""
    name: str
    config_path: Path
    work_dir: Path
    has_source: bool = False
    has_sitetracker: bool = False
    source_file: str | None = None
    sitetracker_file: str | None = None
