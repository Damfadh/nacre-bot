"""
Decorator & helper untuk cek role user
"""
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_IDS
from database import get_user, upsert_user


def require_not_banned(func):
    """Decorator: tolak user yang dibanned."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        db_user = get_user(user.id)
        if db_user and db_user.get("is_banned"):
            await update.message.reply_text(
                "⛔ Akun Anda telah dibanned dari bot ini."
            )
            return
        return await func(update, context)
    return wrapper


def require_admin(func):
    """Decorator: hanya admin yang bisa akses handler ini."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        db_user = get_user(user.id)

        is_admin = (
            user.id in ADMIN_IDS
            or (db_user and db_user.get("role") == "admin")
        )
        if not is_admin:
            await update.message.reply_text(
                "⛔ Perintah ini hanya bisa digunakan oleh admin."
            )
            return
        return await func(update, context)
    return wrapper


def get_or_create_user(telegram_user) -> dict:
    """Buat atau update user di database, kembalikan data user."""
    full_name = telegram_user.full_name or telegram_user.first_name or "Unknown"
    return upsert_user(
        user_id=telegram_user.id,
        username=telegram_user.username,
        full_name=full_name,
    )


def is_admin(user_id: int) -> bool:
    """Cek apakah user adalah admin."""
    if user_id in ADMIN_IDS:
        return True
    db_user = get_user(user_id)
    return bool(db_user and db_user.get("role") == "admin")
