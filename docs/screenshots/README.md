# Sitetracker Data Hub — Screenshots Directory

This directory holds screenshots for the **Sitetracker Data Hub Enterprise User Guide** (`docs/Sitetracker_Data_Hub_User_Guide.docx`).

## Two Ways to Add Screenshots to Your Document

### Option 1: Direct in Microsoft Word (Easiest)
1. Open [`docs/Sitetracker_Data_Hub_User_Guide.docx`](file:///Users/sahilkumar/Documents/Projects/poc_input_generator/docs/Sitetracker_Data_Hub_User_Guide.docx) in Microsoft Word.
2. In each section, you will see a prominent blue-bordered box: `📷 [PASTE SCREENSHOT HERE]`.
3. Simply click the box, press **Delete**, and press **Ctrl+V / Cmd+V** to paste your screenshot!

---

### Option 2: Drop Images Here & Auto-Generate
Save your screenshot PNG files in this folder using the filenames below, then re-run:
```bash
uv run python scripts/generate_user_guide_docx.py
```
The script will automatically detect the files and embed them seamlessly into the Word document at high resolution!

| Filename | Figure | View / Screen to Capture |
|---|---|---|
| `screenshot_1_login.png` | Figure 3.1 | **Login Gateway**: Environment toggle (Sandbox vs Prod), Workbench Session Token input |
| `screenshot_2_dashboard.png` | Figure 4.1 | **Central Dashboard**: Persistent Top Bar, Operation Module cards, active job banner |
| `screenshot_3_guided_step1.png` | Figure 5.1 | **Guided Pipeline Stage 1**: Report template selector, file upload area, source data preview |
| `screenshot_4_guided_step2.png` | Figure 5.2 | **Guided Pipeline Stage 2**: Visual mapping canvas with Source-to-Target column pairings |
| `screenshot_5_guided_step3.png` | Figure 5.3 | **Guided Pipeline Stage 3**: Delta comparison metrics, field differences grid |
| `screenshot_6_guided_step4.png` | Figure 5.4 | **Guided Pipeline Stage 4**: 5 Output download buttons, upload mode selector, Ingest button |
| `screenshot_7_manual_step2.png` | Figure 6.1 | **Manual Dataloader Step 2**: Target SObject search dropdown and Primary Key selector |
| `screenshot_8_manual_step4.png` | Figure 6.2 | **Manual Dataloader Step 4**: Diff review table, Rollback CSV button, upload controls |
| `screenshot_9_run_history.png` | Figure 7.1 | **Run History**: Table of past runs, KPI metric cards, download package buttons |
| `screenshot_10_mapping_editor.png` | Figure 8.1 | **Mapping Editor**: Schema mapping table, type selectors, Save Changes button |
| `screenshot_11_scheduler.png` | Figure 9.1 | **Task Scheduler**: Active schedule cards, recurrence interval, notification toggles |
| `screenshot_12_live_monitor.png` | Figure 10.1 | **Live Monitor**: In-flight worker progress bar, chunks processed, governor limit gauge |
