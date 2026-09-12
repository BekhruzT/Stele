import logging
import os

from google.oauth2 import service_account
import gspread
from core.logger import Logger

logger = Logger(__name__, logging.DEBUG)

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


def get_drive_service():
    logger.log_info("Initializing Google Drive service")
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly', 'https://www.googleapis.com/auth/drive.readonly']
    create_service_account_file()
    creds = Credentials.from_service_account_file('/tmp/service-account.json', scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)
    return service


def initialize_gspread_client():
    logger.log_info("Initializing gspread client")
    create_service_account_file()
    return gspread.service_account(filename='/tmp/service-account.json')


def get_gspread_sheet(client, spreadsheet_id, sheet_name):
    logger.log_info(f"Getting sheet '{sheet_name}' from spreadsheet {spreadsheet_id}")
    sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
    return sheet

def create_service_account_file():
    """Creates the service account JSON file in /tmp/service-account.json"""
    import json
    logger.log_info("Creating service account file")
    service_account_info = construct_service_account_dict()
    
    with open('/tmp/service-account.json', 'w') as f:
        json.dump(service_account_info, f)
    logger.log_info("Service account file created at /tmp/service-account.json")


def get_google_creds():
    # Construct the service account info from environment variables
    service_account_info = construct_service_account_dict()

    # Create credentials using the service account info
    creds = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
    )
    return creds

def construct_service_account_dict():
    service_account_info = {
        "type": "service_account",
        "project_id": os.environ['GOOGLE_PROJECT_ID'],
        "private_key_id": os.environ['GOOGLE_PRIVATE_KEY_ID'],
        "private_key": f"-----BEGIN PRIVATE KEY-----\n{os.environ['GOOGLE_PRIVATE_KEY']}\n-----END PRIVATE KEY-----\n".replace("\\n", "\n"),
        "client_email": os.environ['GOOGLE_CLIENT_EMAIL'],
        "client_id": os.environ['GOOGLE_CLIENT_ID'],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.environ['GOOGLE_CLIENT_X509_CERT_URL']
    }
    
    return service_account_info