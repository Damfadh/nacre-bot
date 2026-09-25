"""
Handler untuk fitur AI: /ai (chat), /cari_ai (smart search), /reset_ai
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import search_photos
from utils.ai import chat_with_ai, ai_smart_search, clear_chat_session
from handlers.permissions import require_not_banned


@require_not_banned
async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /ai [pesan] — chat dengan Gemini AI."""
    user = update.effective_user

    # Ambil pesan dari argument atau teks setelah /ai
    message = " ".join(context.args) if context.args else ""

    if not message:
        await update.message.reply_text(
            "🤖 *Chat dengan AI*\n\n"
            "Cara pakai: `/ai [pertanyaan kamu]`\n\n"
            "Contoh:\n"
            "• `/ai foto landscape apa yang tersedia?`\n"
            "• `/ai rekomendasikan foto untuk profile picture`\n"
            "• `/ai apa itu kategori portrait?`\n\n"
            "_Ketik /reset\\_ai untuk reset riwayat chat_",
            parse_mode="Markdown",
        )
        return

    # Tampilkan indikator mengetik
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    # Kirim ke Gemini
    response = await chat_with_ai(user_id=user.id, message=message)

    await update.message.reply_text(
        f"🤖 *Nacre AI:*\n\n{response}",
        parse_mode="Markdown",
    )


@require_not_banned
async def cmd_reset_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /reset_ai — reset riwayat chat AI."""
    user = update.effective_user
    clear_chat_session(user.id)
    await update.message.reply_text(
        "🔄 Riwayat chat AI telah direset. Mulai percakapan baru dengan /ai"
    )


@require_not_banned
async def cmd_cari_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /cari_ai [deskripsi] — smart search menggunakan AI."""
    keyword = " ".join(context.args) if context.args else ""

    if not keyword:
        await update.message.reply_text(
            "🔍 *Smart Search AI*\n\n"
            "Cari foto dengan deskripsi natural!\n\n"
            "Cara pakai: `/cari_ai [deskripsi]`\n\n"
            "Contoh:\n"
            "• `/cari_ai foto pemandangan pantai saat sunset`\n"
            "• `/cari_ai gambar makanan tradisional`\n"
            "• `/cari_ai potret wajah close up`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"🔍 AI sedang mencari foto untuk: *{keyword}*...",
        parse_mode="Markdown",
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    # Ambil semua foto dari DB
    all_photos = search_photos()
    if not all_photos:
        await update.message.reply_text("📭 Belum ada foto di database.")
        return

    # Smart search dengan AI
    results = await ai_smart_search(query=keyword, all_photos=all_photos)

    if not results:
        await update.message.reply_text(
            f"❌ AI tidak menemukan foto yang cocok untuk: *{keyword}*\n\n"
            "Coba deskripsi yang berbeda atau gunakan /cari untuk pencarian biasa.",
            parse_mode="Markdown",
        )
        return

    # Tampilkan hasil
    keyboard = [
        [InlineKeyboardButton(
            f"[{p['id']}] {p['title']} ({p['category']})",
            callback_data=f"get_photo:{p['id']}"
        )]
        for p in results
    ]
    await update.message.reply_text(
        f"✨ AI menemukan *{len(results)}* foto yang relevan:\n"
        f"Ketuk untuk mengambil foto 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler untuk pesan teks biasa (non-command).
    Jika user sedang dalam mode AI chat, teruskan ke Gemini.
    """
    # Cek apakah pesan dimulai dengan mention bot atau kata kunci AI
    text = update.message.text or ""
    bot_username = context.bot.username

    # Balas jika di-mention atau di private chat
    is_private = update.effective_chat.type == "private"
    is_mentioned = f"@{bot_username}" in text

    if not is_private and not is_mentioned:
        return

    # Bersihkan mention dari teks
    clean_text = text.replace(f"@{bot_username}", "").strip()
    if not clean_text:
        return

    user = update.effective_user
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    response = await chat_with_ai(user_id=user.id, message=clean_text)
    await update.message.reply_text(
        f"🤖 {response}",
        parse_mode="Markdown",
    )
