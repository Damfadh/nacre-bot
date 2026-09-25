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


# ─────────────────────────────────────────────
# AUDIT: Multi-Tab Support
# ─────────────────────────────────────────────

AUDIT_TABS = {
    "valid": "ACTIVE_VALID",
    "duplicate": "DUPLICATE",
    "broken": "BROKEN_RESTRICTED",
}

AUDIT_HEADERS = {
    "valid": ["Kategori", "Judul", "Tanggal_Kegiatan", "Link_Google_Drive", "Pengirim", "Tags"],
    "duplicate": ["Link_Google_Drive", "Pengirim", "Nama_Kegiatan", "Tanggal"],
    "broken": ["Link_Google_Drive", "Issue_Type", "Pengirim"],
}


def _get_or_create_tab(
    spreadsheet: gspread.Spreadsheet,
    tab_name: str,
    headers: list[str],
) -> gspread.Worksheet:
    """Ambil atau buat tab worksheet dengan header."""
    try:
        ws = spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="RAW")
    return ws


async def write_audit_results(audit_result: dict) -> bool:
    """
    Tulis hasil audit ke 3 tab Google Sheets:
    - ACTIVE_VALID : link valid & aktif, sudah dikategorikan
    - DUPLICATE    : link duplikat
    - BROKEN_RESTRICTED : link error/restricted

    Returns True jika berhasil.
    """
    loop = asyncio.get_event_loop()
    try:
        def _write():
            creds = Credentials.from_service_account_file(
                SHEETS_CREDENTIALS_FILE, scopes=SCOPES
            )
            client = gspread.authorize(creds)
            spreadsheet = client.open_by_key(SHEETS_ID)

            # ── Tab ACTIVE_VALID ──
            ws_valid = _get_or_create_tab(
                spreadsheet, AUDIT_TABS["valid"], AUDIT_HEADERS["valid"]
            )
            # Clear lama (keep header baris 1)
            ws_valid.resize(rows=1)
            rows_valid = []
            for cat_group in audit_result.get("categorized_valid_data", []):
                category = cat_group.get("category", "Lainnya")
                for item in cat_group.get("items", []):
                    rows_valid.append([
                        category,
                        item.get("title", "-"),
                        item.get("event_date", "-"),
                        item.get("link_drive", "-"),
                        item.get("sender", "-"),
                        item.get("tags", "-"),
                    ])
            if rows_valid:
                ws_valid.append_rows(rows_valid, value_input_option="USER_ENTERED")

            # ── Tab DUPLICATE ──
            ws_dup = _get_or_create_tab(
                spreadsheet, AUDIT_TABS["duplicate"], AUDIT_HEADERS["duplicate"]
            )
            ws_dup.resize(rows=1)
            meta = audit_result.get("_meta", {})
            rows_dup = [
                [
                    d.get("link_drive", "-"),
                    d.get("sender", "-"),
                    d.get("original_text", "-"),
                    d.get("event_date", "-"),
                ]
                for d in meta.get("duplicate_items", [])
            ]
            if rows_dup:
                ws_dup.append_rows(rows_dup, value_input_option="USER_ENTERED")

            # ── Tab BROKEN_RESTRICTED ──
            ws_broken = _get_or_create_tab(
                spreadsheet, AUDIT_TABS["broken"], AUDIT_HEADERS["broken"]
            )
            ws_broken.resize(rows=1)
            rows_broken = [
                [
                    b.get("link_drive", "-"),
                    b.get("issue_type", "UNKNOWN"),
                    b.get("sender", "-"),
                ]
                for b in audit_result.get("broken_or_restricted_list", [])
            ]
            if rows_broken:
                ws_broken.append_rows(rows_broken, value_input_option="USER_ENTERED")

            return True

        return await loop.run_in_executor(None, _write)

    except Exception as e:
        print(f"[Sheets Audit] Error: {e}")
        return False


async def get_all_archive_records() -> list[dict]:
    """
    Ambil semua record dari tab 'Arsip Dokumentasi' untuk diaudit.
    Returns list of dicts dengan key = nama kolom header.
    """
    loop = asyncio.get_event_loop()
    try:
        def _fetch():
            creds = Credentials.from_service_account_file(
                SHEETS_CREDENTIALS_FILE, scopes=SCOPES
            )
            client = gspread.authorize(creds)
            spreadsheet = client.open_by_key(SHEETS_ID)
            try:
                ws = spreadsheet.worksheet("Arsip Dokumentasi")
                return ws.get_all_records()
            except gspread.WorksheetNotFound:
                return []

        return await loop.run_in_executor(None, _fetch)

    except Exception as e:
        print(f"[Sheets] Error get_all_archive_records: {e}")
        return []

