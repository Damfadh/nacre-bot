"""
Pipeline AI 3-Node untuk pengarsipan dokumentasi PDD/Humas.

Node 1: AI Extractor     → Ekstrak link, tanggal, deskripsi dari teks mentah
Node 2: AI Classifier    → Klasifikasi kategori, tags, standarisasi nama
Node 3: AI Formatter     → Format data Sheets + buat pesan balasan Telegram
"""
import json
import asyncio
import os
from datetime import datetime
from google import genai
from config import GEMINI_API_KEY


def _get_client() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY belum diset!")
    return genai.Client(api_key=key)


def _parse_json(text: str) -> dict:
    """Parse JSON dari response Gemini, bersihkan markdown jika ada."""
    text = text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


async def _generate(prompt: str) -> str:
    """Jalankan Gemini Interactions API secara async di thread pool."""
    loop = asyncio.get_event_loop()
    client = _get_client()
    res = await loop.run_in_executor(
        None,
        lambda: client.interactions.create(
            model="gemini-3.8-flash",
            input=prompt,
        ),
    )
    return res.output_text if hasattr(res, "output_text") else str(res)



# ─────────────────────────────────────────────
# NODE 1: AI EXTRACTOR
# ─────────────────────────────────────────────

async def node1_extractor(
    raw_text: str,
    sender_name: str,
    timestamp: str,
) -> dict:
    """
    Node 1: Ekstrak komponen kunci dari teks mentah Telegram.
    Temperature: 0.0 (sangat presisi, tidak imajinatif)
    """
    prompt = f"""Anda adalah AI Data Extractor khusus untuk pengarsipan dokumentasi PDD dan Humas.
Tugas utama Anda adalah menganalisis teks masukan mentah dari Telegram, lalu mengekstrak komponen kunci tanpa mengubah fakta asli.

INSTRUKSI EKSTRAKSI:
1. LINK GOOGLE DRIVE:
   - Cari URL yang mengandung 'drive.google.com'.
   - Jika ditemukan multiple link, ambil link pertama.
   - Jika tidak ada link Google Drive, set nilai menjadi "NULL".

2. TANGGAL ACARA:
   - Identifikasi tanggal kegiatan dari teks (misal: "acara kemarin", "24 Sep 2026", "2026/09/25").
   - Konversikan ke format standar 'YYYY-MM-DD'.
   - Jika teks TIDAK menyebutkan tanggal acara sama sekali, gunakan tanggal dari timestamp sistem: {timestamp}.

3. DESKRIPSI UTAMA:
   - Ambil ringkasan teks atau keterangan acara yang ditulis oleh pengirim (abaikan teks link URL).

TEKS MASUKAN:
{raw_text}

PENGIRIM: {sender_name}
TIMESTAMP SISTEM: {timestamp}

Keluarkan HANYA JSON murni tanpa format markdown codeblock.

{{
  "raw_text": "isi teks asli",
  "sender": "nama pengirim",
  "link_drive": "URL atau NULL",
  "event_date": "YYYY-MM-DD",
  "raw_description": "teks deskripsi mentah"
}}"""

    try:
        result = await _generate(prompt)
        data = _parse_json(result)
        data["sender"] = sender_name  # pastikan sender benar
        return data
    except Exception as e:
        print(f"[Node 1] Error: {e}")
        return {
            "raw_text": raw_text,
            "sender": sender_name,
            "link_drive": "NULL",
            "event_date": timestamp[:10],
            "raw_description": raw_text[:200],
        }


# ─────────────────────────────────────────────
# NODE 2: AI CLASSIFIER & STANDARDIZER
# ─────────────────────────────────────────────

async def node2_classifier(node1_output: dict) -> dict:
    """
    Node 2: Klasifikasi, pelabelan, dan standarisasi nama.
    """
    prompt = f"""Anda adalah AI Taksonomi & Chief Editor PDD/Humas.
Tugas Anda adalah memproses data JSON dari Node 1, mengklasifikasikannya ke dalam taksonomi resmi organisasi, serta menyusun format penamaan folder yang terstandar.

DAFTAR KATEGORI RESMI (Pilih SATU yang paling tepat):
1. Event Utama : Seminar, Workshop, Lomba, Konferensi, Festival, Pameran.
2. Internal : Rapat, Evaluasi, Pleno, Syukuran, Briefing, Internal Gathering.
3. Publikasi : Konferensi Pers, Press Release, Media Visit, Liputan Khusus.
4. Lapangan : Kunjungan Kerja, Studi Banding, Outbound, Bakti Sosial.
5. Lainnya : Jika tidak memenuhi kategori di atas.

ATURAN STANDARISASI:
1. standardized_title: Buat nama kegiatan singkat, jelas, dan profesional (Maksimal 5 kata). Format Title Case.
2. tags: Buat 2 hingga 4 kata kunci relevan dalam bentuk array string.
3. folder_name_convention: Format: [YYYY-MM-DD]_[KategoriWithoutSpace]_[NamaKegiatanUnderscore]
   Contoh: 2026-09-25_EventUtama_Workshop_AI_Humas

INPUT DATA:
{json.dumps(node1_output, ensure_ascii=False)}

Keluarkan HANYA JSON murni tanpa format markdown codeblock.

{{
  "link_drive": "dari node 1",
  "sender": "dari node 1",
  "event_date": "YYYY-MM-DD",
  "category": "Kategori Terpilih",
  "tags": ["Tag1", "Tag2", "Tag3"],
  "standardized_title": "Nama Acara Terstruktur",
  "folder_name_convention": "Format Penamaan Folder",
  "is_valid_entry": true
}}"""

    try:
        result = await _generate(prompt)
        return _parse_json(result)
    except Exception as e:
        print(f"[Node 2] Error: {e}")
        return {
            "link_drive": node1_output.get("link_drive", "NULL"),
            "sender": node1_output.get("sender", "-"),
            "event_date": node1_output.get("event_date", datetime.now().strftime("%Y-%m-%d")),
            "category": "Lainnya",
            "tags": ["dokumentasi"],
            "standardized_title": "Dokumen Tidak Terklasifikasi",
            "folder_name_convention": f"{node1_output.get('event_date','')}_Lainnya_Dokumen",
            "is_valid_entry": True,
        }


