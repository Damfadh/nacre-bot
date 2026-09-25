"""
Handler Telegram untuk sistem Channel Audit & Sorting.

Commands:
- /audit_channel — Jalankan audit lengkap (hanya admin)
- Scheduled trigger didukung via job queue
"""
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from handlers.permissions import require_not_banned
from utils.audit import run_audit_pipeline
from utils.sheets import (
    get_all_archive_records,
    write_audit_results,
    is_sheets_configured,
)
from config import ADMIN_IDS


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def cmd_audit_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command /audit_channel — Jalankan audit massal channel.
    Hanya bisa dijalankan oleh admin.
    """
    user = update.effective_user

    # Hanya admin
    if not _is_admin(user.id):
        await update.message.reply_text("❌ Perintah ini hanya untuk admin.")
        return

    if not is_sheets_configured():
        await update.message.reply_text(
            "⚠️ *Google Sheets belum dikonfigurasi!*\n\n"
            "Pastikan:\n"
            "• File `credentials.json` ada di folder bot\n"
            "• `SHEETS_ID` sudah diset di Railway Variables\n\n"
            "Gunakan /status\\_arsip untuk cek konfigurasi.",
            parse_mode="Markdown",
        )
        return

    # Mulai audit
    start_time = datetime.now()
    status_msg = await update.message.reply_text(
        "🔍 *AUDIT CHANNEL DIMULAI*\n\n"
        "```\n"
        "Node 0: Mengambil data dari Sheets... ⏳\n"
        "Node 1: Deduplication...              ⏳\n"
        "Node 2: HTTP Link Validator...        ⏳\n"
        "Node 3: AI Categorizer...             ⏳\n"
        "Output: Write to Sheets...            ⏳\n"
        "```",
        parse_mode="Markdown",
    )

    # Node 0: Ambil records dari Google Sheets
    await status_msg.edit_text(
        "🔍 *AUDIT CHANNEL DIMULAI*\n\n"
        "```\n"
        "Node 0: Mengambil data dari Sheets... ✅\n"
        "Node 1: Deduplication...              ⏳\n"
        "Node 2: HTTP Link Validator...        ⏳\n"
        "Node 3: AI Categorizer...             ⏳\n"
        "Output: Write to Sheets...            ⏳\n"
        "```",
        parse_mode="Markdown",
    )
    records = await get_all_archive_records()

    if not records:
        await status_msg.edit_text(
            "⚠️ *Tidak ada data untuk diaudit.*\n\n"
            "Tab 'Arsip Dokumentasi' di Google Sheets masih kosong.\n"
            "Arsipkan beberapa dokumentasi dulu dengan command /arsip.",
            parse_mode="Markdown",
        )
        return

    await status_msg.edit_text(
        f"🔍 *AUDIT CHANNEL DIMULAI*\n\n"
        f"```\n"
        f"Node 0: {len(records)} records diambil.    ✅\n"
        f"Node 1: Deduplication...              ⏳\n"
        f"Node 2: HTTP Link Validator...        ⏳\n"
        f"Node 3: AI Categorizer...             ⏳\n"
        f"Output: Write to Sheets...            ⏳\n"
        f"```",
        parse_mode="Markdown",
    )

    # Jalankan pipeline (Node 1, 2, 3)
    audit_result = await run_audit_pipeline(records)
    summary = audit_result.get("audit_summary", {})

    # Update progress
    await status_msg.edit_text(
        f"🔍 *AUDIT CHANNEL DIMULAI*\n\n"
        f"```\n"
        f"Node 0: {len(records)} records diambil.    ✅\n"
        f"Node 1: Deduplication...              ✅\n"
        f"Node 2: HTTP Link Validator...        ✅\n"
        f"Node 3: AI Categorizer...             ✅\n"
        f"Output: Write to Sheets...            ⏳\n"
        f"```",
        parse_mode="Markdown",
    )

    # Tulis hasil ke Google Sheets (3 tab)
    saved = await write_audit_results(audit_result)

    # Hapus status message
    await status_msg.delete()

    # Durasi proses
    duration = (datetime.now() - start_time).seconds

    # Kirim laporan ke admin
    report = audit_result.get("telegram_report_message", "Audit selesai.")

    # Tambah info sheets
    sheets_status = "✅ Tersimpan ke Google Sheets (3 tab)" if saved else "⚠️ Gagal menyimpan ke Sheets"
    report += f"\n\n⏱️ _Selesai dalam {duration} detik._\n{sheets_status}"

    # Telegram ada limit 4096 char per pesan
    if len(report) > 4000:
        report = report[:4000] + "\n\n_...laporan terpotong. Cek Google Sheets untuk detail lengkap._"

    await update.message.reply_text(report, parse_mode="Markdown", disable_web_page_preview=True)


async def scheduled_audit(context):
    """
    Fungsi untuk audit terjadwal (dipanggil oleh job queue).
    Kirim laporan ke semua admin.
    """
    if not is_sheets_configured():
        return

    records = await get_all_archive_records()
    if not records:
        return

    audit_result = await run_audit_pipeline(records)
    await write_audit_results(audit_result)

    report = audit_result.get("telegram_report_message", "Audit mingguan selesai.")
    report = f"🔄 *AUDIT TERJADWAL*\n\n{report}"

    if len(report) > 4000:
        report = report[:4000] + "\n\n_...cek Google Sheets untuk detail._"

    # Kirim ke semua admin
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=report,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception as e:
            print(f"[Audit Scheduled] Gagal kirim ke admin {admin_id}: {e}")
