# Auto Key In Refactor

Aplikasi desktop PySide6 untuk mengambil data Manual Adjustment API, menjalankan Auto Key-In PlantwareP3 melalui runner Playwright TypeScript, menyimpan session login per divisi, dan melakukan verifikasi hasil ke `db_ptrj`.

## Prasyarat

Install di komputer:

- Python 3.11+.
- Node.js 20+ atau 22+.
- Git.
- Akses jaringan ke PlantwareP3, default `http://plantwarep3:8001`.
- Akses ke Manual Adjustment API, default `http://localhost:8002`.

## Setup Dari GitHub

Masuk ke folder project:

```powershell
cd "D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor"
```

Atau clone baru:

```powershell
git clone <URL_REPOSITORY_GITHUB> "D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor"
cd "D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor"
```

Jalankan setup Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Setup ini akan:

1. Membuat `.env` dari `.env.example` jika belum ada.
2. Install package Python dengan `pip install -e .[dev]`.
3. Install dependency runner Node.js.
4. Build runner TypeScript ke `runner/dist`.
5. Install Chromium untuk Playwright.

Jika memakai Git Bash:

```bash
bash setup.sh
```

## Konfigurasi `.env`

Edit `.env` setelah setup selesai. Minimal isi:

```env
AUTO_KEY_IN_API_BASE_URL=http://localhost:8002
AUTO_KEY_IN_API_KEY=isi_api_key_manual_adjustment
AUTO_KEY_IN_RUNNER_COMMAND=node runner/dist/cli.js

AUTO_KEY_IN_DEFAULT_PERIOD_MONTH=4
AUTO_KEY_IN_DEFAULT_PERIOD_YEAR=2026
AUTO_KEY_IN_DEFAULT_DIVISION_CODE=AB1
AUTO_KEY_IN_DEFAULT_RUNNER_MODE=multi_tab_shared_session
AUTO_KEY_IN_DEFAULT_MAX_TABS=5
AUTO_KEY_IN_HEADLESS=false

PLANTWARE_BASE_URL=http://plantwarep3:8001
PLANTWARE_USERNAME=isi_username_plantware
PLANTWARE_PASSWORD=isi_password_plantware
PLANTWARE_DIVISION=AB1
```

Catatan:

- Jangan commit `.env`.
- `.env` sudah di-ignore oleh `.gitignore`.
- `configs/app.json` juga file lokal dan tidak perlu dipush.
- Kalau `.env` sudah benar, tidak perlu edit `configs/app.json`.

## Menjalankan App

Dari root project:

```powershell
python -m app
```

Jika runner belum dibuild:

```powershell
npm --prefix runner run build
```

Jika Chromium Playwright belum terinstall:

```powershell
npx --prefix runner playwright install chromium
```

## Alur Penggunaan

1. Jalankan app dengan `python -m app`.
2. Di tab **Config**, pastikan API Base URL dan API Key sudah terisi.
3. Pilih Period Month, Period Year, Division, dan Category.
4. Klik **Get Session** untuk login Plantware pada divisi yang dipilih.
5. Tunggu Session Status menjadi `Active`.
6. Klik **Fetch / Refresh Data**.
7. Periksa preview record di tab **Process**.
8. Untuk test awal, set Row Limit kecil, misalnya 1 sampai 5.
9. Klik **Run Auto Key-In**.
10. Cek hasil di tab **Summary**.
11. Gunakan tab **Verify db_ptrj** untuk cek data setelah input.

## Alur Khusus Premi

Kategori Premi mengambil detail dari endpoint grouped:

```text
GET /payroll/manual-adjustment/by-api-key?adjustment_type=PREMI&view=grouped&metadata_only=true
```

Aturan input Premi:

- Satu employee tetap diproses dalam satu tab/concurrent unit.
- Pembagian multi-tab memakai ownership per employee + estate. Seluruh detail/kategori milik employee yang sama dalam satu payload harus masuk ke tab yang sama, termasuk campuran `premi` dan `premi_tunjangan`.
- Runner melakukan preflight sebelum browser input: payload dengan detail key duplicate akan gagal, dan assignment yang memecah employee ke lebih dari satu tab juga akan gagal.
- Jenis premi dibedakan berdasarkan `adjustment_name`.
- `PREMI PRUNING`, `PREMI RAKING`, dan `PREMI TBS` adalah header/form yang berbeda.
- Jika `adjustment_name` berubah, runner harus klik **New** dan membuat input baru.
- Tombol **Add** beruntun hanya dipakai untuk detail sub-transaksi dalam premi yang sama.
- Field Description/DocDesc Plantware harus sama dengan `adjustment_name`.
- ADCode/TaskDesc tetap berasal dari `ad_code_desc` / `task_desc`, bukan dari Description.
- Jika ada `subblok`, data dianggap block-based.
- Jika ada `vehicle_code`, data dianggap vehicle-based.

