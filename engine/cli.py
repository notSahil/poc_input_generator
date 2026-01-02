import sys
from engine.input_file_engine import InputFileEngine

def main():
    if len(sys.argv) < 3 or sys.argv[1] != "--report": #If the arguments are not passed correctly it will stop the code [engine, --report, <REPORT_NAME>]
        print("Usage: python -m engine.cli --report <REPORT_NAME>") #Example of failure Entered command without report name
        sys.exit(1)

    report_name = sys.argv[2]
    engine = InputFileEngine(report_name) #calling the constructor - Initlializing the class with report name
    engine.run() #running the main fun.

if __name__ == "__main__":
    main()
    #To Run the engine: python -m engine.cli --report <REPORT_NAME>
    #Example: python -m engine.cli --report "Apollo 10G"
    