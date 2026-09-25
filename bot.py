"""
Entry point utama bot Nacre
"""
import logging
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from config import BOT_TOKEN, validate_config
from handlers import (
    cmd_start,
    cmd_help,
    cmd_cari,
    cmd_kategori,
    cmd_myid,
    cmd_hapus,
    cmd_setadmin,
    cmd_ban,
    cmd_unban,
    tambah_conversation,
    handle_callback,
    handle_admin_callback,
)
from handlers.ai_handler import cmd_ai, cmd_cari_ai, cmd_reset_ai, handle_ai_message
from handlers.archive_handler import (
    cmd_arsip,
    cmd_cari_arsip,
    cmd_status_arsip,
    handle_auto_archive,
)
from handlers.audit_handler import cmd_audit_channel, scheduled_audit

# Setup logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Set daftar command di Telegram setelah bot start."""
    await application.bot.set_my_commands([
        BotCommand("start", "Menu utama"),
        BotCommand("cari", "Cari foto berdasarkan kata kunci"),
        BotCommand("cari_ai", "Smart search foto dengan AI"),
        BotCommand("ai", "Chat dengan Nacre AI"),
        BotCommand("reset_ai", "Reset riwayat chat AI"),
        BotCommand("kategori", "Lihat semua kategori foto"),
        BotCommand("help", "Bantuan penggunaan bot"),
        BotCommand("arsip", "Arsipkan dokumentasi (kirim link GDrive)"),
        BotCommand("cari_arsip", "Cari arsip dokumentasi"),
        BotCommand("status_arsip", "Cek status sistem arsip"),
        BotCommand("audit_channel", "Admin: Audit & sortir semua link channel"),
        BotCommand("myid", "Lihat Telegram ID kamu"),
        BotCommand("tambah", "Admin: Tambah foto baru"),
        BotCommand("hapus", "Admin: Hapus foto"),
        BotCommand("setadmin", "Admin: Jadikan user sebagai admin"),
        BotCommand("ban", "Admin: Ban user"),
        BotCommand("unban", "Admin: Unban user"),
        BotCommand("batal", "Batalkan proses yang sedang berjalan"),
    ])
    logger.info("✅ Bot commands telah diset")


def main() -> None:
    """Titik masuk utama bot."""
    # Validasi konfigurasi sebelum start
    validate_config()

    logger.info("🚀 Nacre Bot mulai...")

    # Buat aplikasi bot dengan timeout lebih besar
    request = HTTPXRequest(
        read_timeout=30,
        write_timeout=30,
        connect_timeout=30,
        pool_timeout=30,
    )
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(post_init)
        .build()
    )

    # ─── Conversation Handler (harus didaftarkan pertama) ───
    app.add_handler(tambah_conversation)

    # ─── Command Handlers ───
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cari", cmd_cari))
    app.add_handler(CommandHandler("kategori", cmd_kategori))
    app.add_handler(CommandHandler("myid", cmd_myid))

    # Admin commands
    app.add_handler(CommandHandler("hapus", cmd_hapus))
    app.add_handler(CommandHandler("setadmin", cmd_setadmin))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))

    # ─── AI Handlers ───
    app.add_handler(CommandHandler("ai", cmd_ai))
    app.add_handler(CommandHandler("cari_ai", cmd_cari_ai))
    app.add_handler(CommandHandler("reset_ai", cmd_reset_ai))

    # ─── Archive / Dokumentasi Handlers ───
    app.add_handler(CommandHandler("arsip", cmd_arsip))
    app.add_handler(CommandHandler("cari_arsip", cmd_cari_arsip))
    app.add_handler(CommandHandler("status_arsip", cmd_status_arsip))
    app.add_handler(CommandHandler("audit_channel", cmd_audit_channel))

    # Auto-archive: deteksi GDrive link di grup (prioritas tinggi, sebelum AI handler)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
            handle_auto_archive,
        ),
        group=1,
    )

    # Auto-reply AI untuk private chat
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message),
        group=2,
    )

    # ─── Callback Handlers ───
    # Admin callbacks (prioritas lebih tinggi)
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern=r"^admin_"))
    # User callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # ─── Scheduled Jobs ───
    # Audit otomatis setiap Minggu pukul 20:00
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(
            scheduled_audit,
            time=__import__("datetime").time(hour=20, minute=0),
            days=(6,),  # 6 = Minggu
            name="weekly_audit",
        )
        logger.info("✅ Scheduled audit mingguan (Minggu 20:00) telah diset")

    logger.info("✅ Semua handler terdaftar. Bot siap menerima pesan!")

    # Jalankan bot (polling)
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
