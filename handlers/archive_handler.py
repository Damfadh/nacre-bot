"""
Handler Telegram untuk sistem pengarsipan dokumentasi PDD/Humas.

Trigger:
- Pesan di grup/channel yang mengandung link Google Drive → auto arsip
- Command /arsip [teks] → arsipkan manual
- Command /cari_arsip [keyword] → cari arsip di Sheets
- Command /status_arsip → cek konfigurasi sistem
"""
import re
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from utils.pipeline import (
    run_pipeline,
    run_bulk_pipeline,
    find_archive_links,
    ARCHIVE_LINK_REGEX,
)
from utils.sheets import (
    append_archive_row,
    append_archive_rows,
    search_archives,
    is_sheets_configured,
)
from utils.link_checker import check_links_batch, check_single_url

# Regex untuk deteksi link Google Drive dan link dokumentasi lainnya
GDRIVE_PATTERN = ARCHIVE_LINK_REGEX


async def cmd_arsip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command /arsip [teks] — arsipkan dokumentasi secara manual.
    Bisa juga reply ke pesan yang mengandung link GDrive/dokumentasi.
    Mendukung single link maupun bulk links sekaligus.
    """
    user = update.effective_user
    message = update.message

    # Ambil teks: dari args, dari reply, atau dari teks pesan asli
    if context.args:
        raw_text = " ".join(context.args)
    elif message.reply_to_message and message.reply_to_message.text:
        raw_text = message.reply_to_message.text
    else:
        await message.reply_text(
            "📋 *Cara Penggunaan /arsip:*\n\n"
            "1. Ketik: `/arsip [keterangan acara] [link drive]`\n"
            "2. Atau: *Reply* ke pesan yang mengandung link dokumentasi, "
            "lalu ketik `/arsip`\n"
            "3. Mendukung pengarsipan banyak link sekaligus (Bulk Archive)!\n\n"
            "Contoh:\n"
            "`/arsip Foto Workshop AI Humas 25 Sep 2026 "
            "https://drive.google.com/drive/folders/xxx`",
            parse_mode="Markdown",
        )
        return

    sender_name = user.full_name or user.username or f"User {user.id}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    links = find_archive_links(raw_text)
    is_bulk = len(links) > 1

    if is_bulk:
        # ── Mode Pengarsipan Massal (Bulk) ──
        status_msg = await message.reply_text(
            f"⚙️ *Memproses arsip massal (bulk)...*\n\n"
            f"Terdeteksi: *{len(links)} link dokumentasi* ⏳\n"
            f"_Mengekstrak dan mengklasifikasikan setiap kegiatan..._",
            parse_mode="Markdown",
        )

        result = await run_bulk_pipeline(raw_text, sender_name, timestamp)

        await status_msg.edit_text(
            f"⚙️ *Memproses arsip massal (bulk)...*\n\n"
            f"Terdeteksi: *{len(links)} link* ✅\n"
            f"💾 *Menyimpan {len(result['database_rows'])} entitas ke Google Sheets...*",
            parse_mode="Markdown",
        )

        saved = False
        if is_sheets_configured():
            saved = await append_archive_rows(result["database_rows"])

        await status_msg.delete()

        reply_text = result.get("telegram_reply_message", "✅ Arsip massal berhasil diproses.")
        if not saved and is_sheets_configured():
            reply_text += "\n\n⚠️ _Gagal menyimpan ke Google Sheets. Cek konfigurasi._"
        elif not is_sheets_configured():
            reply_text += "\n\n⚠️ _Google Sheets belum dikonfigurasi. Data tidak tersimpan ke Sheets._"

        await _safe_reply(message, reply_text)
        return

    # ── Mode Pengarsipan Tunggal (Single) ──
    status_msg = await message.reply_text(
        "⚙️ *Memproses dokumentasi...*\n\n"
        "```\n"
        "Node 1: Mengekstrak data...    ⏳\n"
        "Node 2: Mengklasifikasi...     ⏳\n"
        "Node 3: Memformat output...    ⏳\n"
        "```",
        parse_mode="Markdown",
    )

    # Jalankan pipeline AI
    result = await run_pipeline(raw_text, sender_name, timestamp)

    # Update status Node 1 & 2 selesai
    await status_msg.edit_text(
        "⚙️ *Memproses dokumentasi...*\n\n"
        "```\n"
        "Node 1: Mengekstrak data...    ✅\n"
        "Node 2: Mengklasifikasi...     ✅\n"
        "Node 3: Memformat output...    ✅\n"
        "```\n\n"
        "💾 Menyimpan ke Google Sheets...",
        parse_mode="Markdown",
    )

    # Simpan ke Google Sheets (Action A)
    saved = False
    if is_sheets_configured():
        saved = await append_archive_row(result["database_row"])

    # Hapus status message
    await status_msg.delete()

    # Kirim balasan konfirmasi (Action B)
    reply_text = result.get("telegram_reply_message", "✅ Arsip berhasil diproses.")

    if not saved and is_sheets_configured():
        reply_text += "\n\n⚠️ _Gagal menyimpan ke Google Sheets. Cek konfigurasi._"
    elif not is_sheets_configured():
        reply_text += "\n\n⚠️ _Google Sheets belum dikonfigurasi. Data tidak tersimpan ke Sheets._"

    await _safe_reply(message, reply_text)


async def _safe_reply(message, text: str, **kwargs):
    """Kirim balasan dengan fallback tanpa markdown jika formatting error."""
    try:
        await message.reply_text(text, parse_mode="Markdown", **kwargs)
    except Exception:
        await message.reply_text(text, **kwargs)


async def handle_auto_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler otomatis: proses pesan grup/channel/private yang mengandung link dokumentasi.
    Mendukung single link maupun bulk links.
    """
    message = update.message or update.channel_post
    if not message or not message.text:
        return

    links = find_archive_links(message.text)
    if not links:
        return

    user = update.effective_user
    if user:
        sender_name = user.full_name or user.username or f"User {user.id}"
    elif update.effective_chat:
        sender_name = update.effective_chat.title or "Channel Post"
    else:
        sender_name = "Anonymous"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if len(links) > 1:
        # Proses pipeline bulk
        result = await run_bulk_pipeline(message.text, sender_name, timestamp)
        if is_sheets_configured():
            await append_archive_rows(result["database_rows"])
        reply_text = result.get("telegram_reply_message", f"✅ {len(links)} dokumentasi berhasil diarsip.")
        await _safe_reply(message, reply_text)
    else:
        # Proses pipeline single
        result = await run_pipeline(message.text, sender_name, timestamp)
        if is_sheets_configured():
            await append_archive_row(result["database_row"])
        reply_text = result.get("telegram_reply_message", "✅ Dokumentasi diarsip.")
        await _safe_reply(message, reply_text)


