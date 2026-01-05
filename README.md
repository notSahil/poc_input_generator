#pip install fastapi uvicorn requests python-dotenv streamlit
# poc_input_generator

Internal Salesforce input file generator using:
- Streamlit UI
- Python execution engine
- YAML-based report configuration
- Excel-driven mapping

## Structure
- app.py – Streamlit UI
- engine/ – Processing Source and Sitetracker Data
- configs/ – Per-report YAML configs
- Common/Mapping_file.xlsx – Mapping source

## Run UI
streamlit run app.py

## Run Engine
python -m engine.cli --report "Master Site Listing"
