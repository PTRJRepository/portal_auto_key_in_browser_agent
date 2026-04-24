# All-in-One Browser Auto Key-In Template Creator

Template creator ini dipakai untuk:

- Rekam interaksi browser (Chromium)
- Ubah hasil rekaman jadi flow linear visual (gaya n8n)
- Edit step, ubah value jadi variable placeholder
- Export/Import JSON template
- Jalankan ulang template dengan input variable baru

## Struktur Project

- `apps/editor-web`: UI template creator (React + React Flow)
- `apps/local-agent`: Local service HTTP + WebSocket + Playwright
- `packages/flow-schema`: Kontrak schema JSON dan validasi (Zod)
- `templates`: Hasil export/import template JSON

## Prasyarat

- Node.js `>= 22`
- npm `>= 10`
- OS: Windows/macOS/Linux

## Setup Awal

Jalankan dari folder root `template/`.

1. Install dependency workspace:

```bash
npm install
```

2. Install browser Chromium untuk Playwright (sekali saja):

```bash
npm run setup:chromium
```

## Menjalankan Aplikasi

Gunakan 2 terminal terpisah.

Terminal 1 - jalankan local agent:

```bash
npm run dev:agent
```

Terminal 2 - jalankan editor web:

```bash
npm run dev:editor
```

Buka URL editor dari output Vite (default: `http://localhost:5173`).

## Cara Pakai (Usage)

### A. Rekam template baru

1. Klik `Start Recording`.
2. Isi URL halaman awal (misalnya halaman form).
3. Browser Chromium akan terbuka dan mulai merekam interaksi.
4. Lakukan semua aksi (klik, isi input, select, dll).
5. Selama recording aktif, canvas flow dan daftar step di editor akan update real-time.
6. Kembali ke editor, klik `Stop Recording`.
7. Flow final hasil rekaman otomatis tersimpan sebagai template baru.

### B. Edit flow template

1. Pilih template di panel kiri.
2. Atur urutan step dengan tombol `Up` / `Down`.
3. Ubah `Label`, `Selector`, dan `Value` di step editor.
4. Atur `Data Mode` per step/event:
   - `Fixed Value`
   - `Variable`
   - `Generated: Timestamp`
   - `Generated: Random Number`
   - `Generated: UUID`
5. Klik `Convert Value to Variable` kalau ingin value jadi placeholder reusable.
6. Klik `Optimize Flow` untuk membersihkan step berulang tanpa mengubah alur utama.

### C. Jalankan ulang template

1. Isi nilai variable di panel `Variables`.
2. Klik `Start (Strict)` untuk menjalankan flow versi editor saat ini.
3. Klik `Recall Saved (100%)` untuk menjalankan template yang tersimpan persis dari storage.
4. Cek nilai `Fidelity` pada hasil run. Target recall adalah `100%` dan `exact match`.
5. Lihat status hasil run dan log event di panel `Live Events`.

### D. Export / Import

- Export:
  - Pilih template, klik `Export JSON`
  - File `.json` akan terunduh
- Import:
  - Klik `Import JSON`
  - Pilih file template `.json`
  - Sistem otomatis melakukan optimasi step berulang saat import

Contoh template tersedia di:
- `templates/sample-login-template.json`

## Command Penting

```bash
npm run dev:agent      # jalankan local automation agent
npm run dev:editor     # jalankan UI template creator
npm run test           # jalankan semua test workspace
npm run typecheck      # cek TypeScript semua workspace
npm run build          # build semua workspace
```

## Batasan v1

- Flow masih linear (belum ada branch/loop)
- Browser support: Chromium saja
- Replay selalu fresh session (belum persistent profile)
- Belum ada multi-tab orchestration kompleks