async def cmd_cari_arsip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command /cari_arsip [keyword] — cari dokumentasi di Google Sheets.
    """
    if not context.args:
        await update.message.reply_text(
            "🔍 *Pencarian Arsip Dokumentasi*\n\n"
            "Cara pakai: `/cari_arsip [kata kunci]`\n\n"
            "Contoh:\n"
            "• `/cari_arsip workshop`\n"
            "• `/cari_arsip rapat september`\n"
            "• `/cari_arsip Event Utama`",
            parse_mode="Markdown",
        )
        return

    if not is_sheets_configured():
        await update.message.reply_text(
            "⚠️ Google Sheets belum dikonfigurasi.\n"
            "Hubungi admin untuk setup.",
        )
        return

    keyword = " ".join(context.args)
    await update.message.reply_text(f"🔍 Mencari: *{keyword}*...", parse_mode="Markdown")

    results = await search_archives(keyword)

    if not results:
        await update.message.reply_text(
            f"❌ Tidak ditemukan arsip dengan kata kunci: *{keyword}*",
            parse_mode="Markdown",
        )
        return

    # Format hasil pencarian
    lines = [f"📂 *Ditemukan {len(results)} Arsip untuk '{keyword}':*\n"]
    for r in results[:10]:  # maks 10 hasil
        link = r.get("Link_Google_Drive", "-")
        link_text = f"[Buka Drive]({link})" if link and link != "NULL" else "❌ Tidak ada link"
        lines.append(
            f"🔖 `{r.get('ID_Arsip', '-')}` | *{r.get('Nama_Kegiatan', '-')}*\n"
            f"   📁 {r.get('Kategori', '-')} | 📅 {r.get('Tanggal_Kegiatan', '-')}\n"
            f"   🏷️ _{r.get('Tags', '-')}_\n"
            f"   🔗 {link_text}\n"
        )

    if len(results) > 10:
        lines.append(f"\n_...dan {len(results) - 10} hasil lainnya. Perluas kata kunci untuk hasil lebih spesifik._")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def cmd_status_arsip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /status_arsip — cek konfigurasi sistem arsip."""
    import os
    sheets_ok = is_sheets_configured()
    from config import GEMINI_API_KEY, SHEETS_ID

    gemini_key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    sheets_id = os.getenv("SHEETS_ID") or SHEETS_ID

    gemini_ok = bool(gemini_key)
    sheets_id_ok = bool(sheets_id)

    status = (
        "📊 *Status Sistem Arsip Dokumentasi*\n"
        "⚡ Model AI: `gemini-3.8-flash`\n\n"
        f"{'✅' if gemini_ok else '❌'} Gemini AI API Key\n"
        f"{'✅' if sheets_id_ok else '❌'} Google Sheets ID\n"
        f"{'✅' if sheets_ok else '❌'} Service Account Credentials\n\n"
    )

    if sheets_ok and gemini_ok:
        status += "🟢 *Sistem siap!* Semua komponen aktif."
    else:
        status += "🔴 *Sistem belum siap.* Beberapa konfigurasi kurang."
        if not gemini_ok:
            status += "\n• Set `GEMINI_API_KEY` di Railway Variables"
        if not sheets_id_ok:
            status += "\n• Set `SHEETS_ID` di Railway Variables"
        if not sheets_ok:
            status += "\n• Upload file `credentials.json` Service Account"

    await update.message.reply_text(status, parse_mode="Markdown")


