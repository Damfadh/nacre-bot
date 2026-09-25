# Blueprint & Documentation: Automated PDD/Humas Database System (Antigravity)

Dokumen ini berisi panduan teknis, arsitektur data, prompt AI, dan skema integrasi untuk membangun sistem pengarsipan dokumentasi PDD/Humas otomatis dari **Telegram Channel** ke **Google Sheets / Database** menggunakan **Antigravity**.

---

## 1. Arsitektur & Alur Kerja Sistem (Pipeline)

Sistem ini dirancang menggunakan pendekatan **Pipeline AI Multi-Stage** (non-agentic) untuk menjamin tingkat akurasi tinggi, data yang terstruktur, dan mencegah AI dari halusinasi.

```
[ Telegram Channel ]
        │ (Webhook Event)
        ▼
[ Node 0: Webhook Trigger & Parser ]
        │
        ▼
[ Node 1: AI Extractor ]
        │ (Raw JSON)
        ▼
[ Node 2: AI Classifier & Standardizer ]
        │ (Enriched JSON)
        ▼
[ Node 3: AI Formatter ]
        │ (Structured Output)
        ├───> [ Action A: Google Sheets / DB Insert ]
        └───> [ Action B: Send Telegram Reply ]
```

---

## 2. Struktur Database (Google Sheets / Notion)

Sebelum mengatur prompt pada Antigravity, siapkan tabel/sheet target dengan nama kolom (Header Baris 1) berikut:

| Column | Header Name | Data Type | Description |
| :--- | :--- | :--- | :--- |
| **A** | `ID_Arsip` | String | Unique ID generated system (e.g., `DOC-2026-001`) |
| **B** | `Tanggal_Kegiatan` | Date (`YYYY-MM-DD`) | Tanggal pelaksanaan acara |
| **C** | `Nama_Kegiatan` | String | Nama acara yang sudah dirapikan |
| **D** | `Kategori` | Enum | Kategori utama acara |
| **E** | `Tags` | String | Label/kata kunci pencarian dipisah koma |
| **F** | `Link_Google_Drive` | URL | Link folder/file Drive |
| **G** | `Pengirim` | String | Nama/Username pengirim pesan di Telegram |
| **H** | `Format_Nama_Folder` | String | Standar penamaan folder untuk merapikan Drive |
| **I** | `Waktu_Input` | Timestamp | Waktu saat bot memproses pesan |

---

## 3. Konfigurasi Node & System Prompts Antigravity

---

### NODE 0: Trigger & Raw Input Parser
- **Type:** Telegram Webhook / Listener
- **Input Received:** Message Data
- **Mapped Variables:**
  - `{{telegram_raw_text}}` : Isi teks pesan
  - `{{telegram_sender_name}}` : Nama pengirim pesan
  - `{{telegram_message_id}}` : ID Pesan
  - `{{telegram_chat_id}}` : ID Channel/Group
  - `{{telegram_timestamp}}` : Waktu kirim pesan

---

### NODE 1: AI Extractor (Data Parsing)
- **Model:** Gemini / OpenAI (LLM Standard)
- **Temperature:** `0.0` (Agar hasil sangat presisi dan tidak imajinatif)
- **Role:** Mengekstrak komponen data mentah dari teks tanpa mengubah isi data.

#### System Prompt (Node 1):
```text
Anda adalah AI Data Extractor khusus untuk pengarsipan dokumentasi PDD dan Humas.
Tugas utama Anda adalah menganalisis teks masukan mentah dari Telegram, lalu mengekstrak komponen kunci tanpa mengubah fakta asli.

INSTRUKSI EKSTRAKSI:
1. LINK GOOGLE DRIVE:
   - Cari URL yang mengandung 'drive.google.com'.
   - Jika ditemukan multiple link, ambil link pertama.
   - Jika tidak ada link Google Drive, set nilai menjadi "NULL".

2. TANGGAL ACARA:
   - Identifikasi tanggal kegiatan dari teks (misal: "acara kemarin", "24 Sep 2026", "2026/09/25").
   - Konversikan ke format standar 'YYYY-MM-DD'.
   - Jika teks TIDAK menyebutkan tanggal acara sama sekali, gunakan tanggal dari variabel timestamp sistem: {{telegram_timestamp}}.

3. DESKRIPSI UTAMA:
   - Ambil ringkasan teks atau keterangan acara yang ditulis oleh pengirim (abaikan teks link URL).

FORMAT OUTPUT:
Keluarkan HANYA JSON murni tanpa format markdown codeblock (no ```json).

