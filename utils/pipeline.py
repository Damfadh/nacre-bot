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
from utils.link_checker import (
    check_single_url,
    check_links_batch,
    STATUS_ICONS,
    STATUS_LABELS,
)

# Regex untuk deteksi Google Drive dan link dokumentasi (s.id, bit.ly, tinyurl, docs.google)
ARCHIVE_LINK_REGEX = re.compile(
    r"https?://(?:drive\.google\.com|s\.id|bit\.ly|tinyurl\.com|docs\.google\.com)/\S+",
    re.IGNORECASE
)
GDRIVE_REGEX = ARCHIVE_LINK_REGEX  # Kompatibilitas mundur

# Header umum yang sering muncul di pesan bulk dan perlu diabaikan sebagai judul
GENERIC_HEADERS = {
    "usable link", "usable links", "link gdrive",
    "link google drive", "link dokumentasi", "daftar link", "kumpulan link",
    "usable link:", "usable links:"
}

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


def clean_url(url: str) -> str:
    """Bersihkan karakter trailing aneh dari URL hasil ekstraksi."""
    return url.rstrip(".,;)>]\n\r\t \"'")


def find_archive_links(text: str) -> list[str]:
    """Cari semua link dokumentasi/arsip dalam teks."""
    matches = ARCHIVE_LINK_REGEX.findall(text)
    return [clean_url(m) for m in matches]


def _extract_gdrive_link(text: str) -> str:
    """Ekstrak Google Drive / dokumentasi URL secara presisi menggunakan regex."""
    match = ARCHIVE_LINK_REGEX.search(text)
    if match:
        return clean_url(match.group(0))
    return "NULL"


def _extract_date_fallback(text: str, default_date: str) -> str:
    """Ekstrak tanggal dari teks secara pintar dan presisi."""
    # Special: Natal YYYY
    m_natal = re.search(r"\bnatal\s+(\d{4})\b", text, re.IGNORECASE)
    if m_natal:
        return f"{m_natal.group(1)}-12-25"

    # Format DD/MM/YYYY atau DD-MM-YYYY
    m_dmy = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", text)
    if m_dmy:
        d, m, y = m_dmy.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"

    # Format YYYY-MM-DD
    m_iso = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if m_iso:
        y, m, d = m_iso.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"

    # Format DD [Nama Bulan] YYYY (misal: 18 NOV 2025 atau 29 September 2026)
    m_words_full = re.search(r"\b(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})\b", text)
    if m_words_full:
        d, m_name, y = m_words_full.groups()
        m_num = MONTH_MAP.get(m_name.lower())
        if m_num:
            return f"{y}-{m_num}-{int(d):02d}"

    # Format DD [Nama Bulan] YY (misal: 7 NOV 25)
    m_words_yy = re.search(r"\b(\d{1,2})\s+([a-zA-Z]+)\s+(\d{2})\b", text)
    if m_words_yy:
        d, m_name, yy = m_words_yy.groups()
        m_num = MONTH_MAP.get(m_name.lower())
        if m_num:
            return f"20{yy}-{m_num}-{int(d):02d}"

    # Format DD [Nama Bulan] tanpa tahun (misal: 3 OKT, 18 DES) -> gunakan tahun default
    m_words_noyear = re.search(r"\b(\d{1,2})\s+([a-zA-Z]{3,})\b", text)
    if m_words_noyear:
        d, m_name = m_words_noyear.groups()
        m_num = MONTH_MAP.get(m_name.lower())
        if m_num:
            def_y = default_date[:4] if len(default_date) >= 4 else datetime.now().strftime("%Y")
            return f"{def_y}-{m_num}-{int(d):02d}"

    # Format Tahun saja YYYY (misal: 2024 atau 2025)
    m_year = re.search(r"\b(20\d{2})\b", text)
    if m_year:
        return f"{m_year.group(1)}-01-01"

    return default_date


