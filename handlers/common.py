"""
Handler untuk command umum: /start, /help, /cari, /myid
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /myid — tampilkan Telegram user ID."""
    user = update.effective_user
    await update.message.reply_text(
        f"🪪 *Info Akun Telegram Kamu:*\n\n"
        f"• ID: `{user.id}`\n"
        f"• Nama: {user.full_name}\n"
        f"• Username: @{user.username or '-'}\n\n"
        f"_Salin angka ID di atas untuk dikirim ke admin._",
        parse_mode="Markdown",
    )
from database import upsert_user, search_photos, list_categories
from handlers.permissions import require_not_banned, is_admin


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /start - daftarkan user & tampilkan menu."""
    user = update.effective_user

    # Simpan user ke database (tidak crash jika Supabase error)
    try:
        upsert_user(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name or user.first_name or "Unknown",
        )
    except Exception as e:
        print(f"[DB] Error upsert_user: {e}")

    try:
        admin = is_admin(user.id)
    except Exception:
        admin = False
    role_text = "👑 Admin" if admin else "👤 User"

    welcome_text = (
        f"👋 Halo, *{user.first_name}*!\n\n"
        f"Selamat datang di *Nacre Bot* 🤖\n"
        f"Role Anda: {role_text}\n\n"
        "📋 *Menu Utama:*\n"
        "🔍 /cari — Cari foto\n"
        "📂 /kategori — Lihat semua kategori\n"
        "ℹ️ /help — Bantuan\n"
    )

    if admin:
        welcome_text += (
            "\n*🔧 Menu Admin:*\n"
            "➕ /tambah — Tambah foto baru\n"
            "🗑️ /hapus — Hapus foto\n"
            "👥 /users — Kelola user\n"
        )

    keyboard = [
        [
            InlineKeyboardButton("🔍 Cari Foto", switch_inline_query_current_chat=""),
            InlineKeyboardButton("📂 Kategori", callback_data="show_categories"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


@require_not_banned
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /help."""
    help_text = (
        "📖 *Panduan Penggunaan Bot*\n\n"
        "*Perintah Umum:*\n"
        "• /start — Menu utama\n"
        "• /cari [kata kunci] — Cari foto berdasarkan nama\n"
        "• /kategori — Lihat semua kategori foto\n\n"
        "*Cara Cari Foto:*\n"
        "Ketik `/cari nama_foto` atau ketuk tombol di menu utama\n\n"
        "*Cara Terima Foto:*\n"
        "Setelah cari, ketuk judul foto → bot akan mengirimkan fotonya\n"
    )

    if is_admin(update.effective_user.id):
        help_text += (
            "\n*Perintah Admin:*\n"
            "• /tambah — Mulai proses tambah foto\n"
            "• /hapus [ID] — Hapus foto berdasarkan ID\n"
            "• /setadmin [ID] — Jadikan user sebagai admin\n"
            "• /ban [ID] — Ban user\n"
            "• /unban [ID] — Unban user\n"
        )

    await update.message.reply_text(help_text, parse_mode="Markdown")


@require_not_banned
async def cmd_cari(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /cari [keyword] — mencari foto di database."""
    keyword = " ".join(context.args) if context.args else ""

    if not keyword:
        await update.message.reply_text(
            "🔍 Masukkan kata kunci setelah /cari\n"
            "Contoh: `/cari sunset`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(f"🔍 Mencari: *{keyword}*...", parse_mode="Markdown")
    photos = search_photos(keyword=keyword)

    if not photos:
        await update.message.reply_text(
            f"❌ Tidak ada foto ditemukan untuk: *{keyword}*\n"
            "Coba kata kunci lain atau ketuk /kategori",
            parse_mode="Markdown",
        )
        return

    # Tampilkan hasil sebagai inline keyboard
    keyboard = []
    for photo in photos[:10]:  # max 10 hasil
        label = f"[{photo['id']}] {photo['title']} ({photo['category']})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"get_photo:{photo['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"✅ Ditemukan *{len(photos)}* foto:\nKetuk untuk mengambil foto 👇",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )


@require_not_banned
async def cmd_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /kategori — tampilkan semua kategori."""
    categories = list_categories()

    if not categories:
        await update.message.reply_text("📂 Belum ada kategori tersedia.")
        return

    keyboard = [
        [InlineKeyboardButton(f"📁 {cat}", callback_data=f"browse_category:{cat}")]
        for cat in categories
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📂 *Pilih Kategori:*",
        parse_mode="Markdown",
        reply_markup=reply_markup,
    )