{
  "raw_text": "{{telegram_raw_text}}",
  "sender": "{{telegram_sender_name}}",
  "link_drive": "URL atau NULL",
  "event_date": "YYYY-MM-DD",
  "raw_description": "Teks deskripsi mentah"
}
```

---

### NODE 2: AI Classifier & Standardizer (Taksonomi Humas)
- **Model:** Gemini / OpenAI
- **Temperature:** `0.2`
- **Input Node:** `{{node1_output}}`
- **Role:** Melakukan klasifikasi, pelabelan (tagging), dan membuat nama folder terstandar.

#### System Prompt (Node 2):
```text
Anda adalah AI Taksonomi & Chief Editor PDD/Humas.
Tugas Anda adalah memproses data JSON dari Node 1, mengklasifikasikannya ke dalam taksonomi resmi organisasi, serta menyusun format penamaan folder yang terstandar.

DAFTAR KATEGORI RESMI (Pilih SATU yang paling tepat):
1. Event Utama : Seminar, Workshop, Lomba, Konferensi, Festival, Pameran.
2. Internal : Rapat, Evaluasi, Pleno, Syukuran, Briefing, Internal Gathering.
3. Publikasi : Konferensi Pers, Press Release, Media Visit, Liputan Khusus.
4. Lapangan : Kunjungan Kerja, Studi Banding, Outbound, Bakti Sosial.
5. Lainnya : Jika tidak memenuhi kategori di atas.

ATURAN STANDARISASI:
1. standardized_title: Buat nama kegiatan singkat, jelas, dan profesional (Maksimal 5 kata). Format Title Case.
2. tags: Buat 2 hingga 4 kata kunci relevan dalam bentuk array string.
3. folder_name_convention: Buat format penamaan folder dengan rumus: [YYYY-MM-DD]_[KategoriWithoutSpace]_[NamaKegiatanUnderscore]
   Contoh: 2026-09-25_EventUtama_Workshop_AI_Humas

INPUT DATA:
{{node1_output}}

FORMAT OUTPUT:
Keluarkan HANYA JSON murni tanpa format markdown codeblock (no ```json).

{
  "link_drive": "Dari Node 1",
  "sender": "Dari Node 1",
  "event_date": "YYYY-MM-DD",
  "category": "Kategori Terpilih",
  "tags": ["Tag1", "Tag2", "Tag3"],
  "standardized_title": "Nama Acara Terstruktur",
  "folder_name_convention": "Format Penamaan Folder",
  "is_valid_entry": true
}
```

---

### NODE 3: AI Formatter & Response Generator
- **Model:** Gemini / OpenAI
- **Temperature:** `0.3`
- **Input Node:** `{{node2_output}}`
- **Role:** Memformat data siap simpan ke Google Sheets dan membuat balasan pesan Telegram.

#### System Prompt (Node 3):
```text
Anda adalah AI Output Formatter dan Telegram Bot Responder.
Tugas Anda adalah merubah JSON dari Node 2 menjadi dua objek utama:
1. Objek data baris untuk Google Sheets.
2. Pesan teks balasan konfirmasi untuk diposting balik ke Telegram.

ATURAN BALASAN TELEGRAM:
- Gunakan bahasa Indonesia yang ramah, rapi, dan profesional.
- Gunakan emoji yang sesuai.
- Jika link_drive bernilai "NULL", berikan pesan peringatan bahwa link Google Drive tidak ditemukan.

INPUT DATA:
{{node2_output}}

FORMAT OUTPUT:
Keluarkan HANYA JSON murni tanpa format markdown codeblock (no ```json).