### Retry Premi Setelah Ada Failed

Jangan langsung menjalankan ulang semua row Premi setelah ada status `Failed`. Sebelum retry, app harus mengecek `db_ptrj` lewat endpoint:

```text
POST /payroll/manual-adjustment/check-adtrans/by-api-key
filters = ["premi"]
```

Aturan retry aman:

- Biarkan checkbox **Input MISS/MISMATCH only** aktif untuk kategori Premi. Untuk Premi, checkbox ini dipakai sebagai retry-safe filter berbasis `check-adtrans`.
- Klik **Fetch / Refresh Data** lagi setelah run gagal. App akan menjumlahkan total payload Premi per employee, lalu membandingkannya dengan total `premi` di `db_ptrj`.
- Row dengan status `VERIFIED_MATCH` tidak boleh diinput ulang.
- Row dengan status `VERIFIED_NOT_FOUND` aman untuk retry karena total Premi employee tersebut masih `0` di `db_ptrj`.
- Row dengan status `VERIFIED_MISMATCH` adalah partial. App mencoba mencari subset detail payload yang jumlahnya sama dengan total `premi` di `db_ptrj`; jika subset itu unik, app hanya menampilkan/menginput detail sisanya.
- Jika `VERIFIED_MISMATCH` ambigu, misalnya ada lebih dari satu kombinasi detail yang bisa membentuk total yang sudah masuk, app menahan employee/filter tersebut untuk pengecekan manual supaya tidak dobel.
- Kalau verifikasi `db_ptrj` error, jangan run ulang massal. Perbaiki endpoint/koneksi dulu supaya filter retry-safe bisa bekerja.

Catatan penting: `check-adtrans` untuk filter `premi` adalah agregat per employee. Untuk kondisi partial/mismatch, app hanya auto-retry jika detail yang sudah masuk bisa diidentifikasi secara unik dari nominal detail payload.

Jika endpoint `sync-status/by-api-key` tersedia, app memakai endpoint itu lebih dulu untuk dry-run verifikasi per row manual adjustment. Row `PREMI` yang sudah verified full akan di-skip, row partial akan diproses per `adjustment_id`, dan setelah runner selesai app menjalankan dry-run lalu apply `sync:SYNC` hanya untuk row id yang sudah benar-benar verified. Jika endpoint belum tersedia di backend yang sedang jalan, app fallback ke pengecekan agregat `check-adtrans`.

Jika remarks sudah berisi `sync:SYNC`, row dianggap sudah sync dan tidak masuk retry/input ulang, walaupun segmen lain masih `match:MANUAL`. Contoh:

```text
PREMI PRUNING | AL3PM0601 - (AL) TUNJANGAN PREMI ((PM) PRUNING) | 493350 | sync:SYNC | match:MANUAL | SEED_IMPORT_AB1
```

### Status Realtime Di UI

Tabel preview dan summary memisahkan status browser input dari status verifikasi API:

- `Input Status`: status runner/browser untuk baris itu (`Pending`, `Running`, `Input Done`, `Skipped`, `Failed`).
- `API Sync`: status dari endpoint `sync-status/by-api-key` untuk manual adjustment id terkait (`QUEUED`, `CHECKING`, `SYNC`, `PARTIAL`, `NOT_FOUND`, `ERROR`, atau status awal dari remarks).
- `API Match`: detail keputusan endpoint, misalnya `UPDATED 300000/300000`, `ADTRANS_AMOUNT_PARTIAL 350000/500000`, atau pesan error endpoint.

Saat runner mengirim event `row.success`, app langsung menandai `Input Status = Input Done`, lalu mengantrekan `payroll_manual_adjustments.id` ke worker `sync-status`. Worker selalu menjalankan `dry_run=true` lebih dulu, kemudian `dry_run=false` hanya untuk id yang benar-benar verified. Semua detail row yang memakai `adjustment_id` yang sama ikut diperbarui di kolom `API Sync`/`API Match`.

Karena Plantware bisa baru menulis ADTRANS setelah tombol Save/Submit tab selesai, status realtime awal bisa sementara `NOT_FOUND` atau `PARTIAL`. Setelah runner selesai submit, app mengantrekan final verification untuk seluruh row sukses agar status akhir berubah menjadi `SYNC` hanya jika endpoint sudah memverifikasi row tersebut masuk di `db_ptrj`.

Jika satu row gagal karena data tidak valid, misalnya Premi detail tidak punya ADCode/TaskDesc, runner menandai row itu `Failed` dan lanjut ke row berikutnya. Jika error menunjukkan browser/page/context sudah tertutup, runner menghentikan tab itu saja dan menandai sisa row di tab tersebut sebagai failed tanpa mencoba menginputnya lagi. Ini mencegah loop gagal berulang dan mengurangi risiko dobel input.

