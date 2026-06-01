# Plantware Auto Key-In Agent Handoff

Dokumen ini adalah ringkasan operasional untuk agent lain yang perlu memahami aplikasi Plantware Auto Key-In tanpa membaca seluruh repo dari awal.

## Gambaran Singkat

Aplikasi ini adalah desktop controller PySide6 untuk mengambil data Manual Adjustment API, mengubahnya menjadi payload runner, lalu menjalankan Playwright TypeScript untuk input ke PlantwareP3.

## MCP Knowledge

Knowledge compact untuk handoff ini sudah disimpan ke MCP server `mcp-otak-digital-atta`.

- `project_id`: `browser-auto-key-in`
- `topic`: `Plantware Auto Key-In Consolidated Agent Handoff 2026-05-08 Compact`
- `doc_id`: `e8f2ae28-04f1-41a7-aaf8-fd90f59850f0`
- Tags utama: `plantware`, `auto-key-in`, `architecture`, `workflow`, `runner`, `playwright`, `pyside6`, `manual-adjustment`, `mcp-handoff`, `millware-structure`

Agent baru harus memanggil `get_agent_bootstrap`, lalu `query_knowledge` / `search_by_tags` pada `project_id=browser-auto-key-in` sebelum mengubah logic Plantware automation. Dokumen lokal ini adalah versi detail; MCP menyimpan versi compact untuk discovery lintas agent.

Strukturnya dibuat mirip pola Millware:

- Python UI/orchestrator ada di `app/`.
- Runner browser TypeScript ada di `runner/src/`.
- Config kategori/divisi ada di `configs/`.
- Bukti run tersimpan di `data/runs/<timestamp>-<category>-<mode>/`.
- Session login Plantware tersimpan per divisi di `runner/data/sessions/session-<DIVISION>.json`.

## Entry Point Penting

- `python -m app` menjalankan UI.
- `app/main.py` load config, categories, divisions, lalu membuat `MainWindow`.
- `app/ui/main_window.py` memegang flow tombol UI: fetch data, get session, run auto key-in, event runner, summary, duplicate cleanup, reset DocID, dan sync-status.
- `app/core/api_client.py` memanggil Manual Adjustment API.
- `app/core/models.py` normalisasi record API menjadi `ManualAdjustmentRecord` dan payload runner.
- `app/core/runner_bridge.py` menulis payload temp, menjalankan `node runner/dist/cli.js --payload <json>`, lalu membaca event JSON per baris dari stdout.
- `runner/src/cli.ts` memilih runner berdasarkan `operation` dan `runner_mode`.
- `runner/src/orchestration/multi-tab-runner.ts` adalah jalur real input multi tab.
- `runner/src/plantware/page-actions.ts` berisi detail aksi browser: buka form, pilih employee, pilih ADCode, isi detail, Add, Save.

## Alur Data End-To-End

1. User pilih period, division, category, optional gang/employee/adjustment name di tab Config.
2. User klik `Fetch / Refresh Data`.
3. `MainWindow.fetch_records()` membuat `ManualAdjustmentQuery`.
4. `FetchWorker.run()` memanggil `ManualAdjustmentApiClient.get_adjustments()`.
5. Untuk `PREMI`, query otomatis dibuat grouped: `adjustment_type=PREMI&view=grouped&metadata_only=true`.
6. API response dinormalisasi oleh `normalize_record()` di `app/core/models.py`.
7. Metadata detail seperti `metadata_json.items[]`, `detail_items[]`, `blok_items[]`, dan `vehicle_items[]` dipecah menjadi record detail individual.
8. UI filter record berdasarkan category, prefix divisi employee, row limit, dan opsi `Input MISS only`.
9. User klik `Run Auto Key-In`.
10. `MainWindow.build_payload()` membuat `RunPayload` berisi records final.
11. `RunArtifactStore.create()` menyimpan `payload.json` ke `data/runs/...`.
12. `RunnerBridge.run()` menjalankan runner Node dengan payload temp.
13. `runner/src/cli.ts` memanggil `runMultiTabSharedSession()` untuk input real.
14. Runner membuka session Plantware, membagi row per tab, menginput setiap row, lalu `submitTab()` melakukan Save.
15. Runner mengirim event `row.started`, `row.success`, `row.failed`, `tab.submit.completed`, `run.completed`, dan `result` ke stdout.
16. Python UI membaca event, mengupdate tabel realtime, menulis `events.ndjson`, lalu menulis `result.json`.
17. Setelah row sukses, UI menjalankan `sync-status` dry-run/apply untuk menandai manual adjustment yang benar-benar sudah muncul di `db_ptrj`.

