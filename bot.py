"""
Entry point utama bot Nacre
"""
import logging
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
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
        BotCommand("kategori", "Lihat semua kategori foto"),
        BotCommand("help", "Bantuan penggunaan bot"),
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

    # ─── Callback Handlers ───
    # Admin callbacks (prioritas lebih tinggi)
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern=r"^admin_"))
    # User callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("✅ Semua handler terdaftar. Bot siap menerima pesan!")

    # Jalankan bot (polling)
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
