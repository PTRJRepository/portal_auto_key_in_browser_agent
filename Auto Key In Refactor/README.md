# Auto Key In Refactor

Aplikasi desktop PySide6 untuk fetch data Manual Adjustment API, monitoring proses Auto Key-In PlantwareP3, menyimpan session login per lokasi/divisi, menjalankan runner Playwright TypeScript, dan verifikasi hasil ke `db_ptrj`.

## Prasyarat

Install dulu di komputer:

- Python 3.11+ direkomendasikan.
- Node.js 20+ atau 22+.
- Git.
- Akses jaringan ke PlantwareP3, default: `http://plantwarep3:8001`.
- Akses ke Manual Adjustment API, default: `http://localhost:8002`.

## Setup setelah pull/clone dari GitHub

Masuk ke folder project:

```powershell
cd "D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor"
```

Atau kalau baru clone:

```powershell
git clone <URL_REPOSITORY_GITHUB> "D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor"
cd "D:\Gawean Rebinmas\Browser_Auto_key_in new\Auto Key In Refactor"
```

Jalankan setup otomatis Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Setup ini akan:

1. Membuat `.env` dari `.env.example` kalau belum ada.
2. Install package Python dengan `pip install -e .[dev]`.
3. Install package runner Node.js.
4. Build runner TypeScript ke `runner/dist`.
5. Install Chromium untuk Playwright.

Jika memakai Git Bash, bisa pakai:

```bash
bash setup.sh
```

## Isi file `.env`

Setelah setup, buka `.env` dan isi nilai rahasia/login sesuai environment lokal.

Contoh isi:

```env
AUTO_KEY_IN_API_BASE_URL=http://localhost:8002
AUTO_KEY_IN_API_KEY=isi_api_key_manual_adjustment
AUTO_KEY_IN_RUNNER_COMMAND=node runner/dist/cli.js

AUTO_KEY_IN_DEFAULT_PERIOD_MONTH=4
AUTO_KEY_IN_DEFAULT_PERIOD_YEAR=2026
AUTO_KEY_IN_DEFAULT_DIVISION_CODE=P1B
AUTO_KEY_IN_DEFAULT_RUNNER_MODE=multi_tab_shared_session
AUTO_KEY_IN_DEFAULT_MAX_TABS=5
AUTO_KEY_IN_HEADLESS=false

PLANTWARE_BASE_URL=http://plantwarep3:8001
PLANTWARE_USERNAME=isi_username_plantware
PLANTWARE_PASSWORD=isi_password_plantware
PLANTWARE_DIVISION=P1B
```

Catatan:

- Jangan commit `.env`.
- `.env` sudah di-ignore oleh `.gitignore`.
- `configs/app.json` juga di-ignore karena bisa berisi API key lokal.
- Kalau `.env` sudah benar, tidak perlu edit `configs/app.json`.

## Menjalankan aplikasi

Dari root project:

```powershell
python -m app
```

## Alur penggunaan yang disarankan

1. Buka app dengan `python -m app`.
2. Tab **Config**:
   - Pastikan API Base URL dan API Key terisi dari `.env`.
   - Pilih Period Month, Period Year, Division, Category.
3. Bagian **Session Status**:
   - Klik **Get Session** di baris lokasi tertentu untuk login satu lokasi.
   - Klik **Get All Sessions** untuk membuka browser sebanyak jumlah lokasi/divisi; setiap browser menangani 1 session lokasi.
   - Status harus berubah menjadi `Active` setelah session tersimpan.
4. Tab **Process**:
   - Klik **Fetch / Refresh Data**.
   - Default checkbox `Input MISS/MISMATCH only` aktif, jadi hanya data `sync:MISS` / `match:MISMATCH` yang diproses.
   - Set Row Limit kecil dulu, misalnya 1-5.
   - Klik **Run Auto Key-In**.
5. Tab **Summary** akan menampilkan hasil run.
6. Tab **Verify db_ptrj** dipakai untuk cek data yang sudah masuk ke endpoint `check-adtrans`.

## Session per lokasi/divisi

Session disimpan per divisi di:

```text
runner/data/sessions/session-<DIVISION>.json
```

Contoh:

```text
runner/data/sessions/session-P1B.json
runner/data/sessions/session-P2A.json
runner/data/sessions/session-AB1.json
```

Aturan penting:

- Input untuk divisi P2A hanya boleh memakai session P2A.
- UI akan blok Run Auto Key-In jika selected division belum punya session aktif.
- Session dianggap aktif jika umur file kurang dari 240 menit.
- Kalau session expired, klik **Get Session** lagi untuk divisi tersebut.

## Verifikasi setup

Jalankan test Python:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
python -m pytest tests -v
```

Build runner TypeScript:

```powershell
npm --prefix runner run build
```

Dry-run runner tanpa browser:

```powershell
node runner/dist/cli.js --payload data/cache/dry-run-payload.json
```

Mock runner tanpa browser:

```powershell
node runner/dist/cli.js --payload data/cache/mock-payload.json
```

## Struktur folder penting

```text
Auto Key In Refactor/
├── app/                         # App desktop PySide6
├── configs/                     # Kategori adjustment, divisions, config example
├── data/cache/                  # Payload contoh untuk dry-run/mock
├── data/runs/                   # Artifact run lokal, tidak perlu commit
├── runner/                      # Runner Playwright TypeScript
│   ├── src/                     # Source runner
│   ├── dist/                    # Build output, hasil npm run build, tidak commit
│   └── data/sessions/           # Session login per divisi, tidak commit
├── tests/                       # Python tests
├── .env.example                 # Template env aman untuk commit
├── setup.ps1                    # Setup otomatis Windows PowerShell
├── setup.sh                     # Setup otomatis Git Bash
└── pyproject.toml               # Python project metadata
```

## Troubleshooting

### App tidak membaca API key

Pastikan `.env` ada di root project dan berisi:

```env
AUTO_KEY_IN_API_KEY=...
```

Lalu restart app.

### Runner gagal karena `runner/dist/cli.js` tidak ada

Build ulang runner:

```powershell
npm --prefix runner run build
```

### Browser Playwright tidak muncul / Chromium missing

Install browser:

```powershell
npx --prefix runner playwright install chromium
```

### Session Status tidak berubah Active

1. Pastikan login benar-benar selesai di browser.
2. Lihat log UI, harus ada path seperti:

```text
runner/data/sessions/session-P1B.json
```

3. Klik **Refresh Status**.
4. Kalau masih tidak ada, build runner ulang:

```powershell
npm --prefix runner run build
```

### Jangan commit file lokal/rahasia

File berikut harus tetap lokal:

- `.env`
- `configs/app.json`
- `runner/data/sessions/*.json`
- `data/runs/`
- `runner/node_modules/`
- `runner/dist/`
