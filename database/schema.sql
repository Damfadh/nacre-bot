-- ============================================================
-- Jalankan SQL ini di Supabase SQL Editor
-- URL: https://supabase.com/dashboard → SQL Editor
-- ============================================================

-- Tabel untuk menyimpan data user/member bot
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    role TEXT DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    is_banned BOOLEAN DEFAULT FALSE,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    last_active TIMESTAMPTZ DEFAULT NOW()
);

-- Tabel untuk menyimpan koleksi foto (link GDrive)
CREATE TABLE IF NOT EXISTS photos (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT DEFAULT 'umum',
    gdrive_link TEXT,
    gdrive_file_id TEXT,
    telegram_file_id TEXT,
    source_type TEXT DEFAULT 'gdrive' CHECK (source_type IN ('gdrive', 'telegram')),
    uploaded_by BIGINT REFERENCES users(id),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabel untuk log request user
CREATE TABLE IF NOT EXISTS request_logs (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    photo_id INT REFERENCES photos(id),
    requested_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index untuk pencarian cepat
CREATE INDEX IF NOT EXISTS idx_photos_category ON photos(category);
CREATE INDEX IF NOT EXISTS idx_photos_active ON photos(is_active);
CREATE INDEX IF NOT EXISTS idx_photos_title ON photos USING gin(to_tsvector('simple', title));

-- Function untuk auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_photos_updated_at
    BEFORE UPDATE ON photos
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Aktifkan Row Level Security (RLS) - opsional untuk keamanan tambahan
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE photos ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_logs ENABLE ROW LEVEL SECURITY;

-- Policy: izinkan semua operasi via service_role (yang dipakai bot)
CREATE POLICY "Allow all for service role" ON users FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON photos FOR ALL USING (true);
CREATE POLICY "Allow all for service role" ON request_logs FOR ALL USING (true);
