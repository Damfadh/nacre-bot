"""
Handler admin: tambah foto (GDrive link atau upload Telegram),
hapus foto, kelola user.

Alur tambah foto via ConversationHandler:
  1. /tambah
  2. Masukkan judul
  3. Masukkan kategori
  4. Masukkan deskripsi (opsional)
  5. Kirim link GDrive ATAU kirim foto langsung sebagai document
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from database import (
    add_photo,
    delete_photo,
    get_photo,
    set_user_role,
    ban_user,
    get_user,
    search_photos,
)
from utils import is_valid_gdrive_link, extract_file_id_from_link
from handlers.permissions import require_admin

# States untuk ConversationHandler
(
    STATE_JUDUL,
    STATE_KATEGORI,
    STATE_DESKRIPSI,
    STATE_SUMBER,
) = range(4)


# ─────────────────────────────────────────────
# TAMBAH FOTO
# ─────────────────────────────────────────────

@require_admin
async def cmd_tambah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mulai proses tambah foto."""
    context.user_data.clear()
    await update.message.reply_text(
        "➕ *Tambah Foto Baru*\n\n"
        "Langkah 1/4: Masukkan *judul* foto:\n"
        "(ketik /batal untuk membatalkan)",
        parse_mode="Markdown",
    )
    return STATE_JUDUL


async def tambah_judul(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima judul foto."""
    judul = update.message.text.strip()
    if not judul:
        await update.message.reply_text("❌ Judul tidak boleh kosong. Coba lagi:")
        return STATE_JUDUL

    context.user_data["judul"] = judul
    await update.message.reply_text(
        f"✅ Judul: *{judul}*\n\n"
        "Langkah 2/4: Masukkan *kategori* foto:\n"
        "Contoh: `landscape`, `portrait`, `produk`, `event`",
        parse_mode="Markdown",
    )
    return STATE_KATEGORI


async def tambah_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima kategori foto."""
    kategori = update.message.text.strip().lower()
    if not kategori:
        await update.message.reply_text("❌ Kategori tidak boleh kosong. Coba lagi:")
        return STATE_KATEGORI

    context.user_data["kategori"] = kategori
    await update.message.reply_text(
        f"✅ Kategori: *{kategori}*\n\n"
        "Langkah 3/4: Masukkan *deskripsi* foto (opsional):\n"
        "Kirim `-` untuk melewati",
        parse_mode="Markdown",
    )
    return STATE_DESKRIPSI


async def tambah_deskripsi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima deskripsi foto."""
    desc = update.message.text.strip()
    context.user_data["deskripsi"] = None if desc == "-" else desc

    await update.message.reply_text(
        "Langkah 4/4: Sekarang *kirim sumber foto*:\n\n"
        "📎 **Opsi A:** Kirim *link Google Drive* (pastikan file publik)\n"
        "📷 **Opsi B:** Kirim foto sebagai *File/Document* langsung di sini\n\n"
        "_Kirim /batal untuk membatalkan_",
        parse_mode="Markdown",
    )
    return STATE_SUMBER


async def tambah_sumber_gdrive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima link Google Drive."""
    link = update.message.text.strip()

    if not is_valid_gdrive_link(link):
        await update.message.reply_text(
            "❌ Link tidak valid. Pastikan link Google Drive yang benar.\n"
            "Contoh: `https://drive.google.com/file/d/FILE_ID/view`\n\n"
            "Coba lagi:",
            parse_mode="Markdown",
        )
        return STATE_SUMBER

    user = update.effective_user
    result = add_photo(
        title=context.user_data["judul"],
        gdrive_link=link,
        description=context.user_data.get("deskripsi"),
        category=context.user_data["kategori"],
        uploaded_by=user.id,
    )

    if result:
        await update.message.reply_text(
            f"✅ *Foto berhasil ditambahkan!*\n\n"
            f"🔖 ID: #{result['id']}\n"
            f"📌 Judul: {result['title']}\n"
            f"📂 Kategori: {result['category']}\n"
            f"🔗 Sumber: Google Drive",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("❌ Gagal menyimpan foto ke database.")

    context.user_data.clear()
    return ConversationHandler.END


async def tambah_sumber_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima foto yang dikirim sebagai Document."""
    doc = update.message.document
    if not doc or not doc.mime_type.startswith("image/"):
        await update.message.reply_text(
            "❌ Kirim file berupa gambar (JPG/PNG) sebagai Document.\n"
            "Atau kirim link Google Drive.\n\nCoba lagi:"
        )
        return STATE_SUMBER

    # Simpan dengan telegram_file_id
    user = update.effective_user
    telegram_file_id = doc.file_id

    result = add_photo(
        title=context.user_data["judul"],
        telegram_file_id=telegram_file_id,
        description=context.user_data.get("deskripsi"),
        category=context.user_data["kategori"],
        uploaded_by=user.id,
    )

    if result:
        await update.message.reply_text(
            f"✅ *Foto berhasil ditambahkan!*\n\n"
            f"🔖 ID: #{result['id']}\n"
            f"📌 Judul: {result['title']}\n"
            f"📂 Kategori: {result['category']}\n"
            f"💾 Sumber: Telegram Document",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("❌ Gagal menyimpan foto ke database.")

    context.user_data.clear()
    return ConversationHandler.END


async def tambah_batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Batalkan proses tambah foto."""
    context.user_data.clear()
    await update.message.reply_text("❌ Proses tambah foto dibatalkan.")
    return ConversationHandler.END


# ConversationHandler untuk /tambah
tambah_conversation = ConversationHandler(
    entry_points=[CommandHandler("tambah", cmd_tambah)],
    states={
        STATE_JUDUL: [MessageHandler(filters.TEXT & ~filters.COMMAND, tambah_judul)],
        STATE_KATEGORI: [MessageHandler(filters.TEXT & ~filters.COMMAND, tambah_kategori)],
        STATE_DESKRIPSI: [MessageHandler(filters.TEXT & ~filters.COMMAND, tambah_deskripsi)],
        STATE_SUMBER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, tambah_sumber_gdrive),
            MessageHandler(filters.Document.IMAGE, tambah_sumber_document),
        ],
    },
    fallbacks=[CommandHandler("batal", tambah_batal)],
    allow_reentry=True,
)


