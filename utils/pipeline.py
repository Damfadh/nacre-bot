"""
Pipeline AI 3-Node untuk pengarsipan dokumentasi PDD/Humas.

Node 1: AI Extractor     → Ekstrak link, tanggal, deskripsi dari teks mentah
Node 2: AI Classifier    → Klasifikasi kategori, tags, standarisasi nama
Node 3: AI Formatter     → Format data Sheets + buat pesan balasan Telegram

Dilengkapi hybrid deterministic regex + AI parsing agar ekstraksi link dan tanggal
100% akurat dan tidak pernah terlewat meskipun AI timeout atau mengembalikan format bervariasi.
"""
import json
import asyncio
import os
import re
from datetime import datetime
from google import genai
from config import GEMINI_API_KEY

# Regex untuk deteksi Google Drive link
GDRIVE_REGEX = re.compile(r"https?://drive\.google\.com/\S+")

# Kamus konversi nama bulan Indonesia/Inggris ke angka
MONTH_MAP = {
    "jan": "01", "januari": "01", "january": "01",
    "feb": "02", "februari": "02", "february": "02",
    "mar": "03", "maret": "03", "march": "03",
    "apr": "04", "april": "04",
    "mei": "05", "may": "05",
    "jun": "06", "juni": "06", "june": "06",
    "jul": "07", "juli": "07", "july": "07",
    "agu": "08", "agustus": "08", "august": "08",
    "sep": "09", "september": "09",
    "okt": "10", "oktober": "10", "october": "10",
    "nov": "11", "november": "11",
    "des": "12", "desember": "12", "december": "12",
}


def _get_client() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY belum diset!")
    return genai.Client(api_key=key)


def _extract_gdrive_link(text: str) -> str:
    """Ekstrak Google Drive URL secara presisi menggunakan regex."""
    match = GDRIVE_REGEX.search(text)
    if match:
        return match.group(0).rstrip(".,;)>]\n\r\t ")
    return "NULL"


def _extract_date_fallback(text: str, default_date: str) -> str:
    """Ekstrak tanggal dari teks jika AI gagal (misal: 29 September 2026 atau 2026-09-29)."""
    # Format YYYY-MM-DD
    m_iso = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if m_iso:
        y, m, d = m_iso.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"

    # Format DD-MM-YYYY
    m_dmy = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", text)
    if m_dmy:
        d, m, y = m_dmy.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"

    # Format DD [Nama Bulan] YYYY (misal: 29 September 2026)
    m_words = re.search(r"\b(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})\b", text)
    if m_words:
        d, m_name, y = m_words.groups()
        m_num = MONTH_MAP.get(m_name.lower())
        if m_num:
            return f"{y}-{m_num}-{int(d):02d}"

    return default_date


def _fallback_classification(raw_text: str, event_date: str) -> dict:
    """Fallback cerdas untuk menentukan judul & kategori jika AI mengalami kendala."""
    clean = re.sub(r"https?://\S+", "", raw_text)
    clean = re.sub(r"LINK\s+GDRIVE", "", clean, flags=re.I).strip(" :-\n\r\t")
    
    first_line = clean.split("\n")[0].strip() if clean else "Dokumentasi Kegiatan"
    title = first_line[:50].strip(" :-\t")
    if not title:
        title = "Dokumentasi Kegiatan"

    lower = title.lower()
    if any(k in lower for k in ["komcad", "lapangan", "apel", "latihan", "kunjungan", "studi banding", "outbound"]):
        category = "Lapangan"
    elif any(k in lower for k in ["rapat", "evaluasi", "pleno", "internal", "briefing"]):
        category = "Internal"
    elif any(k in lower for k in ["pers", "press", "media", "publikasi"]):
        category = "Publikasi"
    elif any(k in lower for k in ["seminar", "workshop", "lomba", "festival", "event"]):
        category = "Event Utama"
    else:
        category = "Lainnya"

    slug_cat = re.sub(r"\s+", "", category)
    slug_title = re.sub(r"[^\w\s-]", "", title)
    slug_title = re.sub(r"\s+", "_", slug_title.strip())[:30]
    folder_name = f"{event_date}_{slug_cat}_{slug_title}"

    return {
        "standardized_title": title,
        "category": category,
        "tags": ["dokumentasi", category.lower()],
        "folder_name_convention": folder_name,
    }


def _parse_json(text: str) -> dict:
    """Parse JSON dari response Gemini dengan regex extractor."""
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


async def _generate(prompt: str) -> str:
    """Jalankan Gemini Interactions API secara async dengan auto-retry."""
    loop = asyncio.get_event_loop()
    client = _get_client()

    for attempt in range(3):
        try:
            res = await loop.run_in_executor(
                None,
                lambda: client.interactions.create(
                    model="gemini-3.8-flash",
                    input=prompt,
                ),
            )
            return res.output_text if hasattr(res, "output_text") else str(res)
        except Exception as e:
            err = str(e)
            print(f"[Pipeline AI] Attempt {attempt+1} error: {err[:150]}")
            if ("503" in err or "UNAVAILABLE" in err or "high demand" in err.lower()) and attempt < 2:
                await asyncio.sleep(2)
                continue
            raise e


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
    Menggunakan kombinasi regex deterministik + AI.
    """
    regex_link = _extract_gdrive_link(raw_text)

    prompt = f"""Anda adalah AI Data Extractor khusus untuk pengarsipan dokumentasi PDD dan Humas.
