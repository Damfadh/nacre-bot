"""
Konfigurasi utama bot - membaca dari file .env
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Token Bot Telegram
BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Supabase
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

# Admin IDs (list of int)
_admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = [
    int(uid.strip())
    for uid in _admin_ids_raw.split(",")
    if uid.strip().isdigit()
]

# Validasi konfigurasi wajib
def validate_config() -> None:
    missing = []
    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_KEY")
    if missing:
        raise ValueError(
            f"❌ Variabel berikut belum diset di .env: {', '.join(missing)}\n"
            "Salin .env.example ke .env dan isi nilainya."
        )