async def cmd_cek_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command /cek_link [url / teks] — Cek status kesehatan link apakah Work, Butuh Akses, atau Rusak.
    Bisa juga me-reply pesan apa saja yang mengandung link.
    """
    message = update.message
    if not message:
        return

    # Ambil teks dari args atau reply
    if context.args:
        raw_text = " ".join(context.args)
    elif message.reply_to_message and message.reply_to_message.text:
        raw_text = message.reply_to_message.text
    else:
        await message.reply_text(
            "🔍 *Cara Pakai /cek_link:*\n\n"
            "1. Ketik: `/cek_link [url]`\n"
            "2. Atau: *Reply* ke pesan yang mengandung satu atau banyak link, lalu ketik `/cek_link`\n\n"
            "Bot akan memeriksa apakah link tersebut:\n"
            "• 🟢 *Work* (Bisa diakses langsung)\n"
            "• 🔒 *Butuh Akses* (Private / Perlu Request Access)\n"
            "• 🔴 *Rusak* (404 / File Tidak Ditemukan)",
            parse_mode="Markdown",
        )
        return

    links = find_archive_links(raw_text)
    if not links:
        # Coba cari link generik jika bukan link drive/shortlink
        links = [m.rstrip(".,;)>]\n\r\t \"'") for m in re.findall(r"https?://\S+", raw_text)]

    if not links:
        await message.reply_text("❌ Tidak ditemukan link yang valid dalam pesan tersebut.")
        return

    status_msg = await message.reply_text(
        f"🔍 *Mengecek status {len(links)} link...* ⏳\n_Memverifikasi keterbukaan akses dan respons server..._",
        parse_mode="Markdown",
    )

    results = await check_links_batch(links, max_concurrent=15, timeout_sec=8.0)

    try:
        await status_msg.delete()
    except Exception:
        pass

    if len(results) == 1:
        res = results[0]
        reply = (
            f"🔍 *HASIL PENGECEKAN LINK*\n\n"
            f"🔗 *URL:* {res['url']}\n"
            f"📊 *Status:* {res['icon']} *{res['label']}*\n"
            f"📝 *Keterangan:* {res['detail']}\n"
        )
        if res.get("final_url") and res["final_url"] != res["url"]:
            reply += f"🎯 *Target Asli:* `{res['final_url'][:60]}...`\n"

        if res["status"] == "RESTRICTED":
            reply += "\n⚠️ *Catatan:* Link ini memerlukan izin akses. Buka Google Drive > Bagikan > Ubah menjadi *'Siapa saja yang memiliki link'* jika ingin dapat diakses publik."
        elif res["status"] == "BROKEN":
            reply += "\n🔴 *Peringatan:* Link tidak dapat diakses atau file telah dihapus."
        else:
            reply += "\n✅ *Link normal dan siap diakses siapa saja.*"

        await _safe_reply(message, reply)
        return

    # Multiple links
    valid_cnt = sum(1 for r in results if r["status"] == "VALID")
    restr_cnt = sum(1 for r in results if r["status"] == "RESTRICTED")
    broken_cnt = sum(1 for r in results if r["status"] == "BROKEN")

    lines = [
        f"🔍 *HASIL PENGECEKAN {len(results)} LINK*\n",
        f"📊 *Ringkasan Status:*",
        f"• 🟢 *Work / Siap Akses:* `{valid_cnt}`",
    ]
    if restr_cnt > 0:
        lines.append(f"• 🔒 *Butuh Akses (Restricted):* `{restr_cnt}`")
    if broken_cnt > 0:
        lines.append(f"• 🔴 *Rusak / 404:* `{broken_cnt}`")

    lines.append("\n📋 *Detail Status Setiap Link:*")
    for i, res in enumerate(results[:15], 1):
        lines.append(f"{i}. {res['icon']} [Buka Link]({res['url']}) — *{res['label']}*")

    if len(results) > 15:
        lines.append(f"\n_...dan {len(results) - 15} link lainnya._")

    if restr_cnt > 0:
        lines.append(f"\n⚠️ Ditemukan *{restr_cnt} link* yang membutuhkan izin akses (restricted). Pastikan setting Google Drive sudah diatur agar orang lain bisa melihat.")

    await _safe_reply(message, "\n".join(lines))