## Session Plantware

Session login adalah syarat untuk run real kecuali mode `dry_run`, `mock`, atau `fresh_login_single`.

File session:

```text
runner/data/sessions/session-<DIVISION>.json
```

Aturan session:

- `Get Session` membuat login baru dan menyimpan storage state.
- `test_session` mengecek apakah session masih valid.
- Session dianggap aktif jika `division` di file cocok dan umur file kurang dari 240 menit.
- `session_division_code` di payload dipakai untuk memilih file session, karena kode UI division dan kode session bisa berbeda melalui `configs/divisions.json`.
- `BrowserSession.tryLoadSession()` menolak session yang expired, salah divisi, tidak punya cookies, login page, atau session expired page.

## Model Data Inti

`ManualAdjustmentRecord` adalah bentuk data yang dikirim dari Python ke runner. Field penting:

- `emp_code`, `emp_name`, `nik`: identitas employee. Runner menolak memakai NIK sebagai autocomplete employee jika tidak ada `emp_name` valid.
- `division_code` / `estate`: top-level Plantware `Charge To`.
- `divisioncode`: block division code untuk detail block-based, contoh `G 1`.
- `gang_code`: dipakai untuk fallback `divisioncode` dan beberapa kategori.
- `adjustment_type`, `adjustment_name`: tipe dan nama adjustment dari API.
- `category_key`: hasil deteksi category seperti `spsi`, `premi`, `potongan_upah_kotor`.
- `amount` / `jumlah`: nominal detail yang diinput.
- `ad_code`, `ad_code_desc`, `task_code`, `task_desc`: sumber ADCode/TaskDesc untuk autocomplete Plantware.
- `detail_type`: `blok`, `kendaraan`, atau kosong.
- `subblok` / `subblok_raw`: Field No Code/SubBlk untuk block-based monthly allowance.
- `vehicle_code`, `vehicle_expense_code`, `expense_code`: field kendaraan dan expense.
- `transaction_index`, `adjustment_id`, `detail_key`: identitas detail agar retry, duplicate guard, dan event UI tidak tertukar.

## Normalisasi API

Normalisasi utama ada di `app/core/models.py`.

Aturan yang perlu dijaga:

- `metadata_detail_items()` membaca detail dari `detail_items`, `metadata_json`, `metadata.items`, `blok_items`, `block_items`, `vehicle_items`, `kendaraan_items`, `expense`, dan `exp`.
- Alias `subblok`, `fieldcode`, `field_code`, `fieldNoCode` semuanya dianggap sub block/field code.
- Alias `vehicle_code`, `nomor_kendaraan`, `NOMOR_KENDARAAN`, `vehicle_number` semuanya dianggap vehicle code.
- Jika detail punya subblok, `detail_type` menjadi `blok`.
- Jika detail punya vehicle code, `detail_type` menjadi `kendaraan`.
- Jika `vehicle_expense_code` kosong pada row kendaraan, fallback ke `expense_code`.
- `amount` dan `jumlah` selalu dibuat positif dengan `abs(float(...))`.
- `adjustment_id` fallback dari `id` agar sync-status bisa memakai id manual adjustment.

Untuk grouped premium, `ManualAdjustmentApiClient._normalize_grouped_premium_records()` membaca struktur:

```text
division -> gangs[] -> employees[] -> premium_transactions[]
```

Setiap `premium_transactions[]` adalah satu detail input Plantware. Jangan memakai total aggregate `premiums[].amount` sebagai detail input.

## Kategori Dan DocDesc

Kategori Python:

- Config: `configs/adjustment-categories.json`
- Loader: `app/core/category_registry.py`
- Filter UI: `filter_by_category()` di `app/core/run_service.py`

Kategori runner:

- Strategy: `runner/src/categories/registry.ts`
- Resolver: `resolveCategory(record, fallbackKey)`

Aturan DocDesc Plantware:

- `spsi`: `POTONGAN SPSI`
- `masa_kerja`: `TUNJANGAN MASA KERJA`
- `tunjangan_jabatan`: `TUNJANGAN JABATAN`
- `pph21`: `(DE) POTONGAN PPH21`
- `premi`, `potongan_upah_kotor`, `potongan_upah_bersih`: pakai `adjustment_name`, dengan prefix `AUTO ` dibuang.

