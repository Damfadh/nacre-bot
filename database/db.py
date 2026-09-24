"""
Koneksi ke Supabase dan helper functions untuk database
"""
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

# Singleton client Supabase
_client: Client | None = None


def get_db() -> Client:
    """Mengembalikan instance Supabase client (singleton)."""
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ─────────────────────────────────────────────
# USER operations
# ─────────────────────────────────────────────

def upsert_user(
    user_id: int,
    username: str | None,
    full_name: str,
    role: str = "user"
) -> dict:
    """Buat atau update data user saat /start."""
    db = get_db()
    result = (
        db.table("users")
        .upsert(
            {
                "id": user_id,
                "username": username,
                "full_name": full_name,
                "role": role,
                "last_active": "now()",
            },
            on_conflict="id",
        )
        .execute()
    )
    return result.data[0] if result.data else {}


def get_user(user_id: int) -> dict | None:
    """Ambil data user berdasarkan Telegram ID."""
    db = get_db()
    result = db.table("users").select("*").eq("id", user_id).single().execute()
    return result.data


def set_user_role(user_id: int, role: str) -> bool:
    """Ubah role user ('admin' atau 'user')."""
    db = get_db()
    result = (
        db.table("users")
        .update({"role": role})
        .eq("id", user_id)
        .execute()
    )
    return bool(result.data)


def ban_user(user_id: int, banned: bool = True) -> bool:
    """Ban atau unban user."""
    db = get_db()
    result = (
        db.table("users")
        .update({"is_banned": banned})
        .eq("id", user_id)
        .execute()
    )
    return bool(result.data)


# ─────────────────────────────────────────────
# PHOTO operations
# ─────────────────────────────────────────────

def add_photo(
    title: str,
    gdrive_link: str | None = None,
    telegram_file_id: str | None = None,
    description: str | None = None,
    category: str = "umum",
    uploaded_by: int | None = None,
) -> dict:
    """Simpan foto baru ke database."""
    db = get_db()

    # Ekstrak file ID dari link GDrive
    gdrive_file_id = None
    source_type = "telegram"
    if gdrive_link:
        gdrive_file_id = extract_gdrive_id(gdrive_link)
        source_type = "gdrive"

    result = (
        db.table("photos")
        .insert(
            {
                "title": title,
                "description": description,
                "category": category,
                "gdrive_link": gdrive_link,
                "gdrive_file_id": gdrive_file_id,
                "telegram_file_id": telegram_file_id,
                "source_type": source_type,
                "uploaded_by": uploaded_by,
            }
        )
        .execute()
    )
    return result.data[0] if result.data else {}


def search_photos(keyword: str = "", category: str | None = None) -> list[dict]:
    """Cari foto berdasarkan keyword atau kategori."""
    db = get_db()
    query = db.table("photos").select("*").eq("is_active", True)

    if category:
        query = query.eq("category", category)
    if keyword:
        query = query.ilike("title", f"%{keyword}%")

    result = query.order("created_at", desc=True).limit(20).execute()
    return result.data or []


def get_photo(photo_id: int) -> dict | None:
    """Ambil detail foto berdasarkan ID."""
    db = get_db()
    result = db.table("photos").select("*").eq("id", photo_id).single().execute()
    return result.data


def delete_photo(photo_id: int) -> bool:
    """Nonaktifkan foto (soft delete)."""
    db = get_db()
    result = (
        db.table("photos")
        .update({"is_active": False})
        .eq("id", photo_id)
        .execute()
    )
    return bool(result.data)


def list_categories() -> list[str]:
    """Daftar semua kategori yang tersedia."""
    db = get_db()
    result = (
        db.table("photos")
        .select("category")
        .eq("is_active", True)
        .execute()
    )
    categories = list({row["category"] for row in (result.data or [])})
    return sorted(categories)


# ─────────────────────────────────────────────
# LOG operations
# ─────────────────────────────────────────────

def log_request(user_id: int, photo_id: int) -> None:
    """Catat log setiap kali user request foto."""
    db = get_db()
    db.table("request_logs").insert(
        {"user_id": user_id, "photo_id": photo_id}
    ).execute()


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def extract_gdrive_id(link: str) -> str | None:
    """
    Ekstrak file ID dari berbagai format link Google Drive.
    Contoh:
      https://drive.google.com/file/d/FILE_ID/view
      https://drive.google.com/open?id=FILE_ID
      https://drive.google.com/uc?id=FILE_ID
    """
    import re
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
        r"/folders/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)
    return None
