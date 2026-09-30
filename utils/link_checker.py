"""
Modul Link Checker untuk memverifikasi apakah URL dokumentasi (Google Drive, s.id, dll):
1. VALID       (🟢 Work / Siap Akses publik)
2. RESTRICTED  (🔒 Membutuhkan akses lebih / izin akses / private)
3. BROKEN      (🔴 Rusak / 404 / file dihapus / timeout)
"""
import asyncio
import aiohttp
from typing import Optional

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

STATUS_ICONS = {
    "VALID": "🟢",
    "RESTRICTED": "🔒",
    "BROKEN": "🔴",
    "UNKNOWN": "⚪",
}

STATUS_LABELS = {
    "VALID": "Work (Siap Akses)",
    "RESTRICTED": "Butuh Akses (Restricted)",
    "BROKEN": "Rusak / Tidak Ditemukan",
    "UNKNOWN": "Belum Dicek",
}

RESTRICTED_KEYWORDS = [
    "anda memerlukan akses",
    "you need access",
    "minta akses",
    "request access",
    "you need permission",
    "perlu izin",
    "sharing/request-access",
    "drive-permission-denied",
    "accounts.google.com/servicelogin",
    "servicelogin?continue",
]

BROKEN_KEYWORDS = [
    "file does not exist",
    "file tidak ada",
    "item does not exist",
    "item tidak ditemukan",
    "ada di sampah",
    "in trash",
    "url tidak valid",
    "invalid url",
]


async def check_single_link(
    session: aiohttp.ClientSession,
    url: str,
    timeout_sec: float = 8.0,
) -> dict:
    """
    Cek status satu URL secara async.
    Returns dict: {url, status, detail, icon, label, final_url}
    """
    clean_url = url.strip()
    if not clean_url or not clean_url.startswith("http"):
        return {
            "url": clean_url,
            "status": "BROKEN",
            "detail": "URL Tidak Valid",
            "icon": STATUS_ICONS["BROKEN"],
            "label": STATUS_LABELS["BROKEN"],
            "final_url": clean_url,
        }

    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with session.get(clean_url, headers=DEFAULT_HEADERS, allow_redirects=True, timeout=timeout) as resp:
            final_url = str(resp.url)
            status_code = resp.status

            # 1. Cek redirect ke Google Login (Restricted / Private)
            if "accounts.google.com" in final_url and (
                "servicelogin" in final_url.lower() or "signin" in final_url.lower()
            ):
                return {
                    "url": clean_url,
                    "status": "RESTRICTED",
                    "detail": "Membutuhkan Akses Tambahan (Login Diperlukan)",
                    "icon": STATUS_ICONS["RESTRICTED"],
                    "label": STATUS_LABELS["RESTRICTED"],
                    "final_url": final_url,
                }

            # 2. Cek status code HTTP
            if status_code in (404, 410):
                return {
                    "url": clean_url,
                    "status": "BROKEN",
                    "detail": f"Tidak Ditemukan (HTTP {status_code})",
                    "icon": STATUS_ICONS["BROKEN"],
                    "label": STATUS_LABELS["BROKEN"],
                    "final_url": final_url,
                }
            elif status_code in (401, 403):
                return {
                    "url": clean_url,
                    "status": "RESTRICTED",
                    "detail": f"Akses Ditolak / Dibatasi (HTTP {status_code})",
                    "icon": STATUS_ICONS["RESTRICTED"],
                    "label": STATUS_LABELS["RESTRICTED"],
                    "final_url": final_url,
                }
            elif status_code >= 500:
                return {
                    "url": clean_url,
                    "status": "BROKEN",
                    "detail": f"Server Error (HTTP {status_code})",
                    "icon": STATUS_ICONS["BROKEN"],
                    "label": STATUS_LABELS["BROKEN"],
                    "final_url": final_url,
                }

            # 3. Baca sebagian isi HTML untuk memeriksa kata kunci khusus Google Drive
            content_bytes = await resp.content.read(30000)
            content_lower = content_bytes.decode("utf-8", errors="ignore").lower()

            for kw in RESTRICTED_KEYWORDS:
                if kw in content_lower:
                    return {
                        "url": clean_url,
                        "status": "RESTRICTED",
                        "detail": "Membutuhkan Akses Tambahan (Request Access)",
                        "icon": STATUS_ICONS["RESTRICTED"],
                        "label": STATUS_LABELS["RESTRICTED"],
                        "final_url": final_url,
                    }

            for kw in BROKEN_KEYWORDS:
                if kw in content_lower:
                    return {
                        "url": clean_url,
                        "status": "BROKEN",
                        "detail": "File / Folder Tidak Ditemukan",
                        "icon": STATUS_ICONS["BROKEN"],
                        "label": STATUS_LABELS["BROKEN"],
                        "final_url": final_url,
                    }

            return {
                "url": clean_url,
                "status": "VALID",
                "detail": "Aktif & Siap Diakses",
                "icon": STATUS_ICONS["VALID"],
                "label": STATUS_LABELS["VALID"],
                "final_url": final_url,
            }

    except asyncio.TimeoutError:
        return {
            "url": clean_url,
            "status": "BROKEN",
            "detail": f"Koneksi Timeout ({timeout_sec:.0f}s)",
            "icon": STATUS_ICONS["BROKEN"],
            "label": STATUS_LABELS["BROKEN"],
            "final_url": clean_url,
        }
    except Exception as e:
        err_msg = str(e)[:35]
        return {
            "url": clean_url,
            "status": "BROKEN",
            "detail": f"Gagal Terhubung ({err_msg})",
            "icon": STATUS_ICONS["BROKEN"],
            "label": STATUS_LABELS["BROKEN"],
            "final_url": clean_url,
        }


async def check_links_batch(
    urls: list[str],
    max_concurrent: int = 15,
    timeout_sec: float = 8.0,
) -> list[dict]:
    """
    Cek banyak link sekaligus secara concurrent dan cepat.
    """
    if not urls:
        return []

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _sem_check(session, u):
        async with semaphore:
            return await check_single_link(session, u, timeout_sec=timeout_sec)

    connector = aiohttp.TCPConnector(ssl=False, limit=max_concurrent + 5)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [_sem_check(session, u) for u in urls]
        return await asyncio.gather(*tasks)


async def check_single_url(url: str, timeout_sec: float = 8.0) -> dict:
    """Helper praktis untuk mengecek satu URL secara independen."""
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        return await check_single_link(session, url, timeout_sec=timeout_sec)
