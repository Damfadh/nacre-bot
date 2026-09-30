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