# ─────────────────────────────────────────────
# HAPUS FOTO
# ─────────────────────────────────────────────

@require_admin
async def cmd_hapus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /hapus [ID] — hapus foto dari database."""
    if not context.args:
        # Tampilkan daftar foto untuk dipilih
        photos = search_photos()
        if not photos:
            await update.message.reply_text("📭 Belum ada foto di database.")
            return

        keyboard = [
            [InlineKeyboardButton(
                f"🗑️ [{p['id']}] {p['title']}",
                callback_data=f"admin_hapus:{p['id']}"
            )]
            for p in photos[:20]
        ]
        await update.message.reply_text(
            "🗑️ *Pilih foto yang ingin dihapus:*\n"
            "_(atau ketik `/hapus [ID]`)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    try:
        photo_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID harus berupa angka. Contoh: `/hapus 5`", parse_mode="Markdown")
        return

    photo_data = get_photo(photo_id)
    if not photo_data:
        await update.message.reply_text(f"❌ Foto dengan ID #{photo_id} tidak ditemukan.")
        return

    success = delete_photo(photo_id)
    if success:
        await update.message.reply_text(
            f"✅ Foto *#{photo_id} - {photo_data['title']}* berhasil dihapus.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("❌ Gagal menghapus foto.")


# ─────────────────────────────────────────────
# KELOLA USER
# ─────────────────────────────────────────────

@require_admin
async def cmd_setadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /setadmin [user_id] — jadikan user sebagai admin."""
    if not context.args:
        await update.message.reply_text(
            "Penggunaan: `/setadmin [user_id]`\n"
            "Cara cari user_id: minta user kirim /start lalu cek log.",
            parse_mode="Markdown",
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID harus berupa angka.")
        return

    target = get_user(target_id)
    if not target:
        await update.message.reply_text(f"❌ User #{target_id} tidak ditemukan di database.")
        return

    set_user_role(target_id, "admin")
    await update.message.reply_text(
        f"✅ User *{target.get('full_name', target_id)}* (#{target_id}) sekarang menjadi Admin.",
        parse_mode="Markdown",
    )


@require_admin
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /ban [user_id]."""
    if not context.args:
        await update.message.reply_text("Penggunaan: `/ban [user_id]`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
        ban_user(target_id, True)
        await update.message.reply_text(f"🚫 User #{target_id} telah dibanned.")
    except ValueError:
        await update.message.reply_text("❌ ID harus berupa angka.")


@require_admin
async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /unban [user_id]."""
    if not context.args:
        await update.message.reply_text("Penggunaan: `/unban [user_id]`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
        ban_user(target_id, False)
        await update.message.reply_text(f"✅ User #{target_id} telah di-unban.")
    except ValueError:
        await update.message.reply_text("❌ ID harus berupa angka.")
