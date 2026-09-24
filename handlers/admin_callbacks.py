"""
Callback handler untuk aksi admin via tombol inline
"""
from telegram import Update
from telegram.ext import ContextTypes
from database import delete_photo, get_photo
from handlers.permissions import is_admin


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler callback khusus admin (hapus foto via tombol)."""
    query = update.callback_query
    user = update.effective_user

    if not is_admin(user.id):
        await query.answer("⛔ Bukan admin!", show_alert=True)
        return

    await query.answer()
    data: str = query.data

    if data.startswith("admin_hapus:"):
        photo_id = int(data.split(":")[1])
        photo_data = get_photo(photo_id)
        if not photo_data:
            await query.edit_message_text("❌ Foto tidak ditemukan.")
            return

        success = delete_photo(photo_id)
        if success:
            await query.edit_message_text(
                f"✅ Foto *#{photo_id} - {photo_data['title']}* berhasil dihapus.",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("❌ Gagal menghapus foto.")
