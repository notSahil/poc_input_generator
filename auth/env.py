from dotenv import load_dotenv
import os

load_dotenv()  # reads .env file

SF_CLIENT_ID = os.getenv("SF_CLIENT_ID")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET")
SF_REDIRECT_URI = os.getenv("SF_REDIRECT_URI")
SF_LOGIN_URL = os.getenv("SF_LOGIN_URL")

if not all([SF_CLIENT_ID, SF_CLIENT_SECRET, SF_REDIRECT_URI, SF_LOGIN_URL]):
    raise RuntimeError("Missing Salesforce OAuth environment variables")