import logging
import os
from typing import List, Optional, Set

from google.oauth2 import service_account
from googleapiclient.discovery import build
from core.google_api_utils import construct_service_account_dict


class GoogleSheetsClient:
    def __init__(self, spreadsheet_id: str):
        """
        Initialize Google Sheets client.
        
        Args:
            spreadsheet_id: The ID of the Google Sheet to interact with
        """
        if not spreadsheet_id:
            raise ValueError("spreadsheet_id must be provided")
            
        service_account_info = construct_service_account_dict()
        self.spreadsheet_id = spreadsheet_id
        self.credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets'
            ]
        )
        self.service = build('sheets', 'v4', credentials=self.credentials)
        self.sheets = self.service.spreadsheets()

    def read_batch_from_sheet(self, sheet_name: str, start_row: int, num_rows: int, num_cols: Optional[int] = None) -> List[List]:
        """
        Read a batch of rows from the specified sheet.
        
        Args:
            sheet_name: Name of the sheet to read from
            start_row: Starting row number (1-based)
            num_rows: Number of rows to read
            num_cols: Number of columns to read (optional)
        
        Returns:
            2D list of values read from the sheet
        """
        if not isinstance(start_row, int) or not isinstance(num_rows, int):
            raise ValueError("start_row and num_rows must be integers")
        if start_row < 1 or num_rows < 1:
            raise ValueError("start_row and num_rows must be positive integers")
        
        if num_cols:
            range_name = f'{sheet_name}!A{start_row}:{chr(64 + num_cols)}{start_row + num_rows - 1}'
        else:
            range_name = f'{sheet_name}!A{start_row}:ZZ{start_row + num_rows - 1}'

        result = self.sheets.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueRenderOption='FORMULA'
        ).execute()
        
        return result.get('values', [])

    def get_existing_ids(self, sheet_name: str, column_index: int) -> Set:
        """
        Get a set of existing IDs from a specific column in the sheet.
        
        Args:
            sheet_name: Name of the sheet to read from
            column_index: Column number (1-based)
        
        Returns:
            Set of non-empty values from the specified column
        """
        # Get sheet metadata to find last row
        sheet_metadata = self.sheets.get(spreadsheetId=self.spreadsheet_id).execute()
        last_row = 1
        for sheet in sheet_metadata.get('sheets', ''):
            if sheet['properties']['title'] == sheet_name:
                last_row = sheet['properties']['gridProperties']['rowCount']
                break

        if last_row < 2:
            return set()

        column_letter = chr(64 + column_index)
        range_name = f'{sheet_name}!{column_letter}2:{column_letter}{last_row}'
        
        result = self.sheets.values().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        return {row[0] for row in values if row and row[0] != ''}

    def get_sheet_id(self, sheet_name: str, create_if_missing: bool = False) -> Optional[int]:
        """
        Get the sheet ID by name, optionally creating it if it doesn't exist.
        
        Args:
            sheet_name: Name of the sheet to find
            create_if_missing: If True, create the sheet if it doesn't exist
        
        Returns:
            Sheet ID if found or created, None if not found and not created
        """
        sheet_metadata = self.sheets.get(spreadsheetId=self.spreadsheet_id).execute()
        
        for sheet in sheet_metadata.get('sheets', ''):
            if sheet['properties']['title'] == sheet_name:
                return sheet['properties']['sheetId']

        if create_if_missing:
            requests = [{
                'addSheet': {
                    'properties': {
                        'title': sheet_name
                    }
                }
            }]
            response = self.sheets.batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={'requests': requests}
            ).execute()
            return response['replies'][0]['addSheet']['properties']['sheetId']

        return None

    def get_last_row(self, sheet_name):
        """Get the last row number that contains data in the specified sheet."""
        range_name = f"'{sheet_name}'!A:A"  # adjusted range to D for the overlay script
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_name
        ).execute()
        values = result.get('values', [])
        return len(values)  # Returns 0 if sheet is empty

    def write_rows_to_sheet(self, sheet_name, rows, start_row, append_mode=False):
        """Write rows to sheet with safety checks."""
        if not rows:
            logging.warning("No rows to write")
            return

        # Get current sheet dimensions
        sheet_metadata = self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
            ranges=[f"'{sheet_name}'"],
            fields="sheets(properties(gridProperties))"
        ).execute()
        
        max_rows = sheet_metadata['sheets'][0]['properties']['gridProperties']['rowCount']
        
        # Check if we're about to exceed sheet limits
        end_row = start_row + len(rows)
        if end_row > max_rows:
            logging.error(f"Attempting to write to row {end_row} but sheet only has {max_rows} rows")
            raise ValueError("Would exceed sheet limits. Try writing fewer rows or increase sheet size.")

        # Proceed with write if safe
        range_name = f"'{sheet_name}'!A{start_row}"
        body = {'values': rows}
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()
        
    def read_cell(self, sheet_name: str, cell: str) -> Optional[str]:
        """
        Reads a specific cell from the given sheet.
        
        :param sheet_name: Name of the sheet to read from.
        :param cell: The cell to read (e.g., "A2").
        :return: The value of the cell, or None if not found.
        """
        try:
            range_name = f"{sheet_name}!{cell}"
            result = self.sheets.values().get(
                spreadsheetId=self.spreadsheet_id,
                range=range_name
            ).execute()
            values = result.get('values', [])
            return values[0][0] if values else None
        except Exception as e:
            logging.error(f"Error reading cell {cell} from sheet {sheet_name}: {str(e)}")
            return None
        