# Blueprint & Documentation: Channel Audit & Sorting Workflow (Antigravity)

Dokumen ini berisi spesifikasi teknis dan prompt khusus untuk membangun **Bot Pembersih & Penyortir Channel Telegram**. Modul ini dirancang terpisah dari bot harian untuk melakukan audit massal (*batch audit*) terhadap riwayat pesan yang sudah menumpuk di channel.

---

## 1. Arsitektur Audit & Penyortiran Data

Sistem ini bekerja secara periodik atau berdasarkan perintah (*trigger command*) untuk memindai isi channel, memvalidasi tautan, menghapus duplikasi, dan menyusun ulang database.

```
[ Trigger Command: /audit_channel ]
                 │
                 ▼
[ Node 0: Fetch Batch Messages (Telegram API) ]
                 │
                 ▼
[ Node 1: Deduplication & Link Extractor ]
                 │
                 ▼
[ Node 2: HTTP Link Validator (Status Check) ]
                 │
                 ▼
[ Node 3: AI Categorizer & Sorting Engine ]
                 │
                 ▼
[ Action Output: Multi-Tab Google Sheets / Report Summary ]
```

---

## 2. Status Output & Skema Log Audit

Hasil audit akan dipisahkan ke dalam **3 Tab Google Sheets** berbeda atau kategori laporan:

1. **Tab 1: `[ACTIVE_VALID]`** $\rightarrow$ Link Google Drive aktif, tidak duplikat, dan sudah dikategorikan.
2. **Tab 2: `[DUPLICATE]`** $\rightarrow$ Link yang diunggah lebih dari sekali (hanya entri terbaru/pertama yang disimpan di Tab Active).
3. **Tab 3: `[BROKEN_RESTRICTED]`** $\rightarrow$ Link 404 (mati/dihapus) atau status *Access Denied* (butuh izin akses).

---

## 3. Konfigurasi Node & System Prompts Antigravity

---

### NODE 0: Batch Fetcher (Telegram Integration)
- **Trigger:** Command `/audit_channel` atau Scheduled Trigger (Misal: Setiap Minggu malam).
- **Target:** Channel Dokumentasi PDD/Humas.
- **Action:** Ambil $N$ pesan terakhir (misal 500-1000 pesan).

---

### NODE 1: Deduplication & Raw Parser
- **Type:** Code / Logic Processing Node.
- **Function:** 
  1. Ekstrak semua URL Google Drive dari pesan.
  2. Bandingkan URL satu sama lain.
  3. Tandai URL yang sama sebagai `DUPLICATE`.

---

### NODE 2: Link Access & Status Checker (HTTP Node)
- **Type:** HTTP Request / API Checker
- **Action:** Melakukan *HEAD request* atau pengecekan via Google Drive API ke setiap URL.
- **Rules Penentuan Status:**
  - `HTTP Status 200`: Status **VALID / OK**.
  - `HTTP Status 404 / 410`: Status **BROKEN / NOT FOUND** (Folder/file sudah dihapus).
  - `HTTP Status 403 / Access Denied`: Status **RESTRICTED** (Akses belum dibuka ke "Public/Anyone with link").

---

### NODE 3: AI Categorizer & Sorting Engine
- **Model:** Gemini / OpenAI
- **Temperature:** `0.1`
- **Role:** Menganalisis pesan-pesan yang berstatus `VALID`, mengelompokkannya ke dalam kategori PDD/Humas, dan menyusun laporan ringkasan audit.

#### System Prompt (Node 3):
```text
Anda adalah AI Auditor Database Dokumentasi PDD/Humas.
Tugas Anda adalah memproses array data link yang telah dibersihkan dari duplikasi dan diperiksa status HTTP-nya, kemudian mengelompokkan link yang VALID ke dalam kategori resmi serta menyusun laporan ringkasan.

DAFTAR KATEGORI RESMI:
- Event Utama (Seminar, Workshop, Lomba, Konferensi, Festival)
- Internal (Rapat, Evaluasi, Pleno, Syukuran, Briefing)
- Publikasi (Konferensi Pers, Press Release, Media Visit)
- Lapangan (Kunjungan Kerja, Studi Banding, Outbound)
- Lainnya (Jika tidak relevan dengan kategori di atas)

INSTRUKSI SORTING:
1. Hanya proses item dengan status HTTP = "VALID".
2. Kelompokkan item berdasarkan "category".
3. Urutkan berdasarkan "event_date" dari yang terbaru ke yang tertua.
4. Buat laporan ringkasan (*Audit Summary*) yang akan dikirimkan ke Admin Telegram.

INPUT DATA:
{{node2_output_array}}

FORMAT OUTPUT:
Keluarkan HANYA JSON murni tanpa format markdown codeblock (no ```json).

{
  "audit_summary": {
    "total_processed": 100,
    "valid_links_count": 80,
    "duplicate_links_count": 12,
    "broken_restricted_count": 8
  },
  "categorized_valid_data": [
    {
      "category": "Event Utama",
      "items": [
        {
          "title": "Workshop AI Humas",
          "event_date": "2026-09-25",
          "link_drive": "https://drive.google.com/...",
          "sender": "@user1"
        }
      ]
    }
  ],
  "broken_or_restricted_list": [
    {
      "link_drive": "https://drive.google.com/...",
      "issue_type": "RESTRICTED / ACCESS_DENIED",
      "sender": "@user2",
      "message_id": 1234
    }
  ],
  "telegram_report_message": "Teks pesan ringkasan audit untuk Admin Telegram"
}
```

---

## 4. Format Laporan Audit Telegram (Auto Response)

Pesan ringkasan yang dikirimkan oleh Bot ke Telegram setelah proses penyortiran selesai:

```text
🧹 *LAPORAN AUDIT & PENYORTIRAN CHANNEL*
----------------------------------------
📊 *Ringkasan Hasil Scan:*
• Total Pesan Diperiksa: `100`
• Link Valid & Aktif: `80`
• Link Duplikat (Dieliminasi): `12`
• Link Error/Restricted: `8`

----------------------------------------
⚠️ *TINDAKAN DIPERLUKAN (LINK ERROR/RESTRICTED):*
1. 🔗 [Link Drive Rapat] - *Error: Access Denied* (Pengirim: @user2)
2. 🔗 [Link Foto Seminar] - *Error: 404 Not Found* (Pengirim: @user5)

----------------------------------------
✅ *UPDATE DATABASE:*
Semua data valid (80 link) telah disortir dan dimasukkan ke dalam Sheet Target berdasarkan kategorinya masing-masing.

📄 *Cek Database Rapi:* [Link Google Sheets]
```

---

## 5. Instruksi Penanganan Hasil Audit

1. **Link Duplikat:** Otomatis dipindahkan ke tab `[DUPLICATE]` di Sheets agar database utama bersih tanpa mempengaruhi riwayat chat Telegram asli.
2. **Link Restricted (Akses Tertutup):** Bot menyebut nama pengirim (`@username`) pada laporan audit agar admin bisa meminta pengirim membuka *permission* Google Drive menjadi *"Anyone with the link"*.
3. **Penyortiran Kategori:** Data pada tab `[ACTIVE_VALID]` secara otomatis terpisah per sheet/view berdasarkan kategori (Event Utama, Internal, Publikasi, Lapangan).