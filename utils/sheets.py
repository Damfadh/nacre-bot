"""
Integrasi Google Sheets untuk penyimpanan arsip dokumentasi.
Menggunakan Service Account JSON untuk autentikasi.
"""
import asyncio
import os
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials
from config import SHEETS_ID, SHEETS_CREDENTIALS_FILE

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Header kolom sesuai blueprint
HEADERS = [
    "ID_Arsip",
    "Tanggal_Kegiatan",
    "Nama_Kegiatan",
    "Kategori",
    "Tags",
    "Link_Google_Drive",
    "Pengirim",
    "Format_Nama_Folder",
    "Waktu_Input",
]

_client: Optional[gspread.Client] = None
_sheet: Optional[gspread.Worksheet] = None


def get_sheet() -> gspread.Worksheet:
    """Singleton: ambil worksheet Google Sheets."""
    global _client, _sheet

    if _sheet is not None:
        return _sheet

    # Autentikasi menggunakan service account JSON
    creds = Credentials.from_service_account_file(
        SHEETS_CREDENTIALS_FILE, scopes=SCOPES
    )
    _client = gspread.authorize(creds)
    spreadsheet = _client.open_by_key(SHEETS_ID)

    # Ambil sheet pertama (atau buat jika belum ada)
    try:
        _sheet = spreadsheet.worksheet("Arsip Dokumentasi")
    except gspread.WorksheetNotFound:
        _sheet = spreadsheet.add_worksheet(
            title="Arsip Dokumentasi", rows=1000, cols=len(HEADERS)
        )
        # Buat header
        _sheet.append_row(HEADERS, value_input_option="RAW")

    return _sheet


async def append_archive_row(database_row: dict) -> bool:
    """
    Tambahkan baris baru ke Google Sheets (Action A dari blueprint).
    Returns True jika berhasil.
    """
    loop = asyncio.get_event_loop()
    try:
        def _append():
            sheet = get_sheet()
            row = [
                database_row.get("ID_Arsip", ""),
                database_row.get("Tanggal_Kegiatan", ""),
                database_row.get("Nama_Kegiatan", ""),
                database_row.get("Kategori", ""),
                database_row.get("Tags", ""),
                database_row.get("Link_Google_Drive", ""),
                database_row.get("Pengirim", ""),
                database_row.get("Format_Nama_Folder", ""),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # Waktu_Input
            ]
            sheet.append_row(row, value_input_option="USER_ENTERED")
            return True

        return await loop.run_in_executor(None, _append)

    except Exception as e:
        print(f"[Sheets] Error append row: {e}")
        return False


async def search_archives(keyword: str) -> list[dict]:
    """
    Cari arsip di Google Sheets berdasarkan keyword.
    Mencari di kolom: Nama_Kegiatan, Tags, Kategori.
    """
    loop = asyncio.get_event_loop()
    try:
        def _search():
            sheet = get_sheet()
            all_records = sheet.get_all_records()
            keyword_lower = keyword.lower()
            results = []
            for record in all_records:
                searchable = " ".join([
                    str(record.get("Nama_Kegiatan", "")),
                    str(record.get("Tags", "")),
                    str(record.get("Kategori", "")),
                ]).lower()
                if keyword_lower in searchable:
                    results.append(record)
            return results

        return await loop.run_in_executor(None, _search)

    except Exception as e:
        print(f"[Sheets] Error search: {e}")
        return []


def is_sheets_configured() -> bool:
    """Cek apakah Google Sheets sudah dikonfigurasi."""
    return bool(
        SHEETS_ID
        and SHEETS_CREDENTIALS_FILE
        and os.path.exists(SHEETS_CREDENTIALS_FILE)
    )
