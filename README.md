# Nacre Bot 🤖

Bot Telegram untuk mengakses dan mendistribusikan koleksi foto dari Google Drive & Telegram.

## ✨ Fitur

- 📸 Simpan & kirim foto dari **Google Drive** atau **Telegram Document**
- 🔍 Pencarian foto berdasarkan judul atau kategori
- 👑 Sistem **role** (Admin & User)
- 🚫 Manajemen ban/unban user
- 📊 Logging setiap request foto

## 🗂️ Struktur Proyek

```
Nacre Bot/
├── bot.py              # Entry point utama
├── config.py           # Konfigurasi dari .env
├── requirements.txt    # Dependensi
├── .env.example        # Template konfigurasi
├── database/
│   ├── __init__.py
│   ├── db.py           # CRUD Supabase
│   └── schema.sql      # Schema database
├── handlers/
│   ├── __init__.py
│   ├── common.py       # /start, /help, /cari, /kategori
│   ├── admin.py        # /tambah, /hapus, /setadmin, /ban
│   ├── callbacks.py    # Callback user
│   ├── admin_callbacks.py # Callback admin
│   └── permissions.py  # Decorator role
└── utils/
    ├── __init__.py
    └── gdrive.py       # Download dari Google Drive
```

## 🚀 Setup

### 1. Clone & Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Buat Bot Telegram

1. Chat dengan [@BotFather](https://t.me/BotFather) di Telegram
2. Ketik `/newbot` dan ikuti instruksinya
3. Simpan **Bot Token** yang diberikan

### 3. Setup Supabase

1. Daftar di [supabase.com](https://supabase.com) (gratis)
2. Buat project baru
3. Buka **SQL Editor** → paste isi file `database/schema.sql` → Run
4. Buka **Project Settings → API** → copy:
   - `Project URL`
   - `anon public` key

### 4. Konfigurasi .env

```bash
cp .env.example .env
```

Edit file `.env`:
```env
TELEGRAM_BOT_TOKEN=token_dari_botfather
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJ...
ADMIN_IDS=123456789
```

> **Cara dapat Telegram User ID:** Kirim pesan ke [@userinfobot](https://t.me/userinfobot)

### 5. Jalankan Bot

```bash
python bot.py
```

## 📋 Perintah Bot

### User Biasa

| Perintah | Keterangan |
|----------|-----------|
| `/start` | Menu utama |
| `/cari [kata kunci]` | Cari foto |
| `/kategori` | Lihat semua kategori |
| `/help` | Bantuan |

### Admin

| Perintah | Keterangan |
|----------|-----------|
| `/tambah` | Tambah foto baru (dialog interaktif) |
| `/hapus [ID]` | Hapus foto |
| `/setadmin [user_id]` | Jadikan user sebagai admin |
| `/ban [user_id]` | Ban user |
| `/unban [user_id]` | Unban user |

## 📎 Cara Tambah Foto (Admin)

**Via Google Drive:**
1. Upload foto ke Google Drive
2. Klik kanan → "Bagikan" → ubah ke "Siapa saja yang memiliki link"
3. Copy link → kirim ke bot saat proses `/tambah`

**Via Telegram Document:**
1. Jalankan `/tambah`
2. Isi judul, kategori, deskripsi
3. Di langkah terakhir, kirim foto sebagai **File** (bukan gambar biasa)

## ☁️ Deployment (Opsional)

Bot bisa dijalankan 24/7 di:
- **Railway.app** (gratis)
- **Render.com** (gratis)
- **VPS** dengan `screen` atau `pm2`

Buat file `Procfile` untuk Railway/Render:
```
worker: python bot.py
```
