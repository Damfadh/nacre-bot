"""
Modul integrasi Google Gemini AI menggunakan SDK resmi terbaru: google-genai
Menggunakan Interactions API (gemini-3.8-flash).
"""
import asyncio
import base64
import json
import os
from pathlib import Path

from google import genai
from config import GEMINI_API_KEY

_client = None

# Riwayat interaction per user: {user_id: interaction_id}
_user_interaction_ids: dict[int, str] = {}

SYSTEM_PROMPT = """Kamu adalah asisten bot Nacre yang ramah dan helpful.
Bot ini adalah galeri foto digital dan sistem dokumentasi Humas/PDD. Kamu membantu user:
- Mencari foto atau dokumentasi kegiatan
- Menjawab pertanyaan seputar koleksi dokumentasi
- Memberikan bantuan umum dengan ramah dan santai

Jawab dalam Bahasa Indonesia yang santai, ringkas, dan jelas. Maksimal 3 paragraf."""


def get_client() -> genai.Client:
    """Singleton Client google-genai dengan API Key dinamis."""
    global _client
    key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY belum diset!")
    if _client is None:
        _client = genai.Client(api_key=key)
    return _client


def clear_chat_session(user_id: int) -> None:
    """Reset riwayat chat user."""
    _user_interaction_ids.pop(user_id, None)


# ─────────────────────────────────────────────
# CHAT AI (Interactions API Multi-Turn)
# ─────────────────────────────────────────────

async def chat_with_ai(user_id: int, message: str) -> str:
    """
    Chat dengan Gemini 3.8 Flash menggunakan Interactions API.
    Mendukung percakapan multi-turn otomatis melalui previous_interaction_id.
    Dilengkapi auto-retry untuk mengatasi lonjakan antrean (503 transient error).
    """
    loop = asyncio.get_event_loop()
    try:
        client = get_client()
    except Exception as e:
        return f"❌ Konfigurasi AI belum siap: {e}"

    prev_id = _user_interaction_ids.get(user_id)

    for attempt in range(3):
        try:
            def _call_api():
                kwargs = {
                    "model": "gemini-3.8-flash",
                    "system_instruction": SYSTEM_PROMPT,
                    "input": message,
                }
                if prev_id:
                    kwargs["previous_interaction_id"] = prev_id
                return client.interactions.create(**kwargs)

            res = await loop.run_in_executor(None, _call_api)
            if res and hasattr(res, "id"):
                _user_interaction_ids[user_id] = res.id
            if hasattr(res, "output_text") and res.output_text:
                return res.output_text
            return str(res)

        except Exception as e:
            err_msg = str(e)
            print(f"[AI Chat] Attempt {attempt+1} error: {err_msg}")

            # Jika previous_interaction_id invalid/expired, reset session dan coba ulang
            if prev_id and ("not found" in err_msg.lower() or "invalid" in err_msg.lower() or "404" in err_msg):
                prev_id = None
                _user_interaction_ids.pop(user_id, None)
                continue

            # Jika 503 / temporary unavailable, coba ulang hingga 3x
            if "503" in err_msg or "UNAVAILABLE" in err_msg or "high demand" in err_msg.lower():
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                return "⚠️ Server AI Google sedang mengalami lonjakan antrean (503). Silakan coba lagi dalam beberapa detik ya!"

            # Jika 429 quota
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                return "⚠️ Kuota penggunaan AI gratis sedang penuh. Silakan coba beberapa saat lagi."

            return f"❌ Terjadi kendala pada layanan AI: {err_msg[:120]}"

    return "⚠️ Server AI sedang sibuk. Silakan coba lagi."



# ─────────────────────────────────────────────
# SMART SEARCH
# ─────────────────────────────────────────────

async def ai_smart_search(query: str, all_photos: list[dict]) -> list[dict]:
    """
    Cari foto yang relevan menggunakan AI berdasarkan deskripsi natural.
    """
    if not all_photos:
        return []

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
        client = get_client()
        res = await loop.run_in_executor(
            None,
            lambda: client.interactions.create(
                model="gemini-3.8-flash",
                input=prompt,
            )
        )
        result = res.output_text.strip() if hasattr(res, "output_text") else ""

        if result == "NONE" or not result:
            return []

        ids = [int(x.strip()) for x in result.split(",") if x.strip().isdigit()]
        photo_map = {p["id"]: p for p in all_photos}
        return [photo_map[pid] for pid in ids if pid in photo_map]

    except Exception as e:
        print(f"[AI Search] Error: {e}")
        return []


# ─────────────────────────────────────────────
# AUTO CAPTION & MODERASI
# ─────────────────────────────────────────────

async def generate_photo_caption(image_path: str) -> dict:
    """Generate judul & deskripsi singkat untuk foto."""
    filename = Path(image_path).stem.replace("_", " ").replace("-", " ")
    return {
        "judul": filename.title() if filename else "Dokumentasi Baru",
        "deskripsi": f"Foto dokumentasi diunggah ke arsip.",
        "kategori": "umum",
    }


async def moderate_image(image_path: str) -> dict:
    """Moderasi foto: default aman."""
    return {"safe": True, "reason": "Foto dinyatakan aman"}