Contoh mapping benar:

```text
adjustment_name = PREMI PRUNING
description     = PREMI PRUNING
ad_code_desc    = (AL) TUNJANGAN PREMI ((PM) PRUNING)

adjustment_name = PREMI RAKING
description     = PREMI RAKING
ad_code_desc    = (AL) TUNJANGAN PREMI ((PM) WEEDING - CIRCLE RAKING)

adjustment_name = PREMI TBS
description     = PREMI TBS
ad_code_desc    = (AL) TUNJANGAN PREMI ((PM) HARVESTING LABOUR - HARVESTING)
```

## Session Per Divisi

Session disimpan di:

```text
runner/data/sessions/session-<DIVISION>.json
```

Contoh:

```text
runner/data/sessions/session-P1B.json
runner/data/sessions/session-P2A.json
runner/data/sessions/session-AB1.json
```

Aturan:

- Input untuk divisi P2A hanya boleh memakai session P2A.
- UI akan blok Run Auto Key-In jika selected division belum punya session aktif.
- Session dianggap aktif jika umur file kurang dari 240 menit.
- Jika session expired, klik **Get Session** lagi untuk divisi tersebut.

## Verifikasi Setup

Test Python:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py -q
```

Build runner TypeScript:

```powershell
npm --prefix runner run build
```

Test runner TypeScript yang sering dipakai setelah mengubah logic input:

```powershell
node runner/dist/plantware/page-actions.test.js
node runner/dist/categories/registry-smoke.test.js
node runner/dist/orchestration/row-assignment.test.js
```

Jika file test di `runner/dist` belum ada, build runner dulu.

## Push Ke GitHub

Sebelum push:

1. Pastikan `.env`, session, artifact run, cache, dan file rahasia tidak ikut commit.
2. Jalankan verifikasi minimal:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests/test_api_models.py -q
npm --prefix runner run build
```

3. Cek perubahan:

```powershell
git status --short
git diff --stat
```

### Push Ke Repository Yang Sudah Ada Remote

Disarankan pakai branch kerja:

```powershell
git checkout -b feature/nama-perubahan
git add README.md app runner tests configs .env.example
git status --short
git commit -m "docs: update setup and github workflow"
git push -u origin feature/nama-perubahan
```

Setelah push, buat Pull Request di GitHub.

Jika memang ingin push branch aktif:

```powershell
git add README.md app runner tests configs .env.example
git commit -m "docs: update setup and github workflow"
git push origin HEAD
```

### Push Pertama Kali Ke Repository Baru

Jika belum ada remote:

```powershell
git remote -v
git remote add origin https://github.com/<owner>/<repo>.git
git branch -M main
git push -u origin main
```

Jika `git remote -v` sudah menampilkan `origin`, jangan tambahkan remote baru. Ganti URL hanya kalau memang salah:

```powershell
git remote set-url origin https://github.com/<owner>/<repo>.git
```

### File Yang Tidak Boleh Dipush

Jangan commit file ini:

- `.env`
- `configs/app.json`
- `runner/data/sessions/*.json`
- `data/runs/`
- `runner/node_modules/`
- `runner/dist/`
- `__pycache__/`
- `.pytest_cache/`

## Struktur Folder

```text
Auto Key In Refactor/
app/                         # App desktop PySide6
configs/                     # Kategori adjustment, divisions, config example
data/cache/                  # Payload contoh untuk dry-run/mock
data/runs/                   # Artifact run lokal, tidak perlu commit
runner/                      # Runner Playwright TypeScript
runner/src/                  # Source runner
runner/dist/                 # Build output, tidak commit
runner/data/sessions/        # Session login per divisi, tidak commit
tests/                       # Python tests
.env.example                 # Template env aman untuk commit
setup.ps1                    # Setup otomatis Windows PowerShell
setup.sh                     # Setup otomatis Git Bash
pyproject.toml               # Python project metadata
```

## Troubleshooting

### App Tidak Membaca API Key

Pastikan `.env` ada di root project dan berisi:

```env
AUTO_KEY_IN_API_KEY=...
```

Lalu restart app.

### Runner Gagal Karena `runner/dist/cli.js` Tidak Ada

Build ulang runner:

```powershell
npm --prefix runner run build
```

### Browser Playwright Tidak Muncul Atau Chromium Missing

Install browser:

```powershell
npx --prefix runner playwright install chromium
```

### Session Status Tidak Berubah Active

1. Pastikan login benar-benar selesai di browser.
2. Lihat log UI, harus ada path seperti `runner/data/sessions/session-AB1.json`.
3. Klik **Refresh Status**.
4. Jika masih gagal, build runner ulang:

```powershell
npm --prefix runner run build
```