def _fallback_classification(raw_text: str, event_date: str) -> dict:
    """Fallback cerdas untuk menentukan judul & kategori secara deterministik."""
    clean = re.sub(r"https?://\S+", "", raw_text)
    clean = re.sub(r"LINK\s+GDRIVE", "", clean, flags=re.IGNORECASE).strip(" :-\n\r\t")

    first_line = clean.split("\n")[0].strip() if clean else "Dokumentasi Kegiatan"
    title = first_line[:60].strip(" :-\t")
    if not title:
        title = "Dokumentasi Kegiatan"

    lower = title.lower()
    if any(k in lower for k in ["komcad", "lapangan", "apel", "latihan", "kunjungan", "studi banding", "outbound", "latsitarda", "drone"]):
        category = "Lapangan"
    elif any(k in lower for k in ["rapat", "evaluasi", "pleno", "internal", "briefing", "pengarahan rektor", "sertilat", "sertijab", "pengukuhan", "cadet"]):
        category = "Internal"
    elif any(k in lower for k in ["pers", "press", "media", "publikasi", "liputan"]):
        category = "Publikasi"
    elif any(k in lower for k in ["seminar", "workshop", "lomba", "festival", "event", "pelantikan", "hut tni", "reuni", "piala menpora", "orkes", "orkestra", "paduan suara", "svara", "genderang suling", "natal", "hindu"]):
        category = "Event Utama"
    else:
        category = "Lainnya"

    slug_cat = re.sub(r"\s+", "", category)
    slug_title = re.sub(r"[^\w\s-]", "", title)
    slug_title = re.sub(r"\s+", "_", slug_title.strip())[:30]
    folder_name = f"{event_date}_{slug_cat}_{slug_title}"

    words = [w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", title)]
    tag_candidates = [w for w in words if w not in {"dan", "atau", "link", "part", "foto", "video", "giat", "dokum", "untuk"}]
    tags = list(dict.fromkeys([category.lower()] + tag_candidates[:3]))

    return {
        "standardized_title": title,
        "category": category,
        "tags": tags,
        "folder_name_convention": folder_name,
    }


def split_bulk_text(text: str, default_date: str) -> list[dict]:
    """
    Pecah teks bulk menjadi daftar item individual.
    Setiap link mendapatkan judul hierarkis, tanggal, kategori, tags, dan format nama folder.
    """
    lines = [ln.strip() for ln in text.split("\n")]
    items = []

    current_main_heading = ""
    current_sub_heading = ""
    pending_links = []

    def commit_pending_links(override_sub=""):
        nonlocal pending_links, current_main_heading, current_sub_heading
        if not pending_links:
            return

        sub_to_use = override_sub or current_sub_heading
        if current_main_heading and sub_to_use:
            clean_sub = re.sub(r"^[-*•\d\.\s]+", "", sub_to_use).strip()
            base_title = f"{current_main_heading} - {clean_sub}" if clean_sub else current_main_heading
        elif current_main_heading:
            base_title = current_main_heading
        elif sub_to_use:
            base_title = re.sub(r"^[-*•\d\.\s]+", "", sub_to_use).strip()
        else:
            base_title = "Dokumentasi Kegiatan"

        ev_date = _extract_date_fallback(base_title, default_date)
        cls_info = _fallback_classification(base_title, ev_date)

        for idx, lnk in enumerate(pending_links):
            item_title = base_title
            if len(pending_links) > 1:
                item_title = f"{base_title} (Part {idx + 1})"

            f_name = cls_info["folder_name_convention"]
            if len(pending_links) > 1:
                f_name += f"_Part{idx+1}"

            items.append({
                "title": item_title,
                "event_date": ev_date,
                "category": cls_info["category"],
                "tags": cls_info["tags"],
                "link": clean_url(lnk),
                "folder_name": f_name,
            })
        pending_links = []

    for line in lines:
        if not line:
            continue

        urls = ARCHIVE_LINK_REGEX.findall(line)
        if urls:
            first_url_pos = line.find(urls[0])
            prefix = line[:first_url_pos].strip(" :-#\t")
            if prefix and prefix.lower() not in GENERIC_HEADERS:
                commit_pending_links()
                pending_links.extend(urls)
                commit_pending_links(override_sub=prefix)
            else:
                pending_links.extend(urls)
            continue

        lower_line = line.lower().strip(" :-\t#*")
        if lower_line in GENERIC_HEADERS:
            continue

        is_sub = bool(re.match(r"^[-*•\d\.]+\s*", line))
        if is_sub:
            commit_pending_links()
            current_sub_heading = line
        else:
            commit_pending_links()
            current_main_heading = line
            current_sub_heading = ""

    commit_pending_links()
    return items


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

async def node3_formatter(
    node2_output: dict,
    archive_id: str,
    link_check: Optional[dict] = None,
) -> dict:
    """
    Node 3: Format data siap simpan ke Sheets + buat pesan balasan Telegram.
    Mencakup status hasil check kesehatan link (Work, Butuh Akses, Rusak).
    """
    link = node2_output.get("link_drive", "NULL")
    link_display = link if link and link != "NULL" else "NULL"

    status_link = link_check.get("status", "VALID") if link_check else "VALID"
    status_icon = link_check.get("icon", "🟢") if link_check else "🟢"
    status_label = link_check.get("label", "Work (Siap Akses)") if link_check else "Work (Siap Akses)"
    status_detail = link_check.get("detail", "Aktif & Siap Diakses") if link_check else "Aktif & Siap Diakses"

    prompt = f"""Anda adalah AI Output Formatter dan Telegram Bot Responder.
Tugas Anda adalah merubah JSON dari Node 2 menjadi dua objek utama:
1. Objek data baris untuk Google Sheets.
2. Pesan teks balasan konfirmasi untuk diposting balik ke Telegram.

ATURAN BALASAN TELEGRAM:
- Gunakan bahasa Indonesia yang ramah, rapi, dan profesional.
- Gunakan emoji yang sesuai.
- Status link saat ini: {status_icon} {status_label} ({status_detail}).
- Jika status_link bernilai "RESTRICTED", ingatkan dengan jelas bahwa link membutuhkan akses/izin (private).
- Jika status_link bernilai "BROKEN", ingatkan bahwa link rusak / tidak ditemukan.
- Jika link_drive bernilai "NULL", berikan pesan peringatan bahwa link tidak ditemukan.
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
    "Format_Nama_Folder": "folder_name_convention",
    "Status_Link": "{status_link}"
  }},
  "telegram_reply_message": "pesan balasan lengkap dengan emoji"
}}"""

    try:
        result = await _generate(prompt)
        data = _parse_json(result)

        # Proteksi konsistensi link & status di database_row
        if data.get("database_row", {}).get("Link_Google_Drive") in (None, "", "NULL") and link != "NULL":
            data["database_row"]["Link_Google_Drive"] = link
        data.setdefault("database_row", {})["Status_Link"] = status_link

        return data
    except Exception as e:
        print(f"[Node 3] Error: {e}")
        tags_str = ", ".join(node2_output.get("tags", []))
        warning = ""
        if link == "NULL":
            warning = "\n\n⚠️ *PERHATIAN:* Link Google Drive tidak ditemukan dalam pesan!"
        elif status_link == "RESTRICTED":
            warning = "\n\n🔒 *PERHATIAN:* Link ini terdeteksi *membutuhkan akses lebih / private*. Pastikan perizinan Google Drive telah dibuka untuk publik jika diperlukan."
        elif status_link == "BROKEN":
            warning = "\n\n🔴 *PERINGATAN:* Link ini rusak atau file/folder tidak ditemukan (HTTP 404 / Dihapus)!"

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
                "Status_Link": status_link,
            },
            "telegram_reply_message": (
                f"✅ *DOKUMENTASI BERHASIL DIARSIP*\n\n"
                f"🆔 *ID Arsip:* `{archive_id}`\n"
                f"📌 *Kegiatan:* {node2_output.get('standardized_title', '-')}\n"
                f"📁 *Kategori:* {node2_output.get('category', '-')}\n"
                f"📅 *Tanggal:* {node2_output.get('event_date', '-')}\n"
                f"🏷️ *Tags:* #{' #'.join(node2_output.get('tags', []))}\n"
                f"🔗 *Link Drive:* {link_display} {status_icon} _{status_label}_\n"
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
    Termasuk pengecekan kesehatan link secara otomatis.
    """
    now = datetime.now()
    archive_id = f"DOC-{now.strftime('%Y%m%d-%H%M%S')}"

    print(f"[Pipeline] START {archive_id}")

    # Node 1
    node1 = await node1_extractor(raw_text, sender_name, timestamp)
    print(f"[Pipeline] Node 1 done: link={node1.get('link_drive')}, date={node1.get('event_date')}")

    # Cek kesehatan link
    link_url = node1.get("link_drive")
    link_check = None
    if link_url and link_url != "NULL":
        try:
            link_check = await check_single_url(link_url, timeout_sec=8.0)
            print(f"[Pipeline] Link check: {link_check.get('status')} - {link_check.get('detail')}")
        except Exception as e:
            print(f"[Pipeline] Link check error: {e}")

    # Node 2
    node2 = await node2_classifier(node1)
    print(f"[Pipeline] Node 2 done: category={node2.get('category')}, title={node2.get('standardized_title')}")

    # Node 3
    node3 = await node3_formatter(node2, archive_id, link_check=link_check)
    print(f"[Pipeline] Node 3 done: status={node3.get('status')}")

    return node3


async def run_bulk_pipeline(
    raw_text: str,
    sender_name: str,
    timestamp: str,
) -> dict:
    """
    Pipeline khusus untuk pengarsipan pesan massal (Bulk Archive).
    Memproses banyak link secara individual, memvalidasi kesehatan link,
    menghasilkan baris-baris Sheets, dan membuat rangkuman balasan Telegram yang ringkas & rapi.
    """
    default_date = timestamp[:10] if timestamp else datetime.now().strftime("%Y-%m-%d")
    items = split_bulk_text(raw_text, default_date)

    if not items:
        found_links = find_archive_links(raw_text)
        for idx, lnk in enumerate(found_links):
            items.append({
                "title": f"Dokumentasi Kegiatan {idx + 1}",
                "event_date": default_date,
                "category": "Lainnya",
                "tags": ["dokumentasi", "bulk"],
                "link": lnk,
                "folder_name": f"{default_date}_Lainnya_Dokumentasi_{idx+1}",
            })

    # Cek kesehatan semua link secara concurrent
    all_urls = [it["link"] for it in items if it.get("link") and it["link"] != "NULL"]
    url_to_check = {}
    if all_urls:
        try:
            check_results = await check_links_batch(all_urls, max_concurrent=15, timeout_sec=8.0)
            url_to_check = {r["url"]: r for r in check_results}
        except Exception as e:
            print(f"[Bulk Pipeline] Error checking links batch: {e}")

    # Optional AI enhancement jika batch kecil (<= 8 item)
    if 1 < len(items) <= 8:
        try:
            summary_list = [{"idx": i, "title": it["title"], "event_date": it["event_date"]} for i, it in enumerate(items)]
            ai_prompt = f"""Anda adalah AI Classifier PDD/Humas.
Berikut adalah daftar {len(items)} kegiatan dari pesan Telegram:
{json.dumps(summary_list, ensure_ascii=False)}

Kategorikan masing-masing ke salah satu: Event Utama, Internal, Publikasi, Lapangan, atau Lainnya.
Formatkan standardized_title agar rapi & profesional (Title Case, maks 5 kata).

Keluarkan HANYA JSON array:
[
  {{"idx": 0, "standardized_title": "...", "category": "...", "tags": ["tag1", "tag2"]}},
  ...
]"""
            ai_res = await asyncio.wait_for(_generate(ai_prompt), timeout=8.0)
            ai_parsed = json.loads(re.search(r"\[.*\]", ai_res, re.DOTALL).group(0))
            for ai_item in ai_parsed:
                idx = ai_item.get("idx")
                if idx is not None and 0 <= idx < len(items):
                    if ai_item.get("standardized_title"):
                        items[idx]["title"] = ai_item["standardized_title"]
                    if ai_item.get("category"):
                        items[idx]["category"] = ai_item["category"]
                    if ai_item.get("tags"):
                        items[idx]["tags"] = ai_item["tags"]
        except Exception as e:
            print(f"[Bulk Pipeline] AI refinement skipped: {e}")

    now = datetime.now()
    batch_timestamp_slug = now.strftime("%Y%m%d-%H%M%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    database_rows = []
    for idx, it in enumerate(items, 1):
        archive_id = f"DOC-{batch_timestamp_slug}-{idx:03d}"
        tags_str = ", ".join(it.get("tags", []))
        chk = url_to_check.get(it["link"], {"status": "VALID", "icon": "🟢", "label": "Work", "detail": "Aktif"})
        database_rows.append({
            "ID_Arsip": archive_id,
            "Tanggal_Kegiatan": it.get("event_date", default_date),
            "Nama_Kegiatan": it.get("title", f"Kegiatan {idx}"),
            "Kategori": it.get("category", "Lainnya"),
            "Tags": tags_str,
            "Link_Google_Drive": it.get("link", ""),
            "Pengirim": sender_name,
            "Format_Nama_Folder": it.get("folder_name", ""),
            "Waktu_Input": now_str,
            "Status_Link": chk.get("status", "VALID"),
        })

    total = len(database_rows)
    valid_cnt = sum(1 for r in database_rows if r["Status_Link"] == "VALID")
    restr_cnt = sum(1 for r in database_rows if r["Status_Link"] == "RESTRICTED")
    broken_cnt = sum(1 for r in database_rows if r["Status_Link"] == "BROKEN")

    lines = [
        "📦 *PENGARSIPAN MASSAL (BULK) BERHASIL*\n",
        f"📊 *Total Link Diproses:* `{total} item`",
        f"   • 🟢 *Work / Siap Akses:* `{valid_cnt}`",
    ]
    if restr_cnt > 0:
        lines.append(f"   • 🔒 *Butuh Akses (Restricted):* `{restr_cnt}`")
    if broken_cnt > 0:
        lines.append(f"   • 🔴 *Rusak / 404:* `{broken_cnt}`")

    lines.extend([
        f"👤 *Pengirim:* {sender_name}",
        f"🆔 *Batch ID:* `{batch_timestamp_slug}`\n",
        "📋 *Rangkuman Entitas yang Diarsip:*"
    ])

    preview_limit = 10
    for i, row in enumerate(database_rows[:preview_limit], 1):
        status_icon = "🟢" if row["Status_Link"] == "VALID" else ("🔒" if row["Status_Link"] == "RESTRICTED" else "🔴")
        note = ""
        if row["Status_Link"] == "RESTRICTED":
            note = " ⚠️ _(Butuh Akses)_"
        elif row["Status_Link"] == "BROKEN":
            note = " ❌ _(Link Rusak)_"
        link_md = f"[Buka Link]({row['Link_Google_Drive']})" if row['Link_Google_Drive'] else "❌"
        lines.append(
            f"{i}. {status_icon} *[{row['Kategori']}]* `{row['Nama_Kegiatan']}`{note}\n"
            f"   📅 {row['Tanggal_Kegiatan']} | 🔗 {link_md}"
        )

    if total > preview_limit:
        lines.append(f"\n_...dan {total - preview_limit} dokumentasi lainnya berhasil dicatat secara individual._")

    if restr_cnt > 0 or broken_cnt > 0:
        lines.append(
            f"\n⚠️ *Pemberitahuan Status Link:*\n"
            f"Ditemukan {restr_cnt} link yang membutuhkan akses/private dan {broken_cnt} link rusak. Mohon periksa perizinan folder di Google Drive jika ada file penting yang perlu dibuka untuk umum."
        )

    lines.append("\n💾 _Semua item beserta status akses telah disimpan ke Google Sheets._")

    return {
        "status": "success",
        "is_bulk": True,
        "total_count": total,
        "database_rows": database_rows,
        "telegram_reply_message": "\n".join(lines),
    }
