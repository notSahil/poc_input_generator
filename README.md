#pip install fastapi uvicorn requests python-dotenv streamlit
# poc_input_generator

Internal Salesforce input file generator using:
- Streamlit UI
- Python execution engine
- YAML-based report configuration
- Excel-driven mapping

## Structure
- Input_File_Portal.py – Streamlit UI
- engine/ – Processing engine
- configs/ – Per-report YAML configs
- Common/Mapping_file.xlsx – Mapping source

## Run UI
streamlit run Input_File_Portal.py

## Run Engine
python engine/input_file_engine.py --report "Master Site Listing"