{
  "status": "success",
  "database_row": {
    "Tanggal_Kegiatan": "event_date",
    "Nama_Kegiatan": "standardized_title",
    "Kategori": "category",
    "Tags": "Tag1, Tag2, Tag3",
    "Link_Google_Drive": "link_drive",
    "Pengirim": "sender",
    "Format_Nama_Folder": "folder_name_convention"
  },
  "telegram_reply_message": "✅ *DOKUMENTASI BERHASIL DIARSIP*\n\n📌 *Kegiatan:* [standardized_title]\n📁 *Kategori:* [category]\n📅 *Tanggal:* [event_date]\n🏷️ *Tags:* #[tag1] #[tag2]\n🔗 *Link:* [link_drive]\n👤 *Pengirim:* [sender]\n\n💡 *Saran Penamaan Folder Drive:* `[folder_name_convention]`"
}
```

---

## 4. Eksekusi Aksi Akhir (Post-Processing Nodes)

Setelah Node 3 selesai memproses JSON, jalankan dua modul integrasi sejajar di Antigravity:

### Action A: Append Row to Google Sheets
- **Integration:** Google Sheets API
- **Action:** Add Row
- **Mapping Column:**
  - `Tanggal_Kegiatan` $\rightarrow$ `{{node3_output.database_row.Tanggal_Kegiatan}}`
  - `Nama_Kegiatan` $\rightarrow$ `{{node3_output.database_row.Nama_Kegiatan}}`
  - `Kategori` $\rightarrow$ `{{node3_output.database_row.Kategori}}`
  - `Tags` $\rightarrow$ `{{node3_output.database_row.Tags}}`
  - `Link_Google_Drive` $\rightarrow$ `{{node3_output.database_row.Link_Google_Drive}}`
  - `Pengirim` $\rightarrow$ `{{node3_output.database_row.Pengirim}}`
  - `Format_Nama_Folder` $\rightarrow$ `{{node3_output.database_row.Format_Nama_Folder}}`
  - `Waktu_Input` $\rightarrow$ `{{system.now}}`

### Action B: Send Telegram Message
- **Integration:** Telegram Bot API
- **Action:** Send Message / Reply to Message
- **Chat ID:** `{{telegram_chat_id}}`
- **Reply To Message ID:** `{{telegram_message_id}}`
- **Message Content:** `{{node3_output.telegram_reply_message}}`
- **Parse Mode:** `Markdown`

---

## 5. Simulasi Testing & Penanganan Error (Edge Cases)

### Kasus 1: Pengirim tidak menyantumkan link Google Drive
* **Hasil Ekstraksi Node 1:** `link_drive` = `"NULL"`
* **Respon Bot Telegram:**
  > ⚠️ *LINK TIDAK DITEMUKAN*
  >
  > Halo @username, sistem tidak menemukan link Google Drive pada pesan Anda. Harap sertakan link Google Drive saat mengirimkan dokumentasi.

### Kasus 2: Penamaan tanggal relatif (Contoh: "Foto Rapat Tadi Siang")
* **Hasil Ekstraksi Node 1:** AI membaca timestamp sistem (misal: `2026-09-25`) dan menetapkan `event_date` secara akurat ke tanggal hari tersebut.

---

## 6. Fitur Opsional Tambahan (Pencarian via Telegram Bot)

Jika ingin menambahkan fitur pencarian database langsung di Telegram, tambahkan **Workflow Baru** di Antigravity dengan trigger Command `/cari` :

1. **Trigger:** Telegram Command `/cari {keyword}`
2. **Action 1:** Google Sheets - Search Rows (Cari baris yang mengandung `{keyword}` pada kolom `Nama_Kegiatan`, `Tags`, atau `Kategori`).
3. **Action 2:** AI Formatter - Merapikan hasil pencarian menjadi list link Drive.
4. **Action 3:** Send Telegram Message - Mengirimkan daftar link Drive ke pengguna.