ADCode berbeda dari DocDesc:

- AUTO_BUFFER memakai keyword tetap seperti `spsi`, `masa kerja`, `tunjangan jabatan`, atau `(DE) POTONGAN PPH21`.
- PREMI/manual memakai `ad_code_desc`, `task_desc`, `description`, lalu `ad_code`, lalu remarks.
- PREMI detail yang punya block/vehicle data tidak boleh fallback ke generic `premi`; runner harus fail jelas jika ADCode hilang.

## Flow Input Browser

Jalur utama ada di `runner/src/orchestration/multi-tab-runner.ts`.

Preflight sebelum browser input:

- `duplicateInputRowKeys()` menolak payload dengan detail key duplicate.
- `assignRowsToTabs()` membagi row per employee group.
- `findCrossTabEmployeeSplits()` menolak employee yang tersebar ke lebih dari satu tab.

Grouping tab:

- Unit kerja konkuren adalah `employeeAutocompleteValue(record) + estate/division_code`.
- Semua row milik employee + estate yang sama harus ada di tab yang sama.
- Untuk premium detail berulang, group sempitnya adalah employee + estate + adjustment_name + ADCode.

Urutan input per row di `fillAdjustmentRow()`:

1. Buka New row jika bukan first row dan bukan kelanjutan detail premium.
2. Pilih employee melalui `#MainContent_ddlEmployee + input.ui-autocomplete-input`.
3. Set `#MainContent_ddlChargeTo` ke division/session yang sesuai.
4. Pilih ADCode/TaskCode melalui `#MainContent_ddlTaskCode + input.ui-autocomplete-input`.
5. Tunggu postback ADCode selesai.
6. Pastikan DocDesc di `#MainContent_txtDocDesc`.
7. Deteksi layout detail monthly allowance dari DOM.
8. Jika block-based, isi Division Code, Field No Code/SubBlk, lalu Expense Code.
9. Jika vehicle-based, isi Vehicle Code lalu Vehicle Expense Code.
10. Jika amount-only, langsung isi Amount.
11. Isi `#MainContent_txtAmount`.
12. Jika layout generic dan butuh expense, pilih expense fallback.
13. Klik `#MainContent_btnAdd`.
14. `waitForAddCompleted()` memastikan tidak ada validation error dan Add terlihat berhasil.

Setelah semua row tab selesai:

- `submitTab()` klik `#MainContent_btnSave` / Save selector lain.
- Save dilakukan per tab setelah semua Add di tab itu selesai.

## Block-Based Monthly Allowance

Field mapping:

- Plantware Division Code: `divisioncode`, fallback dari 2 karakter pertama `gang_code` dengan spasi.
- Plantware Field No Code/SubBlk: `subblok`, `subblok_raw`, `fieldcode`, atau `field_code`.
- Plantware Expense Code: `expense_code`, fallback `L`.

Selector:

```text
#MainContent_MultiDimAcc_ddlBlock + input.ui-autocomplete-input
#MainContent_MultiDimAcc_ddlSubBlk + input.ui-autocomplete-input
#MainContent_MultiDimAcc_ddlExpCode + input.ui-autocomplete-input
```

Subblok dinormalisasi di runner:

- Hapus karakter non-alfanumerik.
- Jika mulai angka, prefix `PM`.
- Jika mulai `P` bukan `PM`, ubah menjadi `PM...`.
- Tambahkan suffix division compact jika belum ada.

## Vehicle-Based Monthly Allowance

Field mapping:

- Plantware Vehicle Code: `vehicle_code` atau metadata `nomor_kendaraan`.
- Plantware Vehicle Expense Code: `vehicle_expense_code`, fallback `expense_code`.
- Jika expense `HELPER` tidak tersedia, runner punya fallback eksplisit ke `OTHER EXPENSES`.

Selector:

```text
#MainContent_MultiDimAcc_ddlVehCode + input.ui-autocomplete-input
#MainContent_MultiDimAcc_ddlVehExpCode + input.ui-autocomplete-input
```

## Autocomplete Rules

Runner mengutamakan hidden select yang berpasangan dengan autocomplete input:

- Coba match langsung pada `<select>` value/text.
- Jika gagal, type ke input dan pilih item menu yang match.
- Untuk `subblok` dan `vehicle`, slow typing fallback boleh memilih item jika hanya ada satu option tersisa.
- Untuk employee dan ADCode, fallback random/any tidak boleh dipakai.
- Untuk field selain employee dan ADCode, `selectAnyAvailableAutocompleteField()` bisa menjadi fallback terakhir karena beberapa form punya optional field yang opsi pastinya tidak selalu lengkap.

