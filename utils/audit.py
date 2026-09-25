"""
Pipeline Audit Channel: 3-Node sistem untuk audit massal link Google Drive.

Node 1: Deduplication & Link Extractor
Node 2: HTTP Link Validator (status check)
Node 3: AI Categorizer & Sorting Engine
"""
import asyncio
import json
import re
from datetime import datetime
from typing import Optional

import aiohttp
import google.generativeai as genai
from config import GEMINI_API_KEY

genai.configure(api_key=GEMINI_API_KEY)

# Regex untuk ekstrak Google Drive URL
GDRIVE_REGEX = re.compile(r"https?://drive\.google\.com/\S+")

# Timeout untuk HTTP check
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Max concurrent requests
MAX_CONCURRENT = 10


# ─────────────────────────────────────────────
# NODE 1: DEDUPLICATION & LINK EXTRACTOR
# ─────────────────────────────────────────────

def node1_deduplicator(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Node 1: Ekstrak semua URL Google Drive dari records, deteksi duplikat.

    Args:
        records: List dict dari Google Sheets (field: Link_Google_Drive, Pengirim, dll)

    Returns:
        (unique_items, duplicate_items)
    """
    seen_links: dict[str, dict] = {}
    duplicates: list[dict] = []

    for record in records:
        link = str(record.get("Link_Google_Drive", "")).strip()

        # Skip jika kosong atau NULL
        if not link or link.upper() == "NULL" or not link.startswith("http"):
            continue

        # Normalisasi link (hapus trailing slash, query params kecil)
        link_clean = link.split("?")[0].rstrip("/")

        if link_clean in seen_links:
            # Duplikat ditemukan
            duplicates.append({
                "link_drive": link,
                "sender": record.get("Pengirim", "-"),
                "original_text": record.get("Nama_Kegiatan", "-"),
                "event_date": record.get("Tanggal_Kegiatan", "-"),
                "status": "DUPLICATE",
            })
        else:
            seen_links[link_clean] = {
                "link_drive": link,
                "sender": record.get("Pengirim", "-"),
                "original_text": record.get("Nama_Kegiatan", "-"),
                "event_date": record.get("Tanggal_Kegiatan", "-"),
                "tags": record.get("Tags", "-"),
                "kategori": record.get("Kategori", "-"),
                "status": "UNIQUE",
            }

    unique_items = list(seen_links.values())
    print(f"[Node 1] Unique: {len(unique_items)}, Duplikat: {len(duplicates)}")
    return unique_items, duplicates


# ─────────────────────────────────────────────
# NODE 2: HTTP LINK VALIDATOR
# ─────────────────────────────────────────────

async def _check_single_link(session: aiohttp.ClientSession, item: dict) -> dict:
    """Cek status HTTP satu link Google Drive."""
    url = item["link_drive"]
    try:
        async with session.get(url, allow_redirects=True) as resp:
            code = resp.status
            if code == 200:
                http_status = "VALID"
                issue_type = None
            elif code in (404, 410):
                http_status = "BROKEN"
                issue_type = f"HTTP_{code}_NOT_FOUND"
            elif code in (403, 401):
                http_status = "RESTRICTED"
                issue_type = "ACCESS_DENIED"
            else:
                http_status = "BROKEN"
                issue_type = f"HTTP_{code}"
    except asyncio.TimeoutError:
        http_status = "BROKEN"
        issue_type = "TIMEOUT"
    except Exception as e:
        http_status = "BROKEN"
        issue_type = f"ERROR: {str(e)[:50]}"

    return {**item, "http_status": http_status, "issue_type": issue_type}


async def node2_link_validator(unique_items: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Node 2: Cek status HTTP setiap link secara concurrent.

    Returns:
        (valid_items, broken_restricted_items)
    """
    if not unique_items:
        return [], []

    # Semaphore untuk batasi concurrent requests
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _check_with_semaphore(session, item):
        async with semaphore:
            return await _check_single_link(session, item)

    print(f"[Node 2] Mengecek {len(unique_items)} link...")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT, connector=connector) as session:
        tasks = [_check_with_semaphore(session, item) for item in unique_items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_items = []
    broken_items = []

    for result in results:
        if isinstance(result, Exception):
            continue
        if result["http_status"] == "VALID":
            valid_items.append(result)
        else:
            broken_items.append(result)

    print(f"[Node 2] Valid: {len(valid_items)}, Broken/Restricted: {len(broken_items)}")
    return valid_items, broken_items


# ─────────────────────────────────────────────
# NODE 3: AI CATEGORIZER & SORTING ENGINE
# ─────────────────────────────────────────────

async def _categorize_batch(model, batch: list[dict], total_stats: dict) -> dict:
    """Kategorikan satu batch item dengan Gemini."""
    loop = asyncio.get_event_loop()

    prompt = f"""Anda adalah AI Auditor Database Dokumentasi PDD/Humas.
Tugas Anda adalah memproses array data link yang telah dibersihkan dari duplikasi dan diperiksa status HTTP-nya, kemudian mengelompokkan link yang VALID ke dalam kategori resmi serta menyusun laporan ringkasan.

DAFTAR KATEGORI RESMI:
- Event Utama (Seminar, Workshop, Lomba, Konferensi, Festival)
- Internal (Rapat, Evaluasi, Pleno, Syukuran, Briefing)
- Publikasi (Konferensi Pers, Press Release, Media Visit)
- Lapangan (Kunjungan Kerja, Studi Banding, Outbound)
- Lainnya (Jika tidak relevan dengan kategori di atas)

INSTRUKSI SORTING:
1. Hanya proses item dengan status HTTP = "VALID".
2. Kelompokkan item berdasarkan "category".
3. Urutkan berdasarkan "event_date" dari yang terbaru ke yang tertua.
4. Buat laporan ringkasan (Audit Summary) yang akan dikirimkan ke Admin Telegram.

STATISTIK KESELURUHAN:
{json.dumps(total_stats, ensure_ascii=False)}

INPUT DATA (hanya item VALID):
{json.dumps(batch, ensure_ascii=False)}

Keluarkan HANYA JSON murni tanpa format markdown codeblock.

{{
  "categorized_valid_data": [
    {{
      "category": "Event Utama",
      "items": [
        {{
          "title": "nama kegiatan",
          "event_date": "YYYY-MM-DD",
          "link_drive": "https://...",
          "sender": "@pengirim",
          "tags": "tag1, tag2"
        }}
      ]
    }}
  ],
  "telegram_report_message": "pesan laporan lengkap dengan emoji dan format Markdown"
}}"""

    response = await loop.run_in_executor(
        None,
        lambda: model.generate_content(prompt)
    )
    text = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)


