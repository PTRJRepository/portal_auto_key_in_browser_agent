# Auto Key In Refactor

Aplikasi desktop Python untuk monitor dan kontrol proses auto key-in PlantwareP3 dari sumber data Manual Adjustment API. UI dibuat dengan PySide6, sementara browser automation tetap memakai runner TypeScript Playwright agar logic login/session/multi-tab yang sudah teroptimasi bisa dipakai ulang.

## Struktur Folder

```text
Auto Key In Refactor/
├── app/                 # Aplikasi desktop PySide6
├── configs/             # Config contoh, division, kategori adjustment
├── data/
│   ├── cache/           # Payload contoh/cache lokal
│   └── runs/            # Payload, events, result per run
├── runner/              # TypeScript Playwright runner
├── tests/               # Unit test Python
├── _dev_utils/          # Script percobaan/non-produksi
├── Clean Runner/        # Folder existing Anda, tidak diubah
├── Data/                # Folder existing Anda, tidak diubah
└── pyproject.toml
```

## Prasyarat

- Python 3.11+ direkomendasikan.
- Node.js 20+ atau 22+.
- Akses jaringan ke PlantwareP3 `http://plantwarep3:8001` untuk runner nyata.
- Akses ke Manual Adjustment API, misalnya `http://localhost:8002`.

## Setup Pertama Kali

Jalankan dari folder project:

```bash
cd "D:/Gawean Rebinmas/Browser_Auto_key_in new/Auto Key In Refactor"
```

Install dependency Python:

```bash
python -m pip install -e ".[dev]"
```

Install dependency runner TypeScript:

```bash
cd runner
npm install
npm run build
cd ..
```

Jika Playwright browser belum terinstall:

```bash
cd runner
npx playwright install chromium
cd ..
```

## Catatan Penting: Kode Divisi

**Lihat dokumentasi lengkap:** [docs/DIVISION-CODES.md](docs/DIVISION-CODES.md)

> **PENTING:** Gunakan kode 3 karakter untuk filter API.
> - **Benar:** `P1B`, `P1A`, `P2B`
> - **Salah:** `PG1B`, `PG1A`, `PG2B`

## Konfigurasi

Copy config contoh:

```bash
cp configs/app.example.json configs/app.json
```

Edit `configs/app.json`:

```json
{
  "api_base_url": "http://localhost:8002",
  "api_key": "ISI_API_KEY_ANDA",
  "runner_command": "node runner/dist/cli.js",
  "default_period_month": 4,
  "default_period_year": 2026,
  "default_division_code": "P1B",
  "default_runner_mode": "multi_tab_shared_session",
  "default_max_tabs": 5,
  "headless": false
}
```

Alternatif API key bisa lewat environment variable:

```bash
export AUTO_KEY_IN_API_KEY="ISI_API_KEY_ANDA"
```

Di Windows PowerShell:

```powershell
$env:AUTO_KEY_IN_API_KEY="ISI_API_KEY_ANDA"
```

## Menjalankan Aplikasi Desktop

Dari folder project:

```bash
python -m app
```

Alur penggunaan aman:

1. Isi `API Base URL` dan `API Key`.
2. Pilih `Period Month`, `Period Year`, `Division`, dan filter lain bila perlu.
3. Pilih `Category`, misalnya `SPSI`, `Masa Kerja`, atau `Tunjangan Jabatan`.
4. Klik `Test Get Data`.
5. Cek preview table.
6. Pilih `Runner Mode`:
   - `dry_run`: paling aman, tidak membuka browser dan tidak input Plantware.
   - `mock`: test bridge/event tanpa browser.
   - `multi_tab_shared_session`: mode default nyata, fresh login lalu multi-tab shared session.
   - `session_reuse_single`: disiapkan untuk reuse session single mode.
   - `fresh_login_single`: disiapkan untuk single mode fresh login.
7. Set `Row Limit` kecil dulu, misalnya 1-5.
8. Klik `Run Auto Key-In`.
9. Cek log dan status row.

