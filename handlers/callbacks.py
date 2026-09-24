"""
Handler untuk callback query (tombol inline keyboard)
"""
import os
from telegram import Update
from telegram.ext import ContextTypes
from database import get_photo, search_photos, log_request
from utils import download_gdrive_photo, cleanup_file
from handlers.permissions import require_not_banned


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router utama untuk semua callback query."""
    query = update.callback_query
    await query.answer()

    data: str = query.data

    if data.startswith("get_photo:"):
        photo_id = int(data.split(":")[1])
        await send_photo_to_user(update, context, photo_id)

    elif data.startswith("browse_category:"):
        category = data.split(":", 1)[1]
        await browse_category(update, context, category)

    elif data == "show_categories":
        from database import list_categories
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        categories = list_categories()
        if not categories:
            await query.edit_message_text("📂 Belum ada kategori tersedia.")
            return
        keyboard = [
            [InlineKeyboardButton(f"📁 {cat}", callback_data=f"browse_category:{cat}")]
            for cat in categories
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📂 *Pilih Kategori:*",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )


async def send_photo_to_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    photo_id: int,
):
    """Download & kirim foto ke user."""
    query = update.callback_query
    user = update.effective_user

    photo_data = get_photo(photo_id)
    if not photo_data or not photo_data.get("is_active"):
        await query.edit_message_text("❌ Foto tidak ditemukan atau sudah dihapus.")
        return

    await query.edit_message_text(
        f"⏳ Mengambil foto: *{photo_data['title']}*...",
        parse_mode="Markdown",
    )

    # Catat log request
    log_request(user_id=user.id, photo_id=photo_id)

    caption = f"📸 *{photo_data['title']}*"
    if photo_data.get("description"):
        caption += f"\n\n{photo_data['description']}"
    caption += f"\n\n🏷️ Kategori: {photo_data.get('category', '-')}"
    caption += f"\n🔖 ID: #{photo_data['id']}"

    # Kasus 1: foto disimpan sebagai Telegram file_id
    if photo_data.get("source_type") == "telegram" and photo_data.get("telegram_file_id"):
        await context.bot.send_photo(
            chat_id=user.id,
            photo=photo_data["telegram_file_id"],
            caption=caption,
            parse_mode="Markdown",
        )
        await query.edit_message_text("✅ Foto sudah dikirim ke chat kamu!")
        return

    # Kasus 2: foto dari Google Drive
    file_id = photo_data.get("gdrive_file_id")
    if not file_id:
        await query.edit_message_text(
            "❌ Tidak ada sumber foto yang tersedia. Hubungi admin."
        )
        return

    local_path = await download_gdrive_photo(file_id)
    if not local_path:
        await query.edit_message_text(
            "❌ Gagal mendownload foto dari Google Drive.\n"
            "Pastikan link masih aktif & file bersifat publik."
        )
        return

    try:
        with open(local_path, "rb") as f:
            await context.bot.send_photo(
                chat_id=user.id,
                photo=f,
                caption=caption,
                parse_mode="Markdown",
            )
        await query.edit_message_text("✅ Foto sudah dikirim ke chat kamu!")
    except Exception as e:
        await query.edit_message_text(f"❌ Gagal mengirim foto: {e}")
    finally:
        cleanup_file(local_path)


async def browse_category(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    category: str,
):
    """Tampilkan daftar foto berdasarkan kategori."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    query = update.callback_query
    photos = search_photos(category=category)

    if not photos:
        await query.edit_message_text(f"📂 Belum ada foto di kategori *{category}*.", parse_mode="Markdown")
        return

    keyboard = [
        [InlineKeyboardButton(
            f"[{p['id']}] {p['title']}",
            callback_data=f"get_photo:{p['id']}"
        )]
        for p in photos[:15]
    ]
    keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="show_categories")])

    await query.edit_message_text(
        f"📂 *Kategori: {category}*\n"
        f"Total: {len(photos)} foto — Ketuk untuk mengambil 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
