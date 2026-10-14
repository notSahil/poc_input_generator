#!/usr/bin/env python3
"""
Sitetracker Data Hub — Enterprise User Guide Generator (.docx)
Generates an executive, fully-formatted Microsoft Word User Guide with:
- Salesforce Lightning Design System (SLDS) styling
- Complete feature walkthroughs with step-by-step instructions
- Dedicated, styled screenshot placeholder boxes with capture guides
- Automated image embedding if screenshots exist in docs/screenshots/
- Executive comparison tables, callout alert boxes, and output schemas
"""

from __future__ import annotations

import sys
from pathlib import Path
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

# ---------------------------------------------------------------------------
# COLOR PALETTE (SLDS & Executive Enterprise Branding)
# ---------------------------------------------------------------------------
NAVY_HEX = "0B2149"        # #0B2149 - Deep Corporate Navy
SF_BLUE_HEX = "0176D3"     # #0176D3 - Salesforce Brand Blue
SLATE_HEX = "5C6F84"       # #5C6F84 - Secondary Slate
BODY_HEX = "2B2B2B"        # #2B2B2B - Charcoal Body Text
BG_LIGHT_HEX = "F4F8FB"    # #F4F8FB - Light Slate Tint
BG_HEADER_HEX = "0B2149"   # Header Row Fill
BG_ALT_ROW = "F8FAFC"      # Alternating Row Shading
BORDER_GRAY = "D8DDE6"     # Table Border Gray
BORDER_BLUE = "0176D3"     # Box Accent Border
GREEN_HEX = "2E844A"       # Emerald Green for Tips
ORANGE_HEX = "D96B27"      # Soft Amber for Warnings
RED_HEX = "BA0517"         # Red for Critical Alerts

COLOR_NAVY = RGBColor(11, 33, 73)
COLOR_SF_BLUE = RGBColor(1, 118, 211)
COLOR_SLATE = RGBColor(92, 111, 132)
COLOR_BODY = RGBColor(43, 43, 43)

SCREENSHOTS_DIR = Path("docs/screenshots")
OUTPUT_DOCX_PATH = Path("docs/Sitetracker_Data_Hub_User_Guide.docx")


# ---------------------------------------------------------------------------
# XML HELPER FUNCTIONS
# ---------------------------------------------------------------------------
def set_cell_shading(cell, color_hex: str) -> None:
    """Applies background fill color to a table cell."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    tcPr.append(shd)


def set_cell_margins(cell, top: int = 140, bottom: int = 140, left: int = 200, right: int = 200) -> None:
    """Sets cell internal padding in dxa units (20 dxa = 1 pt)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>\n'
        f'  <w:top w:w="{top}" w:type="dxa"/>\n'
        f'  <w:bottom w:w="{bottom}" w:type="dxa"/>\n'
        f'  <w:left w:w="{left}" w:type="dxa"/>\n'
        f'  <w:right w:w="{right}" w:type="dxa"/>\n'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)


def set_callout_border(cell, color_hex: str, sz: int = 24) -> None:
    """Creates a thick left border for callout alert boxes."""
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>\n'
        f'  <w:top w:val="none"/>\n'
        f'  <w:left w:val="single" w:sz="{sz}" w:space="0" w:color="{color_hex}"/>\n'
        f'  <w:bottom w:val="none"/>\n'
        f'  <w:right w:val="none"/>\n'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)


def set_box_borders(cell, color_hex: str = BORDER_BLUE, sz: int = 12, val: str = "single") -> None:
    """Applies a 4-sided border around a cell (for screenshot placeholders)."""
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>\n'
        f'  <w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color_hex}"/>\n'
        f'  <w:left w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color_hex}"/>\n'
        f'  <w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color_hex}"/>\n'
        f'  <w:right w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color_hex}"/>\n'
        f'</w:tcBorders>'
    )
    tcPr.append(borders)


def set_table_borders(table, color_hex: str = BORDER_GRAY) -> None:
    """Applies clean horizontal table borders with no vertical borders."""
    tblPr = table._tbl.tblPr
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>\n'
        f'  <w:top w:val="single" w:sz="6" w:space="0" w:color="{color_hex}"/>\n'
        f'  <w:bottom w:val="single" w:sz="8" w:space="0" w:color="{NAVY_HEX}"/>\n'
        f'  <w:left w:val="none"/>\n'
        f'  <w:right w:val="none"/>\n'
        f'  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>\n'
        f'  <w:insideV w:val="none"/>\n'
        f'</w:tblBorders>'
    )
    tblPr.append(borders)


