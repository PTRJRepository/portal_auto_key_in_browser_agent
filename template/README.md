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

Jalankan satu aplikasi monolit dari folder root `template/`:

```bash
npm run dev
```

Buka:

```text
http://localhost:9001
```

Mode ini menjalankan UI, API, WebSocket, recorder Playwright, runner, dan template store dalam satu service lokal.

## Cara Pakai (Usage)

### A. Rekam template baru

1. Klik `Start Recording`.
2. Isi URL halaman awal (misalnya halaman form).
3. Browser Chromium akan terbuka dan mulai merekam interaksi.
4. Lakukan semua aksi (klik, isi input, select, dll).
5. Selama recording aktif, canvas flow dan daftar step di editor akan update real-time.
6. Kembali ke editor, klik `Stop Recording`.
7. Flow final hasil rekaman otomatis tersimpan sebagai template baru.

### B. Inspect flow template

1. Pilih template di panel kiri.
2. Lihat flow di `Workflow Canvas`.
3. Klik node untuk melihat detail di `Agent Inspector`.
4. Raw event tetap tampil di `Live Events`, tetapi template hanya menyimpan clean committed steps.

### C. Jalankan ulang template

1. Isi nilai variable di panel `Variables`.
2. Klik `Replay Draft` untuk menjalankan flow versi editor saat ini.
3. Klik `Recall Saved` untuk menjalankan template yang tersimpan persis dari storage.
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
npm run dev            # build UI lalu jalankan monolith di http://localhost:9001
npm run start          # build UI + agent lalu jalankan hasil build
npm run dev:agent      # jalankan local automation agent langsung
npm run dev:editor     # jalankan Vite editor standalone untuk development UI
npm run test           # jalankan semua test workspace
npm run typecheck      # cek TypeScript semua workspace
npm run build          # build semua workspace
```

## Catatan Recording v1

- Raw browser event tidak langsung disimpan sebagai step.
- Input yang diketik berurutan pada selector dan URL yang sama diringkas menjadi satu step dengan nilai akhir.
- Username dan password disimpan sebagai fixed value agar replay sama persis.
- Idle setelah event selesai tidak membuat step baru.
- Navigation/click/input duplikat yang berurutan dibuang oleh normalizer.
- Action bermakna yang terjadi di antara input, click, atau key press tetap dipertahankan agar replay tidak berubah urutan.

## Batasan v1

- Flow masih linear (belum ada branch/loop)
- Browser support: Chromium saja
- Replay selalu fresh session (belum persistent profile)
- Belum ada multi-tab orchestration kompleks