## Test Tanpa Browser

### Python unit tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests
```

Catatan: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` dipakai karena environment Python global bisa memuat plugin pytest yang tidak relevan.

### Build TypeScript runner

```bash
cd runner
npm run build
cd ..
```

### Dry-run CLI

```bash
node runner/dist/cli.js --payload data/cache/dry-run-payload.json
```

### Mock CLI

```bash
node runner/dist/cli.js --payload data/cache/mock-payload.json
```

## Output Run

Setiap run dari UI disimpan di:

```text
data/runs/<timestamp>-<category>-<runner_mode>/
├── payload.json     # data yang dikirim ke runner
├── events.ndjson    # event stream per baris
└── result.json      # hasil akhir runner
```

Gunakan folder ini untuk audit dan debugging.

## Mode Runner

### `dry_run`

- Tidak membuka browser.
- Tidak menyentuh Plantware.
- Menghasilkan rencana input per row.
- Cocok untuk validasi filter API, category mapping, payload, dan UI.

### `mock`

- Tidak membuka browser.
- Simulasi event sukses per row.
- Cocok untuk test bridge Python ↔ TypeScript.

### `multi_tab_shared_session`

- Membuka browser Playwright.
- Fresh login dulu.
- Menyimpan session state.
- Membuka beberapa tab dalam context/session yang sama.
- Mendistribusikan row ke tab.
- Submit dilakukan per tab.

## Category Mapping Awal

File: `configs/adjustment-categories.json`

Kategori awal:

- `spsi` → adcode `spsi`, deskripsi: **POTONGAN SPSI**
- `masa_kerja` → adcode `masa kerja`, deskripsi: **TUNJANGAN MASA KERJA**
- `tunjangan_jabatan` → adcode `tunjangan jabatan`, deskripsi: **TUNJANGAN JABATAN**
- `premi`
- `potongan_upah_kotor`
- `premi_tunjangan`

Mapping bisa diperluas tanpa mengubah UI utama.

### Aturan Deskripsi (DocDesc) di Plantware

Lihat dokumentasi lengkap: [docs/DESCRIPTION-RULES.md](docs/DESCRIPTION-RULES.md)

> **PENTING:** Deskripsi yang diinput ke field DocDesc Plantware **bukan** langsung dari adjustment_name.
>
> **AUTO_BUFFER categories:**
> | Category | Adjustment Name | Deskripsi di Plantware |
> |----------|----------------|----------------------|
> | SPSI | AUTO SPSI | **POTONGAN SPSI** |
> | Masa Kerja | AUTO MASA KERJA | **TUNJANGAN MASA KERJA** |
> | Tunjangan Jabatan | AUTO TUNJANGAN JABATAN | **TUNJANGAN JABATAN** |
>
> **Non-AUTO_BUFFER:** ikuti adjustment_name apa adanya (strip prefix "AUTO " jika ada).

## Catatan Safety

- Mulai dari `dry_run` sebelum runner nyata.
- Untuk runner nyata, gunakan `Row Limit` kecil dulu.
- Jangan commit `configs/app.json` jika berisi API key.
- Jangan commit session/cookie file di `data/sessions`.
- Missing-row detection saat ini masih fondasi berbasis teks halaman Plantware aktif; setelah test nyata, sebaiknya diperkuat dengan selector tabel yang lebih spesifik.

## Troubleshooting

### PySide6 belum terinstall

```bash
python -m pip install PySide6 requests pytest
```

### Runner belum build

```bash
cd runner
npm install
npm run build
cd ..
```

### API kosong

Cek filter:

- `period_month`
- `period_year`
- `division_code`
- `adjustment_type`
- `adjustment_name`

Coba kosongkan `gang_code` dan `emp_code` dulu.

### Runner path salah

Pastikan `configs/app.json` berisi:

```json
"runner_command": "node runner/dist/cli.js"
```

### Pytest error karena plugin global

Gunakan:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests
```