async def node3_ai_categorizer(
    valid_items: list[dict],
    duplicate_items: list[dict],
    broken_items: list[dict],
) -> dict:
    """
    Node 3: AI kategorisasi dan buat laporan ringkasan.
    Proses batch jika >50 item.
    """
    import os
    key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if key:
        genai.configure(api_key=key)

    model = genai.GenerativeModel(
        model_name="gemini-3.8-flash",
        generation_config=genai.GenerationConfig(temperature=0.1),
    )

    total_stats = {
        "total_processed": len(valid_items) + len(duplicate_items) + len(broken_items),
        "valid_links_count": len(valid_items),
        "duplicate_links_count": len(duplicate_items),
        "broken_restricted_count": len(broken_items),
    }

    # Fallback jika tidak ada item valid
    if not valid_items:
        return _build_fallback_report(total_stats, [], duplicate_items, broken_items)

    try:
        # Proses dalam batch jika banyak item
        BATCH_SIZE = 50
        all_categorized = []

        if len(valid_items) <= BATCH_SIZE:
            result = await _categorize_batch(model, valid_items, total_stats)
            all_categorized = result.get("categorized_valid_data", [])
            telegram_msg = result.get("telegram_report_message", "")
        else:
            # Multi-batch: merge hasil
            telegram_msg = ""
            for i in range(0, len(valid_items), BATCH_SIZE):
                batch = valid_items[i:i + BATCH_SIZE]
                batch_result = await _categorize_batch(model, batch, total_stats)
                batch_cats = batch_result.get("categorized_valid_data", [])

                # Merge ke all_categorized
                for bc in batch_cats:
                    existing = next(
                        (c for c in all_categorized if c["category"] == bc["category"]),
                        None
                    )
                    if existing:
                        existing["items"].extend(bc.get("items", []))
                    else:
                        all_categorized.append(bc)

            # Generate laporan dari batch terakhir
            telegram_msg = _build_telegram_report(total_stats, all_categorized, broken_items)

        return {
            "audit_summary": total_stats,
            "categorized_valid_data": all_categorized,
            "broken_or_restricted_list": [
                {
                    "link_drive": b.get("link_drive", "-"),
                    "issue_type": b.get("issue_type", "UNKNOWN"),
                    "sender": b.get("sender", "-"),
                }
                for b in broken_items
            ],
            "telegram_report_message": telegram_msg or _build_telegram_report(
                total_stats, all_categorized, broken_items
            ),
        }

    except Exception as e:
        print(f"[Node 3] AI Error: {e}")
        return _build_fallback_report(total_stats, valid_items, duplicate_items, broken_items)