# ---------------------------------------------------------------------------
# DOCUMENT GENERATOR CLASS
# ---------------------------------------------------------------------------
class UserGuideDocxBuilder:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.doc = Document()
        self._configure_document_geometry()
        self._setup_styles()

    def _configure_document_geometry(self) -> None:
        """Sets standard 1-inch margins and page size."""
        for section in self.doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.0)
            section.right_margin = Inches(1.0)
            section.page_width = Inches(8.5)
            section.page_height = Inches(11.0)

            # Header & Footer setup
            header = section.header
            header_p = header.paragraphs[0]
            header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            hrun = header_p.add_run("Sitetracker Data Hub — Enterprise User Guide & Operational Manual")
            hrun.font.name = "Calibri"
            hrun.font.size = Pt(8.5)
            hrun.font.color.rgb = COLOR_SLATE

            footer = section.footer
            footer_p = footer.paragraphs[0]
            footer_p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            frun1 = footer_p.add_run("CONFIDENTIAL • Sitetracker Data Operations Platform\t\t")
            frun1.font.name = "Calibri"
            frun1.font.size = Pt(8.5)
            frun1.font.color.rgb = COLOR_SLATE
            frun2 = footer_p.add_run("Production Release v2.4")
            frun2.font.name = "Calibri"
            frun2.font.size = Pt(8.5)
            frun2.font.color.rgb = COLOR_SLATE

    def _setup_styles(self) -> None:
        """Registers font sizes and default paragraph formatting."""
        normal_style = self.doc.styles["Normal"]
        normal_style.font.name = "Calibri"
        normal_style.font.size = Pt(10.5)
        normal_style.font.color.rgb = COLOR_BODY
        normal_style.paragraph_format.line_spacing = 1.15
        normal_style.paragraph_format.space_after = Pt(4)

    # -----------------------------------------------------------------------
    # TYPOGRAPHY & LAYOUT HELPERS
    # -----------------------------------------------------------------------
    def add_title(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.font.name = "Segoe UI"
        run.font.size = Pt(26)
        run.font.bold = True
        run.font.color.rgb = COLOR_NAVY
        p.paragraph_format.space_before = Pt(36)
        p.paragraph_format.space_after = Pt(4)

    def add_subtitle(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(13)
        run.font.color.rgb = COLOR_SF_BLUE
        p.paragraph_format.space_after = Pt(24)

    def add_heading_1(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        run.font.name = "Segoe UI"
        run.font.size = Pt(16)
        run.font.bold = True
        run.font.color.rgb = COLOR_NAVY

    def add_heading_2(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        run.font.name = "Segoe UI"
        run.font.size = Pt(12.5)
        run.font.bold = True
        run.font.color.rgb = COLOR_SF_BLUE

    def add_heading_3(self, text: str) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.keep_with_next = True
        run = p.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = COLOR_NAVY

    def add_body(self, text: str, bold_prefix: str = "", space_after: int = 4) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_after = Pt(space_after)
        if bold_prefix:
            brun = p.add_run(bold_prefix)
            brun.font.bold = True
            brun.font.color.rgb = COLOR_NAVY
        run = p.add_run(text)
        run.font.color.rgb = COLOR_BODY

    def add_bullet(self, bold_text: str, normal_text: str) -> None:
        p = self.doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(3)
        brun = p.add_run(bold_text + " ")
        brun.font.bold = True
        brun.font.color.rgb = COLOR_NAVY
        nrun = p.add_run(normal_text)
        nrun.font.color.rgb = COLOR_BODY

    def add_callout(self, title: str, text: str, alert_type: str = "NOTE") -> None:
        """Renders an enterprise callout alert box with a colored left border."""
        border_color = SF_BLUE_HEX
        bg_color = "F0F6FA"
        icon = "ℹ️ NOTE"

        if alert_type == "TIP":
            border_color = GREEN_HEX
            bg_color = "F0F9F3"
            icon = "💡 PRO TIP"
        elif alert_type == "WARNING":
            border_color = ORANGE_HEX
            bg_color = "FFF8F0"
            icon = "⚠️ IMPORTANT"
        elif alert_type == "CONTRACT":
            border_color = NAVY_HEX
            bg_color = "F4F6F9"
            icon = "🔒 INVIOLABLE CONTRACT"

        table = self.doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        cell = table.cell(0, 0)
        cell.width = Inches(6.5)

        set_cell_shading(cell, bg_color)
        set_callout_border(cell, border_color, sz=24)
        set_cell_margins(cell, top=140, bottom=140, left=200, right=160)

        cp = cell.paragraphs[0]
        cp.paragraph_format.space_after = Pt(3)
        irun = cp.add_run(f"{icon}: {title}\n")
        irun.font.bold = True
        irun.font.size = Pt(10)
        irun.font.name = "Segoe UI"
        irun.font.color.rgb = COLOR_NAVY

        trun = cp.add_run(text)
        trun.font.size = Pt(9.5)
        trun.font.color.rgb = COLOR_BODY

        # Add breathing room after table
        sp = self.doc.add_paragraph()
        sp.paragraph_format.space_before = Pt(2)
        sp.paragraph_format.space_after = Pt(2)

    def add_screenshot_placeholder(
        self,
        figure_num: str,
        title: str,
        target_view: str,
        what_to_capture: str,
        image_filename: str = ""
    ) -> None:
        """
        Embeds a screenshot if the image exists in docs/screenshots/.
        Otherwise, renders a styled placeholder box with clear instructions for the user.
        """
        image_path = SCREENSHOTS_DIR / image_filename if image_filename else None
        has_image = image_path and image_path.exists()

        if has_image:
            # Insert real image
            p_img = self.doc.add_paragraph()
            p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_img.paragraph_format.space_before = Pt(8)
            p_img.paragraph_format.space_after = Pt(2)
            run = p_img.add_run()
            run.add_picture(str(image_path), width=Inches(6.3))
        else:
            # Render styled placeholder box
            table = self.doc.add_table(rows=1, cols=1)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            cell = table.cell(0, 0)
            cell.width = Inches(6.5)

            set_cell_shading(cell, BG_LIGHT_HEX)
            set_box_borders(cell, color_hex=SF_BLUE_HEX, sz=10, val="single")
            set_cell_margins(cell, top=180, bottom=180, left=220, right=220)

            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(4)

            # Box Header
            cam_run = p.add_run("📷 [PASTE SCREENSHOT HERE]\n")
            cam_run.font.name = "Segoe UI"
            cam_run.font.bold = True
            cam_run.font.size = Pt(11)
            cam_run.font.color.rgb = COLOR_SF_BLUE

            # Feature Tag
            title_run = p.add_run(f"Screen: {title}\n")
            title_run.font.name = "Calibri"
            title_run.font.bold = True
            title_run.font.size = Pt(10)
            title_run.font.color.rgb = COLOR_NAVY

            # Capture Guidance
            instr_run = p.add_run(f"Navigation: {target_view}\n")
            instr_run.font.italic = True
            instr_run.font.size = Pt(9)
            instr_run.font.color.rgb = COLOR_SLATE

            guide_run = p.add_run(f"What to capture: {what_to_capture}\n")
            guide_run.font.size = Pt(9)
            guide_run.font.color.rgb = COLOR_BODY

            hint_run = p.add_run("👉 (In Word: Select this box, press Delete, and Paste (Ctrl+V) your screenshot image)")
            hint_run.font.size = Pt(8.5)
            hint_run.font.color.rgb = COLOR_SLATE

        # Figure Caption
        p_cap = self.doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_cap.paragraph_format.space_before = Pt(3)
        p_cap.paragraph_format.space_after = Pt(10)
        crun = p_cap.add_run(f"Figure {figure_num}: {title}")
        crun.font.name = "Calibri"
        crun.font.italic = True
        crun.font.size = Pt(9)
        crun.font.color.rgb = COLOR_SLATE

    def add_table_data(self, headers: list[str], rows: list[list[str]], col_widths: list[float] | None = None) -> None:
        """Renders an SLDS-styled table with navy header and zebra striping."""
        table = self.doc.add_table(rows=len(rows) + 1, cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        set_table_borders(table, BORDER_GRAY)

        # Header Row
        hdr_cells = table.rows[0].cells
        for i, header_text in enumerate(headers):
            hdr_cells[i].text = header_text
            set_cell_shading(hdr_cells[i], BG_HEADER_HEX)
            set_cell_margins(hdr_cells[i], top=120, bottom=120, left=140, right=140)
            p = hdr_cells[i].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            for run in p.runs:
                run.font.name = "Segoe UI"
                run.font.bold = True
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor(255, 255, 255)

        # Data Rows
        for r_idx, row_data in enumerate(rows):
            row_cells = table.rows[r_idx + 1].cells
            bg = BG_ALT_ROW if r_idx % 2 == 1 else "FFFFFF"
            for c_idx, cell_value in enumerate(row_data):
                row_cells[c_idx].text = cell_value
                set_cell_shading(row_cells[c_idx], bg)
                set_cell_margins(row_cells[c_idx], top=90, bottom=90, left=140, right=140)
                p = row_cells[c_idx].paragraphs[0]
                for run in p.runs:
                    run.font.name = "Calibri"
                    run.font.size = Pt(9)
                    run.font.color.rgb = COLOR_BODY

        # Column widths
        if col_widths:
            for row in table.rows:
                for idx, w in enumerate(col_widths):
                    row.cells[idx].width = Inches(w)

        # Space after table
        sp = self.doc.add_paragraph()
        sp.paragraph_format.space_before = Pt(2)
        sp.paragraph_format.space_after = Pt(6)

    # -----------------------------------------------------------------------
    # DOCUMENT CHAPTER ASSEMBLERS
    # -----------------------------------------------------------------------
    def build_cover_page(self) -> None:
        """Assembles executive cover page with metadata."""
        # Top Badge
        p_badge = self.doc.add_paragraph()
        p_badge.alignment = WD_ALIGN_PARAGRAPH.CENTER
        brun = p_badge.add_run("ENTERPRISE DATA OPERATIONS MANUAL")
        brun.font.name = "Segoe UI"
        brun.font.bold = True
        brun.font.size = Pt(10)
        brun.font.color.rgb = COLOR_SF_BLUE
        p_badge.paragraph_format.space_before = Pt(40)

        # Title
        self.add_title("⚡ Sitetracker Data Hub")
        self.add_subtitle("POC Input Generator & Automated Salesforce Ingestion Engine\nComplete Operational Guide & User Manual")

        # Metadata Card Box
        table = self.doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        cell = table.cell(0, 0)
        cell.width = Inches(5.5)
        set_cell_shading(cell, BG_LIGHT_HEX)
        set_box_borders(cell, color_hex=BORDER_GRAY, sz=8)
        set_cell_margins(cell, top=160, bottom=160, left=200, right=200)

        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r1 = p.add_run("DOCUMENT CONTROL & PLATFORM METADATA\n\n")
        r1.font.bold = True
        r1.font.size = Pt(10)
        r1.font.color.rgb = COLOR_NAVY

        meta_lines = [
            ("Platform Version:", "2.4 (Production Release)"),
            ("Operating System:", "Oracle Cloud Ubuntu Linux (LTS)"),
            ("Access Endpoint:", "https://161-118-182-20.sslip.io"),
            ("Target Audience:", "Data Operations, Project Managers, Sitetracker Admins"),
            ("Classification:", "Internal Enterprise Documentation (Restricted)"),
            ("Date Published:", "October 2026"),
        ]
        for label, val in meta_lines:
            lr = p.add_run(f"{label:<22} ")
            lr.font.bold = True
            lr.font.size = Pt(9)
            lr.font.color.rgb = COLOR_NAVY
            vr = p.add_run(f"{val}\n")
            vr.font.size = Pt(9)
            vr.font.color.rgb = COLOR_BODY

        self.doc.add_page_break()

    def build_chapter_1_overview(self) -> None:
        """Chapter 1: Platform Overview & Business Impact."""
        self.add_heading_1("1. Platform Overview & Business Impact")
        self.add_body(
            "The Sitetracker Data Hub (POC Input Generator) is an internal enterprise automation platform "
            "engineered to eliminate the manual, error-prone spreadsheet reconciliation workflow previously required "
            "to update contractor reports into Sitetracker (Salesforce). By pairing automated schema normalization "
            "with smart field-level delta comparison, the platform enables operators to prepare, validate, and synchronize "
            "massive weekly contractor datasets in seconds with 1-click rollback protection."
        )

        self.add_heading_2("1.1 The Business Transformation: Before vs. Now")
        self.add_body(
            "Prior to this platform, data operators spent 2 to 4 hours per report downloading baseline data, "
            "running Excel VLOOKUP formulas, manually inspecting rows, and uploading 100,000-row files through external tools. "
            "The table below summarizes the operational gains achieved:"
        )

        headers = ["Operational Dimension", "Legacy Manual Workflow", "Sitetracker Data Hub", "Business Benefit"]
        rows = [
            ["Processing Duration", "2 – 4 hours per weekly report", "Under 60 seconds (1-Click)", "95%+ operator time savings"],
            ["Human Error Rate", "High (copy-paste, date errors)", "0% programmatic errors", "Eliminates contractor rework"],
            ["Salesforce API Quota", "Uploaded entire 100k row dataset", "Uploads only modified deltas", "85%–95% API quota saved"],
            ["Rollback Capability", "Zero (native tools have no undo)", "1-Click Instant Rollback CSV", "Zero risk of live data corruption"],
            ["Audit Compliance", "Fragmented spreadsheet copies", "Standardized 5-file audit package", "100% audit & finance compliance"],
            ["Execution Mode", "Manual operator intervention", "Web UI + Automated Task Scheduler", "Unattended scheduled runs"],
        ]
        self.add_table_data(headers, rows, [1.5, 1.8, 1.8, 1.4])

        self.add_callout(
            "Core Architectural Guarantee",
            "The platform enforces strict UI-engine decoupling. All business calculations, delta comparisons, and validations "
            "can be executed headlessly via CLI (cli.py) or scheduled unattended background cron jobs without opening a web browser.",
            alert_type="NOTE"
        )

    def build_chapter_2_output_contracts(self) -> None:
        """Chapter 2: The 5 Inviolable Output Files."""
        self.add_heading_1("2. The 5 Standard Output Files (Core Data Contracts)")
        self.add_body(
            "Every run executed by the platform—whether initiated via the Guided Pipeline, Manual Dataloader, or Scheduled Task—"
            "is cryptographically isolated and saved into a dedicated timestamped folder: runs/<YYYYMMDD_HHMMSS>/. "
            "To maintain strict auditability, the engine is bound by contract to generate exactly the following 5 core files:"
        )

        headers = ["Output Filename", "File Purpose & Description", "Key Columns & Schema"]
        rows = [
            [
                "final_input_file.csv",
                "Clean, ready-to-load upload payload containing ONLY modified rows with valid Primary Keys. Zero blanks or duplicates.",
                "Primary Key (e.g. Sitetracker Job ID) + All mapped Target Sitetracker Columns"
            ],
            [
                "field_level_changes.csv",
                "Granular field-by-field audit log recording every single detected delta between source contractor data and live baseline.",
                "Primary_Key, Column, Old_Value, New_Value"
            ],
            [
                "invalid_primary_key.csv",
                "Exact replica of source rows that were quarantined and rejected because their Primary Key was null, blank, or whitespace.",
                "All Raw Source Columns (Exact copy for contractor feedback)"
            ],
            [
                "duplicate_primary_keys.csv",
                "Exact replica of source rows rejected because the Primary Key appeared multiple times in the source spreadsheet.",
                "All Raw Source Columns (Exact copy for deduplication)"
            ],
            [
                "run_summary.txt",
                "Plain text human-readable executive scorecard containing mathematical row counts, validation metrics, and duration.",
                "Total Rows Processed, Valid Records, Modified Records, Errors, Null Wipes, Execution Time"
            ],
        ]
        self.add_table_data(headers, rows, [1.6, 2.7, 2.2])

        self.add_heading_2("2.1 Supplementary Operational Files")
        self.add_bullet("audit.log:", "Thread-safe diagnostic execution log capturing detailed engine steps, SOQL queries, and API response codes.")
        self.add_bullet("rollback_file.csv:", "Auto-generated snapshot containing pre-change baseline values for 1-click disaster recovery.")
        self.add_bullet("run_summary.json:", "Structured JSON telemetry metrics consumed by the Streamlit Run History dashboard and monitoring services.")

        self.add_callout(
            "The Null-Wipe Value Rule (#N/A)",
            "To prevent contractors from accidentally erasing live Salesforce data by submitting empty spreadsheet cells, empty cells "
            "are ignored by default. If a contractor explicitly intends to wipe a field to NULL in Salesforce, they must input the exact string "
            "'#N/A'. The engine detects this token and generates an explicit empty DML payload to clear the field safely.",
            alert_type="CONTRACT"
        )

    def build_chapter_3_login_and_auth(self) -> None:
        """Chapter 3: Access & Authentication Gateway."""
        self.add_heading_1("3. Access & Authentication Gateway")
        self.add_body(
            "The Sitetracker Data Hub features an enterprise authentication gatekeeper that verifies credentials before "
            "permitting any user to access data pipelines or live Salesforce schemas."
        )

        self.add_heading_2("3.1 Server URLs & Endpoints")
        self.add_bullet("Production HTTPS Entry:", "https://161-118-182-20.sslip.io (Protected by Let's Encrypt TLS 1.3)")
        self.add_bullet("Local / Company Laptop Entry:", "http://localhost:8501 or http://localhost:8080 (via run_company_laptop_8080.sh)")

        self.add_heading_2("3.2 Authentication Methods")
        self.add_body("Operators can connect through either of two enterprise authentication mechanisms:")
        self.add_bullet("Method 1: Direct OAuth 2.0 (PKCE):", "Click 'Connect with Salesforce', log into your company SSO/OAuth portal, and grant authorization.")
        self.add_bullet("Method 2: Workbench Session Token Injection:", "For environments with strict IP restrictions or MFA tokens, paste an active Salesforce Session ID copied directly from Salesforce Workbench (workbench.developerforce.com). The token is sanitized and validated on injection.")

        self.add_heading_2("3.3 Environment Scoping: Sandbox vs. Production")
        self.add_body(
            "The Gateway provides a prominent environment toggle: Sandbox vs. Production. "
            "Always select 'Sandbox' when validating new contractor mapping rules or testing batch updates. "
            "An ambient visual badge in the top navigation bar displays your active environment at all times."
        )

        self.add_screenshot_placeholder(
            figure_num="3.1",
            title="Enterprise Login Gateway & Environment Scoping",
            target_view="Login Gateway (Default landing page when unauthenticated)",
            what_to_capture="The Login Gateway displaying the Sitetracker logo, Environment Toggle (Sandbox / Production), and Workbench Session Token input box.",
            image_filename="screenshot_1_login.png"
        )

    def build_chapter_4_home_dashboard(self) -> None:
        """Chapter 4: Main Navigation & Command Dashboard."""
        self.add_heading_1("4. Main Navigation & Command Dashboard")
        self.add_body(
            "Upon successful authentication, users arrive at the Central Command Dashboard. "
            "From here, operators can launch primary data processing pipelines or access administrative tools."
        )

        self.add_heading_2("4.1 Persistent Top Bar & Telemetry")
        self.add_bullet("Environment Badge:", "Displays current profile (e.g., 'SANDBOX: test.salesforce.com') with quick switch link.")
        self.add_bullet("Active In-Flight Banner:", "If a background upload job is actively running on the server, a prominent amber notification banner appears with a direct link to the Live Monitor.")
        self.add_bullet("Notification Bell:", "Displays in-app alert badges for completed background jobs or scheduled task alerts.")
        self.add_bullet("Profile & Logout:", "Shows connected username, instance URL, and provides a 1-click secure session termination button.")

        self.add_heading_2("4.2 Primary Operation Modules")
        self.add_bullet("📥 Guided Report Pipeline:", "For standard, recurring weekly contractor reports (e.g. Apollo 10G, Master Site Listing).")
        self.add_bullet("⚡ Ad-Hoc Object Ingestion & Mapping:", "Manual Dataloader mode for arbitrary CSV/Excel uploads to any Salesforce object.")
        self.add_bullet("📜 Run History & Audit:", "Browse historical runs, view math scorecards, and re-download past output packages.")
        self.add_bullet("📝 Schema & Mapping Editor:", "View and update Excel column mappings in the browser without server restarts.")
        self.add_bullet("📤 Salesforce Data Export:", "Manage active tokens, verify connection health, and query live schemas.")
        self.add_bullet("⏰ Task Scheduler:", "Configure unattended recurring intervals and automated SOQL delta synchronizations.")

        self.add_screenshot_placeholder(
            figure_num="4.1",
            title="Central Command Dashboard & Navigation Cards",
            target_view="Home Page (app.py)",
            what_to_capture="The main dashboard showing the Persistent Top Bar, Operation Module cards (Guided Pipeline, Ad-Hoc Loader), and Admin utilities.",
            image_filename="screenshot_2_dashboard.png"
        )

    def build_chapter_5_guided_pipeline(self) -> None:
        """Chapter 5: Guided Report Pipeline."""
        self.add_heading_1("5. Guided Report Pipeline (Pre-Configured Reports)")
        self.add_body(
            "The Guided Pipeline is the standard operating workflow for routine weekly contractor reports. "
            "It guides the operator through a standardized 4-stage Dataloader.io-style stepper wizard:"
        )

        self.add_heading_2("Stage 1: Report Selection & File Upload")
        self.add_body(
            "1. Choose the pre-configured report template from the dropdown (e.g., 'Apollo 10G', 'Master Site Listing').\n"
            "2. Drag and drop the contractor's raw source file (.csv or .xlsx).\n"
            "3. If an Excel workbook contains multiple worksheets, select the designated data sheet from the sheet dropdown.\n"
            "4. Review the raw data preview table and click 'Next: Field Mapping ➔'."
        )
        self.add_screenshot_placeholder(
            figure_num="5.1",
            title="Guided Pipeline — Stage 1: Report Selection & Upload",
            target_view="Guided Pipeline > Stage 1",
            what_to_capture="Stage 1 showing the selected report template dropdown, file upload drag-and-drop zone, and initial source data preview table.",
            image_filename="screenshot_3_guided_step1.png"
        )

        self.add_heading_2("Stage 2: Visual Field Mapping Canvas")
        self.add_body(
            "1. The engine reads Mapping_file.xlsx and config/reports/<report>.yml to pre-populate Source-to-Target column pairs.\n"
            "2. Green checkmarks indicate exact column matches; yellow badges highlight auto-suggested aliases.\n"
            "3. Operators can adjust dropdown mappings, verify Target Sitetracker field names, and click 'Next: Validation & Delta Engine ➔'."
        )
        self.add_screenshot_placeholder(
            figure_num="5.2",
            title="Guided Pipeline — Stage 2: Visual Field Mapping Canvas",
            target_view="Guided Pipeline > Stage 2",
            what_to_capture="Stage 2 showing the mapping table with Source Column, Target Salesforce Field, Data Type pill, and green checkmark indicators.",
            image_filename="screenshot_4_guided_step2.png"
        )

        self.add_heading_2("Stage 3: Delta & Validation Engine")
        self.add_body(
            "The engine executes an intensive multi-step reconciliation:\n"
            "• Baseline Pull: Automatically executes dynamic SOQL queries to fetch live Salesforce state, or accepts a baseline CSV.\n"
            "• Primary Key Validation: Quarantines missing keys to invalid_primary_key.csv.\n"
            "• Duplicate Check: Quarantines repeated keys to duplicate_primary_keys.csv.\n"
            "• Data Normalization: Cleans text strings, normalizes UK dates (DD/MM/YYYY) to ISO (YYYY-MM-DD), and checks data types.\n"
            "• Delta Comparison: Identifies rows where contractor values differ from live Salesforce state."
        )
        self.add_screenshot_placeholder(
            figure_num="5.3",
            title="Guided Pipeline — Stage 3: Delta Comparison & Validation",
            target_view="Guided Pipeline > Stage 3",
            what_to_capture="Stage 3 displaying the KPI metric cards (Total Processed, Modified Rows, Errors) and the Field-Level Differences preview grid.",
            image_filename="screenshot_5_guided_step3.png"
        )

        self.add_heading_2("Stage 4: Review, Output Downloads & 1-Click Salesforce Ingest")
        self.add_body(
            "1. Download Outputs: Click individual buttons to download final_input_file.csv, field_level_changes.csv, and error CSVs, or download the all-in-one ZIP package.\n"
            "2. Select Upload Method:\n"
            "   • REST Composite SObject Collections (~15-40 seconds for up to 5,000 rows, immediate rollback file).\n"
            "   • Bulk API 2.0 (Recommended for 10,000+ rows, server-side processing).\n"
            "3. Click 'Synchronize to Sitetracker 🚀'. The system uploads changes in micro-batches with live progress bars."
        )
        self.add_screenshot_placeholder(
            figure_num="5.4",
            title="Guided Pipeline — Stage 4: Review, Downloads & Salesforce Ingest",
            target_view="Guided Pipeline > Stage 4",
            what_to_capture="Stage 4 displaying the 5 Output File download buttons, Upload Mode selector (Composite vs Bulk 2.0), and Synchronize button.",
            image_filename="screenshot_6_guided_step4.png"
        )

    def build_chapter_6_manual_loader(self) -> None:
        """Chapter 6: Ad-Hoc Object Ingestion (Manual Dataloader)."""
        self.add_heading_1("6. Ad-Hoc Object Ingestion & Mapping (Manual Dataloader)")
        self.add_body(
            "When an operator receives an ad-hoc contractor spreadsheet for a Salesforce object that does NOT have a pre-configured "
            "report template, they use the Manual Dataloader mode. This mode dynamically inspects the live Salesforce schema."
        )

        self.add_heading_2("Step-by-Step Ad-Hoc Workflow:")
        self.add_bullet("Step 1: File Upload:", "Upload any custom CSV or Excel file.")
        self.add_bullet("Step 2: Object & Key Selection:", "The app queries describeGlobal() to list all available Salesforce objects (e.g. sitetracker__Site__c, sitetracker__Job__c). Select the Target Object and designate the Primary Key column (e.g. Id or External_Id__c).")
        self.add_bullet("Step 3: Dynamic Field Mapping:", "The UI inspects the object schema via describeSObject(). Operators match source columns to updateable Salesforce fields with fuzzy auto-matching.")
        self.add_bullet("Step 4: Live Diff & Upload with 1-Click Rollback:", "The engine queries live Salesforce values for all uploaded IDs, computes field deltas, and generates an automatic rollback file before executing updates.")

        self.add_screenshot_placeholder(
            figure_num="6.1",
            title="Manual Dataloader — Object Selection & Primary Key Designation",
            target_view="Manual Dataloader > Step 2",
            what_to_capture="Step 2 of Manual Dataloader showing the Target Object search dropdown and Primary Key selector.",
            image_filename="screenshot_7_manual_step2.png"
        )

        self.add_screenshot_placeholder(
            figure_num="6.2",
            title="Manual Dataloader — Diff Review & 1-Click Rollback Generation",
            target_view="Manual Dataloader > Step 4",
            what_to_capture="Step 4 showing the Delta Diff review grid, Download Rollback CSV button, and Upload Execution controls.",
            image_filename="screenshot_8_manual_step4.png"
        )

        self.add_callout(
            "1-Click Rollback File Guarantee",
            "Whenever updates are uploaded via Manual Dataloader mode, the engine captures the pre-change baseline state and exports "
            "a rollback_file.csv. If an operator discovers an error in contractor data post-upload, they can immediately upload this rollback file "
            "to restore the Salesforce database to its exact prior state.",
            alert_type="TIP"
        )

    def build_chapter_7_history_and_editor(self) -> None:
        """Chapter 7 & 8: Run History and Mapping Editor."""
        self.add_heading_1("7. Run History & Audit Replay")
        self.add_body(
            "Every single engine run is permanently recorded on the server. The Run History page allows operators to inspect past runs, "
            "view historical KPI metric cards, re-download output packages, and verify audit trails."
        )
        self.add_bullet("Run Table Search:", "Filter runs by report type, timestamp, or execution mode.")
        self.add_bullet("Executive KPI Cards:", "View Total Rows, Modified Records, Quarantined Errors, and Execution Duration.")
        self.add_bullet("1-Click Package Re-download:", "Download any past run's 5 standard output files or inspection inputs.")

        self.add_screenshot_placeholder(
            figure_num="7.1",
            title="Run History & Execution Audit Dashboard",
            target_view="Run History (ui/run_history.py)",
            what_to_capture="Run History table with timestamped runs, KPI metric cards, and individual file download buttons.",
            image_filename="screenshot_9_run_history.png"
        )

        self.add_heading_1("8. Interactive Schema & Mapping Editor")
        self.add_body(
            "The Mapping Editor allows administrators to inspect and update column mapping rules directly within the web interface, "
            "eliminating the need to manually open Excel on the server or restart Python processes."
        )
        self.add_bullet("Excel Column Rule Management:", "Modify Source Column aliases, Target Sitetracker fields, and data type definitions.")
        self.add_bullet("Revision History & Rollback:", "Every edit creates an automatic backup in data/mapping_history/ for safe rollbacks.")

        self.add_screenshot_placeholder(
            figure_num="8.1",
            title="Interactive Schema & Mapping Editor",
            target_view="Mapping Editor (ui/mapping_editor.py)",
            what_to_capture="Mapping Editor screen displaying editable mapping rows, data type selectors, and Save Changes button.",
            image_filename="screenshot_10_mapping_editor.png"
        )

    def build_chapter_9_scheduler_and_monitor(self) -> None:
        """Chapter 9 & 10: Task Scheduler, Telemetry & Post-Validation."""
        self.add_heading_1("9. Task Scheduler & Persistent Job Queue")
        self.add_body(
            "The Task Scheduler enables automated, unattended data reconciliation. Operators can configure jobs to run at designated "
            "future datetimes or on recurring schedules (Hourly, Daily, Weekly, Monthly)."
        )
        self.add_bullet("Timezone Precision:", "All schedules are evaluated in Europe/London timezone with daylight saving support.")
        self.add_bullet("Persistent SQLite Queue (WAL Mode):", "Job state survives server reboots. Interrupted jobs are automatically detected and marked.")
        self.add_bullet("Multi-Channel Alerting:", "Dispatches completion and failure alerts via In-App badges, SMTP Email, Slack Block Kit, and MS Teams.")

        self.add_screenshot_placeholder(
            figure_num="9.1",
            title="Task Scheduler Management Dashboard",
            target_view="Task Scheduler (ui/task_scheduler.py)",
            what_to_capture="Task Scheduler interface showing active schedule cards, interval selectors, and notification channel toggles.",
            image_filename="screenshot_11_scheduler.png"
        )

        self.add_heading_1("10. Real-Time Telemetry & Live Monitor")
        self.add_body(
            "When large uploads (10,000+ records) are submitted, they execute in the background via the Background Ingest Job Manager. "
            "The Live Monitor page provides real-time telemetry into worker execution."
        )
        self.add_bullet("Session Reconnection:", "Operators can safely close their browser; upon returning, the monitor reconnects to the active background job.")
        self.add_bullet("Chunk Progress & Metrics:", "Displays micro-batch upload velocity, success/failure counts, and Salesforce API governor limit consumption.")

        self.add_screenshot_placeholder(
            figure_num="10.1",
            title="Real-Time Telemetry & Background Ingest Monitor",
            target_view="Live Monitor (ui/live_monitor.py)",
            what_to_capture="Live Monitor showing active progress bar, processed chunks, success/error metrics, and error log viewer.",
            image_filename="screenshot_12_live_monitor.png"
        )

    def build_chapter_11_troubleshooting(self) -> None:
        """Chapter 11: Troubleshooting & Quick FAQ."""
        self.add_heading_1("11. Troubleshooting & Quick FAQ")
        self.add_body("This section outlines common operational scenarios and their rapid resolutions:")

        headers = ["Symptom / Error", "Root Cause Analysis", "Operator Resolution Action"]
        rows = [
            [
                "Rows quarantined in invalid_primary_key.csv",
                "Contractor submitted blank cells or whitespace in the designated Primary Key column.",
                "Forward invalid_primary_key.csv back to the contractor for key remediation. Valid rows can proceed immediately."
            ],
            [
                "Rows quarantined in duplicate_primary_keys.csv",
                "The same Primary Key appeared multiple times in the source spreadsheet.",
                "Review duplicate_primary_keys.csv with contractor to determine which row represents the canonical latest state."
            ],
            [
                "INVALID_SESSION_ID or Token Expired",
                "Salesforce OAuth token or Workbench session expired after 2 hours of inactivity.",
                "Click 'Logout' in the top bar, return to the Login Gateway, and reconnect via OAuth or enter a fresh Workbench token."
            ],
            [
                "Salesforce Governor Limit Alert",
                "Daily Salesforce API call limit or concurrent batch limit exceeded in the target org.",
                "Switch upload method from Bulk API 2.0 to REST Composite Collection (or pause until daily API quota resets at midnight GMT)."
            ],
            [
                "Date formatting mismatches",
                "Contractor submitted mixed UK (DD/MM/YYYY) and US/Excel serial dates.",
                "The engine normalizer handles standard UK dates automatically. For custom formats, adjust the column type in the Mapping Editor."
            ],
            [
                "Intended Blank Wipe not reflecting",
                "Contractor left the cell blank instead of entering '#N/A'.",
                "By design, blank cells do NOT erase live data. Instruct contractor to enter '#N/A' to explicitly wipe a field."
            ],
        ]
        self.add_table_data(headers, rows, [1.8, 2.3, 2.4])

    def build_chapter_12_devops_reference(self) -> None:
        """Chapter 12: Production Server & DevOps Reference."""
        self.add_heading_1("12. Production Server & DevOps Reference (For Administrators)")
        self.add_body(
            "The platform runs in production on an Oracle Cloud Ubuntu Virtual Machine. "
            "This reference provides system administrators with essential management commands:"
        )

        headers = ["Service / Resource", "Port / Protocol", "Management Command / Access Path"]
        rows = [
            ["Nginx Reverse Proxy", "Port 443 (HTTPS) & Port 80 (Redirect)", "sudo systemctl [status|restart|stop] nginx"],
            ["Streamlit Backend", "Port 8501 (Loopback 127.0.0.1)", "sudo systemctl [status|restart|stop] streamlit.service"],
            ["code-server Web IDE", "Port 8080 (Password: Sitetracker2026!)", "sudo systemctl [status|restart|stop] code-server@ubuntu.service"],
            ["SSH Remote Access", "Port 22 (SSH Key)", "ssh -i /path/to/key.key ubuntu@161.118.182.20"],
            ["Automated Git Deploy", "Cron task (/home/ubuntu/poc_input_generator)", "scripts/auto_deploy.sh"],
        ]
        self.add_table_data(headers, rows, [1.8, 1.8, 2.9])

        self.add_heading_2("12.1 Deploying Code Changes to Live Production")
        self.add_body(
            "To deploy tested updates from GitHub to the live Oracle Cloud server, execute the following sequence:\n"
            "1. SSH into the server: ssh -i <key.key> ubuntu@161.118.182.20\n"
            "2. Navigate to project: cd /home/ubuntu/poc_input_generator\n"
            "3. Pull repository changes: git pull origin main\n"
            "4. Sync Python dependencies: uv pip install -r requirements.txt\n"
            "5. Run integration tests: uv run python quick_test.py\n"
            "6. Restart web service: sudo systemctl restart streamlit.service"
        )

        self.add_callout(
            "Package Management Standard",
            "Never invoke direct 'pip' on the server. Always use Astral's 'uv' (e.g. uv pip install, uv run pytest).",
            alert_type="WARNING"
        )

    # -----------------------------------------------------------------------
    # MASTER BUILD
    # -----------------------------------------------------------------------
    def build(self) -> Path:
        """Assembles all chapters and generates the complete Word document."""
        print("Building Cover Page...")
        self.build_cover_page()

        print("Building Chapter 1: Overview & Business Impact...")
        self.build_chapter_1_overview()

        print("Building Chapter 2: The 5 Output Contracts...")
        self.build_chapter_2_output_contracts()

        print("Building Chapter 3: Access & Authentication...")
        self.build_chapter_3_login_and_auth()

        print("Building Chapter 4: Navigation & Dashboard...")
        self.build_chapter_4_home_dashboard()

        print("Building Chapter 5: Guided Report Pipeline...")
        self.build_chapter_5_guided_pipeline()

        print("Building Chapter 6: Ad-Hoc Object Ingestion...")
        self.build_chapter_6_manual_loader()

        print("Building Chapter 7 & 8: History & Mapping Editor...")
        self.build_chapter_7_history_and_editor()

        print("Building Chapter 9 & 10: Scheduler & Monitor...")
        self.build_chapter_9_scheduler_and_monitor()

        print("Building Chapter 11: Troubleshooting & FAQ...")
        self.build_chapter_11_troubleshooting()

        print("Building Chapter 12: DevOps Reference...")
        self.build_chapter_12_devops_reference()

        # Ensure output directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(self.output_path))
        print(f"✅ Successfully generated User Guide at: {self.output_path}")
        return self.output_path


def main() -> None:
    builder = UserGuideDocxBuilder(OUTPUT_DOCX_PATH)
    builder.build()


if __name__ == "__main__":
    main()
