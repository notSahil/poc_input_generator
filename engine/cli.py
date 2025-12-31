import sys
from engine.input_file_engine import InputFileEngine

def main():
    if len(sys.argv) < 3 or sys.argv[1] != "--report":
        print("Usage: python engine/cli.py --report <REPORT_NAME>")
        sys.exit(1)

    report_name = sys.argv[2]
    engine = InputFileEngine(report_name)
    engine.run()

if __name__ == "__main__":
    main()
    #To Run the engine: python -m engine.cli --report <REPORT_NAME>
    #Example: python -m engine.cli --report "Apollo 10G"