## Skip, Retry, Dan Sync-Status

Ada dua lapis proteksi agar tidak double input:

1. Saat fetch:
   - UI bisa cek `sync-status` atau `check-adtrans`.
   - `Input MISS only` hanya menampilkan row yang masih missing.
   - Untuk PREMI partial, UI hanya auto-retry detail sisa jika subset nominal yang sudah masuk bisa diidentifikasi unik.
   - Jika partial ambigu, group ditahan untuk pengecekan manual.

2. Saat runner:
   - Jika `only_missing_rows` aktif, `rowAlreadyExists()` scan row yang sudah ada di halaman Plantware dan skip jika match.

Setelah row sukses:

- UI queue id manual adjustment ke `SyncStatusWorker`.
- Worker selalu `dry_run=true` dulu.
- `dry_run=false` hanya dipanggil untuk id yang verified.
- Endpoint sync-status hanya untuk `PREMI`, `POTONGAN_KOTOR`, dan `POTONGAN_BERSIH`, bukan `AUTO_BUFFER`.

## Event Dan Artifact

Run artifact:

```text
data/runs/<timestamp>-<category>-<runner_mode>/
  payload.json
  events.ndjson
  result.json
```

Event penting dari runner:

- `run.started`
- `session.ready`
- `tab.assigned`
- `tab.open.started`
- `tab.form.ready`
- `row.started`
- `row.success`
- `row.skipped`
- `row.failed`
- `tab.progress`
- `tab.completed`
- `tab.submit.started`
- `tab.submit.completed`
- `tab.submit.failed`
- `run.completed`
- `run.failed`
- `result`

Python UI memakai event ini untuk:

- Update Process table dan Summary.
- Menulis event ke artifact.
- Queue sync-status saat `row.success`.
- Menampilkan progress per tab seperti agent worker.

## Mode Runner

`runner_mode`:

- `multi_tab_shared_session`: run real multi-tab dengan session tersimpan.
- `session_reuse_single`: run real satu tab dengan session tersimpan.
- `fresh_login_single`: login fresh lalu input satu tab.
- `get_session`: login fresh dan simpan session, tidak input row.
- `test_session`: cek session, tidak input row.
- `dry_run`: validasi payload tanpa browser input real.
- `mock`: simulasi.

`operation`:

- `input`: default auto key-in.
- `delete_duplicates`: delete duplicate/reset DocID via browser.
- `debug_duplicate_scan`: scan debug duplicate.

## Titik Risiko Yang Harus Dipahami Agent Baru

- Jangan campur data antar divisi. UI punya prefix guard employee code berdasarkan divisi.
- Jangan retry massal PREMI setelah gagal tanpa `Input MISS only` dan verifikasi `db_ptrj`.
- Jangan input aggregate premium total jika metadata punya detail. Input per detail transaction.
- Jangan memetakan autocomplete berdasarkan index global. Selalu pakai hidden select dan adjacent input.
- Jangan memakai NIK sebagai employee autocomplete.
- Jangan ubah DocDesc rules tanpa cek `docs/DESCRIPTION-RULES.md`.
- Jangan ubah monthly allowance DOM logic tanpa cek `docs/MONTHLY-ALLOWANCE-DOM-PATTERNS.md`.
- Jangan menghapus atau recreate session lintas divisi tanpa memastikan `session_division_code`.
- Jangan anggap `row.success` berarti sudah masuk `db_ptrj`; status final harus lewat sync-status setelah Save/Submit.

## Lokasi Rujukan Cepat

- Arsitektur umum: `README.md`, `CLAUDE.md`
- DocDesc: `docs/DESCRIPTION-RULES.md`
- Monthly allowance DOM: `docs/MONTHLY-ALLOWANCE-DOM-PATTERNS.md`
- Divisi dan alias: `configs/divisions.json`, `docs/DIVISION-CODES.md`
- Kategori: `configs/adjustment-categories.json`, `runner/src/categories/registry.ts`
- Normalisasi API: `app/core/models.py`, `app/core/api_client.py`
- UI flow: `app/ui/main_window.py`
- Runner flow: `runner/src/orchestration/multi-tab-runner.ts`
- Browser actions: `runner/src/plantware/page-actions.ts`
- Session: `runner/src/session/browser-session.ts`