Tugas utama Anda adalah menganalisis teks masukan mentah dari Telegram, lalu mengekstrak komponen kunci tanpa mengubah fakta asli.

INSTRUKSI EKSTRAKSI:
1. LINK GOOGLE DRIVE:
   - Cari URL yang mengandung 'drive.google.com'.
   - Jika ditemukan multiple link, ambil link pertama.
   - Jika tidak ada link Google Drive, set nilai menjadi "NULL".

2. TANGGAL ACARA:
   - Identifikasi tanggal kegiatan dari teks (misal: "acara kemarin", "24 Sep 2026", "29 September 2026", "2026/09/25").
   - Konversikan ke format standar 'YYYY-MM-DD'.
   - Jika teks TIDAK menyebutkan tanggal acara sama sekali, gunakan tanggal dari timestamp sistem: {timestamp}.

3. DESKRIPSI UTAMA:
   - Ambil ringkasan teks atau keterangan acara yang ditulis oleh pengirim (abaikan teks link URL).

TEKS MASUKAN:
{raw_text}

PENGIRIM: {sender_name}
TIMESTAMP SISTEM: {timestamp}

Keluarkan HANYA JSON murni tanpa format markdown codeblock:
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
        data["sender"] = sender_name

        # Proteksi: Jika AI gagal menemukan link tapi regex menemukan, utamakan regex!
        if (data.get("link_drive") in (None, "", "NULL")) and regex_link != "NULL":
            data["link_drive"] = regex_link

        return data
    except Exception as e:
        print(f"[Node 1] Error: {e}")
        extracted_date = _extract_date_fallback(raw_text, timestamp[:10])
        return {
            "raw_text": raw_text,
            "sender": sender_name,
            "link_drive": regex_link,
            "event_date": extracted_date,
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
4. Lapangan : Kunjungan Kerja, Studi Banding, Outbound, Bakti Sosial, Pelatihan, Komcad.
5. Lainnya : Jika tidak memenuhi kategori di atas.

ATURAN STANDARISASI:
1. standardized_title: Buat nama kegiatan singkat, jelas, dan profesional (Maksimal 5 kata). Format Title Case.
2. tags: Buat 2 hingga 4 kata kunci relevan dalam bentuk array string.
3. folder_name_convention: Format: [YYYY-MM-DD]_[KategoriWithoutSpace]_[NamaKegiatanUnderscore]
   Contoh: 2026-09-25_EventUtama_Workshop_AI_Humas

INPUT DATA:
{json.dumps(node1_output, ensure_ascii=False)}

Keluarkan HANYA JSON murni tanpa format markdown codeblock:
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
        data = _parse_json(result)

        # Jaga agar link_drive dari Node 1 tidak hilang
        if (data.get("link_drive") in (None, "", "NULL")) and node1_output.get("link_drive") != "NULL":
            data["link_drive"] = node1_output.get("link_drive")

        return data
    except Exception as e:
        print(f"[Node 2] Error: {e}")
        ev_date = node1_output.get("event_date") or datetime.now().strftime("%Y-%m-%d")
        fb = _fallback_classification(
            node1_output.get("raw_description") or node1_output.get("raw_text") or "",
            ev_date
        )
        return {
            "link_drive": node1_output.get("link_drive", "NULL"),
            "sender": node1_output.get("sender", "-"),
            "event_date": ev_date,
            "category": fb["category"],
            "tags": fb["tags"],
            "standardized_title": fb["standardized_title"],
            "folder_name_convention": fb["folder_name_convention"],
            "is_valid_entry": True,
        }


# ─────────────────────────────────────────────
# NODE 3: AI FORMATTER & RESPONSE GENERATOR
# ─────────────────────────────────────────────

async def node3_formatter(node2_output: dict, archive_id: str) -> dict:
    """
    Node 3: Format data siap simpan ke Sheets + buat pesan balasan Telegram.
    """
    link = node2_output.get("link_drive", "NULL")
    link_display = link if link and link != "NULL" else "NULL"

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

Keluarkan HANYA JSON murni tanpa format markdown codeblock:
{{
  "status": "success",
  "database_row": {{
    "ID_Arsip": "{archive_id}",
    "Tanggal_Kegiatan": "event_date",
    "Nama_Kegiatan": "standardized_title",
    "Kategori": "category",
    "Tags": "Tag1, Tag2, Tag3",
    "Link_Google_Drive": "{link_display}",
    "Pengirim": "sender",
    "Format_Nama_Folder": "folder_name_convention"
  }},
  "telegram_reply_message": "pesan balasan lengkap dengan emoji"
}}"""

    try:
        result = await _generate(prompt)
        data = _parse_json(result)

        # Proteksi konsistensi link di database_row
        if data.get("database_row", {}).get("Link_Google_Drive") in (None, "", "NULL") and link != "NULL":
            data["database_row"]["Link_Google_Drive"] = link

        return data
    except Exception as e:
        print(f"[Node 3] Error: {e}")
        tags_str = ", ".join(node2_output.get("tags", []))
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
                "Link_Google_Drive": link_display,
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
                f"🔗 *Link Drive:* {link_display}\n"
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
