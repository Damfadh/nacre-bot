"""
Modul integrasi Google Gemini AI
Fitur:
- Chat bebas dengan AI
- Smart search foto
- Auto generate caption/deskripsi foto
- Moderasi konten foto
"""
import asyncio
import base64
import os
from pathlib import Path

import google.generativeai as genai
from config import GEMINI_API_KEY

# Konfigurasi Gemini
genai.configure(api_key=GEMINI_API_KEY)

# Model untuk text
_text_model = None
# Model untuk vision (gambar)
_vision_model = None

# Riwayat chat per user: {user_id: ChatSession}
_chat_sessions: dict[int, any] = {}

SYSTEM_PROMPT = """Kamu adalah asisten bot Nacre yang ramah dan helpful.
Bot ini adalah galeri foto digital. Kamu membantu user:
- Mencari foto berdasarkan deskripsi
- Menjawab pertanyaan seputar koleksi foto
- Memberikan saran foto yang mungkin cocok

Jawab dalam Bahasa Indonesia yang santai dan singkat. Maksimal 3 paragraf.
Jika pertanyaan tidak relevan dengan foto/galeri, tetap jawab dengan sopan tapi arahkan ke topik utama."""


def get_text_model():
    """Singleton Gemini text model."""
    global _text_model
    if _text_model is None:
        key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
        if key:
            genai.configure(api_key=key)
        _text_model = genai.GenerativeModel(
            model_name="gemini-3.8-flash",
            system_instruction=SYSTEM_PROMPT,
        )
    return _text_model


def get_vision_model():
    """Singleton Gemini vision model (untuk analisis gambar)."""
    global _vision_model
    if _vision_model is None:
        key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
        if key:
            genai.configure(api_key=key)
        _vision_model = genai.GenerativeModel("gemini-3.8-flash")
    return _vision_model


def get_chat_session(user_id: int):
    """Ambil atau buat chat session untuk user (menyimpan riwayat)."""
    if user_id not in _chat_sessions:
        model = get_text_model()
        _chat_sessions[user_id] = model.start_chat(history=[])
    return _chat_sessions[user_id]


def clear_chat_session(user_id: int) -> None:
    """Reset riwayat chat user."""
    if user_id in _chat_sessions:
        del _chat_sessions[user_id]


# ─────────────────────────────────────────────
# CHAT AI
# ─────────────────────────────────────────────

async def chat_with_ai(user_id: int, message: str) -> str:
    """
    Chat dengan Gemini (dengan memori percakapan per user).
    Returns: jawaban AI sebagai string
    """
    loop = asyncio.get_event_loop()
    try:
        session = get_chat_session(user_id)
        response = await loop.run_in_executor(
            None, lambda: session.send_message(message)
        )
        return response.text
    except Exception as e:
        return f"❌ AI error: {str(e)[:200]}"


# ─────────────────────────────────────────────
# SMART SEARCH
# ─────────────────────────────────────────────

async def ai_smart_search(query: str, all_photos: list[dict]) -> list[dict]:
    """
    Gunakan AI untuk mencari foto yang relevan berdasarkan deskripsi natural.
    Mengembalikan list foto yang diranking berdasarkan relevansi.
    """
    if not all_photos:
        return []

    # Buat daftar foto untuk AI
    photo_list = "\n".join([
        f"ID:{p['id']} | Judul:{p['title']} | Kategori:{p['category']} | Deskripsi:{p.get('description') or '-'}"
        for p in all_photos
    ])

    prompt = f"""Dari daftar foto berikut, temukan yang paling relevan dengan pencarian: "{query}"

Daftar foto:
{photo_list}

Kembalikan HANYA ID foto yang relevan, pisahkan dengan koma. Maksimal 5 foto.
Jika tidak ada yang relevan, kembalikan kata: NONE
Contoh output: 1,3,7"""

    loop = asyncio.get_event_loop()
    try:
        model = get_text_model()
        response = await loop.run_in_executor(
            None, lambda: model.generate_content(prompt)
        )
        result = response.text.strip()

        if result == "NONE" or not result:
            return []

        # Parse ID yang dikembalikan AI
        ids = [int(x.strip()) for x in result.split(",") if x.strip().isdigit()]
        photo_map = {p["id"]: p for p in all_photos}
        return [photo_map[pid] for pid in ids if pid in photo_map]

    except Exception as e:
        print(f"[AI Search] Error: {e}")
        return []


# ─────────────────────────────────────────────
# AUTO CAPTION / DESKRIPSI
# ─────────────────────────────────────────────

async def generate_photo_caption(image_path: str) -> dict:
    """
    Analisis foto menggunakan Gemini Vision dan generate:
    - Judul singkat
    - Deskripsi detail
    - Kategori yang disarankan
    """
    loop = asyncio.get_event_loop()
    try:
        # Baca file gambar
        with open(image_path, "rb") as f:
            image_data = f.read()

        image_part = {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(image_data).decode("utf-8"),
        }

        prompt = """Analisis foto ini dan berikan dalam format JSON berikut:
{
  "judul": "judul singkat 3-5 kata dalam bahasa Indonesia",
  "deskripsi": "deskripsi 1-2 kalimat dalam bahasa Indonesia",
  "kategori": "satu kata kategori: landscape/portrait/produk/event/kuliner/nature/arsitektur/lainnya"
}
Hanya kembalikan JSON, tanpa teks lain."""

        model = get_vision_model()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content([prompt, image_part])
        )

        import json
        text = response.text.strip()
        # Bersihkan markdown code block jika ada
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)

    except Exception as e:
        print(f"[AI Caption] Error: {e}")
        return {
            "judul": "Foto Baru",
            "deskripsi": None,
            "kategori": "lainnya",
        }


# ─────────────────────────────────────────────
# MODERASI KONTEN
# ─────────────────────────────────────────────

async def moderate_image(image_path: str) -> dict:
    """
    Cek apakah gambar aman untuk diposting.
    Returns: {"safe": bool, "reason": str}
    """
    loop = asyncio.get_event_loop()
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()

        image_part = {
            "mime_type": "image/jpeg",
            "data": base64.b64encode(image_data).decode("utf-8"),
        }

        prompt = """Apakah gambar ini aman dan pantas untuk galeri foto publik?
Periksa: konten dewasa, kekerasan, ujaran kebencian, atau konten berbahaya.

Jawab HANYA dengan format JSON:
{"safe": true/false, "reason": "alasan singkat"}"""

        model = get_vision_model()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content([prompt, image_part])
        )

        import json
        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)

    except Exception as e:
        print(f"[AI Moderate] Error: {e}")
        return {"safe": True, "reason": "moderasi tidak tersedia"}