def _build_telegram_report(stats: dict, categorized: list, broken: list) -> str:
    """Buat pesan laporan Telegram dari data audit."""
    now = datetime.now().strftime("%d %b %Y %H:%M")
    lines = [
        f"🧹 *LAPORAN AUDIT & PENYORTIRAN CHANNEL*",
        f"📅 _{now}_",
        "─" * 40,
        f"📊 *Ringkasan Hasil Scan:*",
        f"• Total Diperiksa: `{stats['total_processed']}`",
        f"• Link Valid & Aktif: `{stats['valid_links_count']}`",
        f"• Link Duplikat (Dieliminasi): `{stats['duplicate_links_count']}`",
        f"• Link Error/Restricted: `{stats['broken_restricted_count']}`",
    ]

    if broken:
        lines.append("")
        lines.append("─" * 40)
        lines.append("⚠️ *TINDAKAN DIPERLUKAN (LINK ERROR/RESTRICTED):*")
        for i, b in enumerate(broken[:10], 1):
            issue = b.get("issue_type", "ERROR")
            sender = b.get("sender", "-")
            link = b.get("link_drive", "-")
            lines.append(f"{i}. 🔗 [Link Drive]({link}) — *{issue}* (Pengirim: {sender})")
        if len(broken) > 10:
            lines.append(f"_...dan {len(broken) - 10} link lainnya._")

    lines.append("")
    lines.append("─" * 40)
    lines.append("✅ *UPDATE DATABASE:*")
    lines.append(
        f"Semua data valid ({stats['valid_links_count']} link) telah disortir "
        "dan dimasukkan ke Google Sheets berdasarkan kategorinya."
    )

    return "\n".join(lines)


def _build_fallback_report(stats, valid_items, duplicate_items, broken_items) -> dict:
    """Fallback jika AI error: buat laporan manual."""
    categorized = [{"category": "Lainnya", "items": [
        {
            "title": v.get("original_text", "-"),
            "event_date": v.get("event_date", "-"),
            "link_drive": v.get("link_drive", "-"),
            "sender": v.get("sender", "-"),
            "tags": v.get("tags", "-"),
        }
        for v in valid_items
    ]}] if valid_items else []

    return {
        "audit_summary": stats,
        "categorized_valid_data": categorized,
        "broken_or_restricted_list": [
            {"link_drive": b["link_drive"], "issue_type": b.get("issue_type", "-"), "sender": b["sender"]}
            for b in broken_items
        ],
        "telegram_report_message": _build_telegram_report(stats, categorized, broken_items),
    }


# ─────────────────────────────────────────────
# PIPELINE UTAMA
# ─────────────────────────────────────────────

async def run_audit_pipeline(records: list[dict]) -> dict:
    """
    Jalankan pipeline audit lengkap: Node 1 → Node 2 → Node 3.

    Args:
        records: List record dari Google Sheets (tab Arsip Dokumentasi)

    Returns:
        Dict lengkap dengan audit_summary, categorized_valid_data,
        broken_or_restricted_list, telegram_report_message,
        dan metadata: unique_items, duplicate_items, broken_items
    """
    print(f"[Audit] START — {len(records)} records")

    # Node 1: Deduplikasi
    unique_items, duplicate_items = node1_deduplicator(records)

    # Node 2: Validasi HTTP
    valid_items, broken_items = await node2_link_validator(unique_items)

    # Node 3: AI Kategorisasi
    result = await node3_ai_categorizer(valid_items, duplicate_items, broken_items)

    # Tambahkan metadata raw
    result["_meta"] = {
        "unique_items": unique_items,
        "duplicate_items": duplicate_items,
        "broken_items": broken_items,
        "valid_items": valid_items,
    }

    print(f"[Audit] DONE — Valid: {len(valid_items)}, Dup: {len(duplicate_items)}, Broken: {len(broken_items)}")
    return result
