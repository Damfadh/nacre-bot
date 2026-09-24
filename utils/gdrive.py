"""
Utilitas untuk mendownload foto dari Google Drive
"""
import os
import re
import tempfile
import asyncio
import aiohttp
import gdown

GDRIVE_DIRECT_URL = "https://drive.google.com/uc?export=download&id={file_id}"


async def download_gdrive_photo(
    file_id: str,
    output_dir: str | None = None,
) -> str | None:
    """
    Download foto dari Google Drive berdasarkan file ID.

    Args:
        file_id: Google Drive file ID
        output_dir: Direktori output (default: tempdir)

    Returns:
        Path ke file yang didownload, atau None jika gagal
    """
    if output_dir is None:
        output_dir = tempfile.gettempdir()

    output_path = os.path.join(output_dir, f"gdrive_{file_id}.jpg")

    # Jalankan gdown di thread pool (blocking)
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: gdown.download(
                id=file_id,
                output=output_path,
                quiet=True,
                fuzzy=True,
            ),
        )
        if result and os.path.exists(output_path):
            return output_path
    except Exception as e:
        print(f"[GDrive] Error download {file_id}: {e}")

    return None


def extract_file_id_from_link(link: str) -> str | None:
    """Ekstrak file ID dari link Google Drive."""
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    return None


def is_valid_gdrive_link(link: str) -> bool:
    """Cek apakah link adalah Google Drive yang valid."""
    return bool(
        re.search(r"drive\.google\.com", link)
        and extract_file_id_from_link(link)
    )


def cleanup_file(path: str) -> None:
    """Hapus file temporary setelah dikirim."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