# ─────────────────────────────────────────────
# NODE 3: AI FORMATTER & RESPONSE GENERATOR
# ─────────────────────────────────────────────

async def node3_formatter(node2_output: dict, archive_id: str) -> dict:
    """
    Node 3: Format data siap simpan ke Sheets + buat pesan balasan Telegram.
    """
    prompt = f"""Anda adalah AI Output Formatter dan Telegram Bot Responder.
Tugas Anda adalah merubah JSON dari Node 2 menjadi dua objek utama:
1. Objek data baris untuk Google Sheets.
2. Pesan teks balasan konfirmasi untuk diposting balik ke Telegram.

ATURAN BALASAN TELEGRAM:
- Gunakan bahasa Indonesia yang ramah, rapi, dan profesional.
- Gunakan emoji yang sesuai.
- Jika link_drive bernilai "NULL", berikan pesan peringatan bahwa link Google Drive tidak ditemukan.
- ID Arsip sistem: {archive_id}

INPUT DATA:
{json.dumps(node2_output, ensure_ascii=False)}

Keluarkan HANYA JSON murni tanpa format markdown codeblock.

{{
  "status": "success",
  "database_row": {{
    "ID_Arsip": "{archive_id}",
    "Tanggal_Kegiatan": "event_date",
    "Nama_Kegiatan": "standardized_title",
    "Kategori": "category",
    "Tags": "Tag1, Tag2, Tag3",
    "Link_Google_Drive": "link_drive",
    "Pengirim": "sender",
    "Format_Nama_Folder": "folder_name_convention"
  }},
  "telegram_reply_message": "pesan balasan lengkap dengan emoji"
}}"""

    try:
        result = await _generate(prompt)
        return _parse_json(result)
    except Exception as e:
        print(f"[Node 3] Error: {e}")
        tags_str = ", ".join(node2_output.get("tags", []))
        link = node2_output.get("link_drive", "NULL")
        link_text = "NULL" if link == "NULL" else link

        warning = ""
        if link == "NULL":
            warning = "\n\n⚠️ *PERHATIAN:* Link Google Drive tidak ditemukan dalam pesan!"

        return {
            "status": "success",
            "database_row": {
                "ID_Arsip": archive_id,
                "Tanggal_Kegiatan": node2_output.get("event_date", ""),
                "Nama_Kegiatan": node2_output.get("standardized_title", ""),
                "Kategori": node2_output.get("category", ""),
                "Tags": tags_str,
                "Link_Google_Drive": link_text,
                "Pengirim": node2_output.get("sender", ""),
                "Format_Nama_Folder": node2_output.get("folder_name_convention", ""),
            },
            "telegram_reply_message": (
                f"✅ *DOKUMENTASI BERHASIL DIARSIP*\n\n"
                f"🆔 *ID Arsip:* `{archive_id}`\n"
                f"📌 *Kegiatan:* {node2_output.get('standardized_title', '-')}\n"
                f"📁 *Kategori:* {node2_output.get('category', '-')}\n"
                f"📅 *Tanggal:* {node2_output.get('event_date', '-')}\n"
                f"🏷️ *Tags:* #{' #'.join(node2_output.get('tags', []))}\n"
                f"🔗 *Link Drive:* {link_text}\n"
                f"👤 *Pengirim:* {node2_output.get('sender', '-')}\n\n"
                f"💡 *Saran Nama Folder:*\n`{node2_output.get('folder_name_convention', '-')}`"
                f"{warning}"
            ),
        }


# ─────────────────────────────────────────────
# PIPELINE UTAMA
# ─────────────────────────────────────────────

async def run_pipeline(
    raw_text: str,
    sender_name: str,
    timestamp: str,
) -> dict:
    """
    Jalankan pipeline lengkap Node 1 → Node 2 → Node 3.
    Returns: output Node 3 (database_row + telegram_reply_message)
    """
    # Generate ID Arsip unik
    now = datetime.now()
    archive_id = f"DOC-{now.strftime('%Y%m%d-%H%M%S')}"

    print(f"[Pipeline] START {archive_id}")

    # Node 1
    node1 = await node1_extractor(raw_text, sender_name, timestamp)
    print(f"[Pipeline] Node 1 done: link={node1.get('link_drive')}, date={node1.get('event_date')}")

    # Node 2
    node2 = await node2_classifier(node1)
    print(f"[Pipeline] Node 2 done: category={node2.get('category')}, title={node2.get('standardized_title')}")

    # Node 3
    node3 = await node3_formatter(node2, archive_id)
    print(f"[Pipeline] Node 3 done: status={node3.get('status')}")

    return node3
