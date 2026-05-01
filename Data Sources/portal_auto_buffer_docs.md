# Manual Adjustment API

Dokumentasi API untuk mengelola manual adjustment (koreksi) daftar upah melalui API key bypass.

---

## Update Penting Untuk Browser Automation

Perubahan terbaru menambahkan endpoint khusus untuk agent/browser automation yang sudah menginput premi, koreksi, atau potongan ke Plantware lalu ingin menandai data manual adjustment sebagai sudah sync.

Endpoint yang dipakai:

```text
POST /payroll/manual-adjustment/sync-status/by-api-key
```

Gunakan endpoint ini setelah input Plantware selesai. Endpoint akan:

- membaca row manual adjustment dari `extend_db_ptrj.dbo.payroll_manual_adjustments`;
- mengecek transaksi yang sudah masuk di `db_ptrj` (`PR_ADTRANS` dan `PR_ADTRANS_ARC`);
- mengubah hanya segmen `sync:` di `remarks`, misalnya `sync:MANUAL` menjadi `sync:SYNC`;
- tidak mengubah `amount`, `metadata_json`, `adjustment_name`, TaskDesc/ADCode, atau segmen `match:`;
- melewati row yang belum ada di ADTRANS atau baru masuk sebagian detailnya.

Gunakan `dry_run=true` dulu untuk verifikasi. Jika hasilnya sesuai, panggil ulang dengan `dry_run=false`.

Catatan eksekusi awal AB1: pada 2026-05-01 sudah dijalankan untuk `period_month=4`, `period_year=2026`, `division_code=AB1`, `adjustment_type=PREMI`, `only_if_adtrans_exists=true`. Hasil apply: 27 row diubah ke `sync:SYNC`, 102 row belum ditemukan di ADTRANS, dan 2 row dilewati karena `ADTRANS_AMOUNT_PARTIAL`.

---

## Daftar Division (Divisi)

Division dikelompokkan menjadi **Real Divisions** dan **Virtual Divisions**.

### Real Divisions

| Code | Nama | Aliases | Gang Prefix | Lokasi |
|------|------|---------|-------------|--------|
| `PG1A` | Plasma 1 Afdeling | P1A, PLASMA1A, Plasma 1A | A | Afdeling Plasma 1 |
| `PG1B` | Plasma 1 Blok | P1B, PLASMA1B, Plasma 1B | B | Blok Plasma 1 |
| `PG2A` | Plasma 2 Afdeling | P2A, PLASMA2A, Plasma 2A | C | Afdeling Plasma 2 |
| `PG2B` | Plasma 2 Blok | P2B, PLASMA2B, Plasma 2B | D | Blok Plasma 2 |
| `PGE` | Plasma Energi | PGE | PGE | Energi |
| `AB1` | Afdeling 1 | ARB1, AFDELING1, Air Ruak 1 | G | Air Ruak 1 |
| `AB2` | Afdeling 2 | ARB2, AFDELING2, Air Ruak 2 | H | Air Ruak 2 |
| `ARA` | Area | Area | F | Area |
| `ARC` | Air Ruak Central | AREC, Air Ruak Central | J | Air Ruak Central |
| `DME` | Dempo | Dempo | E | Dempo |
| `IJL` | Ijuk | L | L | Ijuk |

### Virtual Divisions

| Code | Nama | Source | Gang Pattern | Description |
|------|------|--------|--------------|-------------|
| `INF` | Infrastruktur | PG1A | `/^IN.*/i` | Gang mulai dengan IN |
| `NRS` | Nursery | PG1B | `/^B2N$/i` | Gang B2N |
| `WKS_AR` | Workshop Air Ruak | AB2 | `/^HMC$/i` | Gang HMC |
| `WKS_PG` | Workshop Parit Gunung | PG1A | `/^AMC$/i` | Gang AMC |
| `WORKSHOP` | Workshop All | - | `/^(HMC\|AMC)$/i` | AMC dan HMC |
| `MILL` | Palm Oil Mill | - | `/^M\d*$/i` | Gang mulai dengan M |

## Get adjustment untuk Employee yang MISSING

Ketika employee missing adjustment (tidak ada di daftar upah), gunakan endpoint ini untuk mendapatkan/callback adjustment yang sudah ada:

```bash
# Get adjustment via API (jika auth mode internal)
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&emp_code=B0745" \
  -H "X-API-Key: ${API_KEY}"

# Get adjustment via API (jika auth mode external/proxy)
curl -s "http://localhost:8002/backend/upah/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&emp_code=B0745" \
  -H "X-API-Key: ${API_KEY}"

# Get adjustment via SQL Gateway (direct database query - WORKAROUND)
curl -X POST "http://10.0.0.110:8001/v1/query" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${DB_API_KEY}" \
  -d '{
    "sql": "SELECT emp_code, gang_code, division_code, adjustment_name, adjustment_type, amount FROM payroll_manual_adjustments WHERE period_month = 4 AND period_year = 2026 AND emp_code = '\''B0745'\''",
    "server": "SERVER_PROFILE_1",
    "database": "extend_db_ptrj"
  }'
```

**Hasil Query SQL (emp_code=B0745):**

```json
{
  "success": true,
  "db": "extend_db_ptrj",
  "server": "SERVER_PROFILE_1",
  "execution_ms": 7.24,
  "data": {
    "recordset": [
      {"emp_code": "B0745", "gang_code": "B2N", "division_code": "NRS", "adjustment_name": "PREMI COBA", "adjustment_type": "PREMI", "amount": 50},
      {"emp_code": "B0745", "gang_code": "B2N", "division_code": "NRS", "adjustment_name": "KOREKSI KOREKKSI PANEN", "adjustment_type": "POTONGAN_KOTOR", "amount": 0},
      {"emp_code": "B0745", "gang_code": "B2N", "division_code": "NRS", "adjustment_name": "AUTO TUNJANGAN JABATAN", "adjustment_type": "AUTO_BUFFER", "amount": 0},
      {"emp_code": "B0745", "gang_code": "B2N", "division_code": "NRS", "adjustment_name": "AUTO MASA KERJA", "adjustment_type": "AUTO_BUFFER", "amount": 2500},
      {"emp_code": "B0745", "gang_code": "B2N", "division_code": "NRS", "adjustment_name": "AUTO SPSI", "adjustment_type": "AUTO_BUFFER", "amount": 4000}
    ],
    "rowsAffected": 5
  }
}
```

**Query Parameters untuk Get Employee Adjustments (via API):**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period_month` | string | ✅ | Bulan (1-12) |
| `period_year` | string | ✅ | Tahun (e.g. "2026") |
| `emp_code` | string | ❌ | Employee code spesifik |
| `gang_code` | string | ❌ | Filter per gang |
| `division_code` | string | ❌ | Filter per division |
| `adjustment_type` | string | ❌ | Filter per type: `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, `PENDAPATAN_LAINNYA`, `AUTO_BUFFER`, `MANUAL` (alias = semua kecuali AUTO_BUFFER). Mendukung comma-separated, e.g. `PREMI,POTONGAN_KOTOR` |
| `adjustment_name` | string | ❌ | Filter per nama (partial match) |
| `view` | string | ❌ | Format response. Default `flat`. Pakai `grouped` untuk response siap auto input: division -> gang -> employee -> premiums/adjustments. |
| `metadata_only` | string | ❌ | Jika `true`, hanya ambil row yang memiliki `metadata_json`. Ini disarankan untuk data premi detail terbaru; row tanpa metadata adalah format lama. |

**`adjustment_type` Values:**

| Value | Description |
|-------|-------------|
| `PREMI` | Tunjangan bonus/premi tambahan |
| `POTONGAN_KOTOR` | Potongan dari upah kotor (koreksi) |
| `POTONGAN_BERSIH` | Potongan dari upah bersih |
| `PENDAPATAN_LAINNYA` | Pendapatan lain (THR, bonus, dll) |
| `AUTO_BUFFER` | Auto-generated Jabatan/Masa Kerja/SPSI (dari seeder) |
| `MANUAL` | Alias untuk `PREMI,POTONGAN_KOTOR,POTONGAN_BERSIH,PENDAPATAN_LAINNYA` (semua kecuali AUTO_BUFFER) |

**Comma-separated example:** `adjustment_type=PREMI,POTONGAN_KOTOR` → filter PREMI dan POTONGAN_KOTOR sekaligus.

**SQL Query untuk Get Adjustments by Employee:**

```sql
-- Get semua adjustment untuk 1 employee
SELECT emp_code, gang_code, division_code, adjustment_name, adjustment_type, amount
FROM payroll_manual_adjustments
WHERE period_month = {month}
  AND period_year = {year}
  AND emp_code = '{emp_code}'

-- Get hanya AUTO_BUFFER adjustments
SELECT emp_code, gang_code, division_code, adjustment_name, adjustment_type, amount
FROM payroll_manual_adjustments
WHERE period_month = {month}
  AND period_year = {year}
  AND emp_code = '{emp_code}'
  AND adjustment_type = 'AUTO_BUFFER'

-- Get hanya MANUAL adjustments (semua kecuali AUTO_BUFFER)
SELECT emp_code, gang_code, division_code, adjustment_name, adjustment_type, amount
FROM payroll_manual_adjustments
WHERE period_month = {month}
  AND period_year = {year}
  AND emp_code = '{emp_code}'
  AND adjustment_type IN ('PREMI', 'POTONGAN_KOTOR', 'POTONGAN_BERSIH', 'PENDAPATAN_LAINNYA')

-- Get adjustment berdasarkan division
SELECT emp_code, gang_code, division_code, adjustment_name, adjustment_type, amount
FROM payroll_manual_adjustments
WHERE period_month = {month}
  AND period_year = {year}
  AND division_code = '{division_code}'
ORDER BY emp_code, adjustment_type
```

**Table:** `payroll_manual_adjustments` (database: `extend_db_ptrj`, profile: `SERVER_PROFILE_1`)

---

## Filter Per Division

```bash
# Filter by division_code (semua gang dalam divisi)
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1" \
  -H "X-API-Key: ${API_KEY}"

# Filter by gang_code (gang spesifik)
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&gang_code=H1H" \
  -H "X-API-Key: ${API_KEY}"

# Filter by division + gang (spesifik)
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&gang_code=H1H" \
  -H "X-API-Key: ${API_KEY}"
  -H "X-API-Key: ${API_KEY}"
```

---

## Authentication

Semua endpoint manual adjustment memerlukan header `X-API-Key`.

```bash
# API Key yang dikonfigurasi di backend/.env
X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a
```

Jika API key valid, request akan mendapat akses **ADMIN** dengan semua divisions.

---

## ADCode untuk Manual Adjustment

Manual adjustment kategori `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, dan `PENDAPATAN_LAINNYA` wajib membawa `ad_code` saat membuat kolom/manual adjustment baru. Hanya `AUTO_BUFFER` yang boleh disimpan tanpa `ad_code`. Endpoint `adjustment-name-options/by-api-key` hanya mengembalikan variasi `adjustment_name`; jangan ambil ADCode dari endpoint itu.

Remarks disimpan dengan format:

```text
AD CODE: <adcode> - <taskdesc>
```

Parser response mendukung format remarks lama/automation berikut untuk mengisi `ad_code` dan `ad_code_desc` saat kolom structured (`ad_code`, `task_code`, `base_task_code`, `task_desc`) masih kosong:

```text
AD CODE: <adcode> - <taskdesc>
<adjustment_name> | <adcode> - <taskdesc> | <amount> | sync:<status> | match:<status>
<adjustment_name> | (<adcode>) <taskdesc> - <taskdesc> | <amount> | sync:<status> | match:<status>
<adjustment_name> | <taskdesc> - <taskdesc> | <amount> | sync:<status> | match:<status>
```

Untuk remarks pipe-delimited, parser hanya mengambil hasil `remarks.split("|")[1]` sebagai sumber ADCode/TaskDesc. Jika segmen itu diawali kode dalam kurung seperti `(AL0018P1A)`, response mengisi `ad_code` dari kode tersebut dan `ad_code_desc` dari TaskDesc setelahnya. Jika segmen ADCode/TaskDesc diawali `(AL)` atau `(DE)`, parser memperlakukannya sebagai **TaskDesc display**, bukan kode ADCode pendek.

Contoh:

```text
PREMI TBS | (AL) TUNJANGAN PREMI ((PM) HARVESTING LABOUR - HARVESTING) - (AL) TUNJANGAN PREMI ((PM) HARVESTING LABOUR - HARVESTING) | 423363 | sync:MANUAL | match:MANUAL
PREMI JAGA | (AL0018P1A) (AL) TUNJANGAN JAGA GENSET - (AL) TUNJANGAN JAGA GENSET | 350000 | sync:MANUAL | match:MANUAL
```

Parser contoh `PREMI JAGA` akan menghasilkan:

```json
{
  "ad_code": "AL0018P1A",
  "ad_code_desc": "(AL) TUNJANGAN JAGA GENSET",
  "task_desc": "(AL) TUNJANGAN JAGA GENSET"
}
```

**Catatan parsing remarks:**

- Tanda minus dalam TaskDesc seperti `HARVESTING LABOUR - HARVESTING` tidak dianggap sebagai pemisah ADCode.
- Pemisah TaskDesc display hanya valid jika setelah ` - ` ada awalan `(AL)` atau `(DE)`.
- Parser remarks bekerja secara berurutan: jika kolom structured (`ad_code`, `task_code`, `base_task_code`, `task_desc`) sudah terisi, nilainya digunakan langsung; baru kemudian fallback ke parse remarks.
- Format `AD CODE: <adcode> - <taskdesc>` di remarks juga tetap didukung untuk backward compatibility.
- Format `AD CODE: <taskdesc>` (tanpa kode pendek) juga didukung untuk remarks yang hanya menyimpan TaskDesc display saja.
- Jika structured field kosong dan remarks tidak bisa diparse, response fallback ke `backend/data/premium_definitions.json` berdasarkan `adjustment_name`. Ini memastikan premi/koreksi/potongan yang sudah punya definisi tetap memiliki `ad_code_desc`/`task_desc`.

Daftar ADCode diambil dari cache JSON `backend/data/taskcode_mapping_db_ptrj.json` yang bersumber dari `PR_TASKCODE` dengan filter:

```sql
SELECT DISTINCT [TaskDesc]
FROM [db_ptrj].[dbo].[PR_TASKCODE]
WHERE [TaskDesc] LIKE '(AL)%'
   OR [TaskDesc] LIKE '(DE)%'
ORDER BY [TaskDesc];
```

### GET `/payroll/manual-adjustment/taskcode-options`

Endpoint untuk search ADCode saat user mengetik di popup tambah kolom manual adjustment.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `search` | string | ❌ | Cari berdasarkan ADCode, TaskCode, atau TaskDesc |
| `division_code` | string | ❌ | Filter suffix lokasi/divisi jika tersedia |
| `limit` | string | ❌ | Maksimal data, default 50, maksimum 100 |

**Response:**

```json
{
  "success": true,
  "count": 1,
  "data": [
    {
      "ad_code": "AL0001",
      "task_code": "AL0001",
      "base_task_code": "AL0001",
      "task_desc": "(AL) BENEFIT IN KIND - ACCOMMODATION",
      "doc_desc": "(AL) BENEFIT IN KIND - ACCOMMODATION",
      "loc_code": null
    }
  ]
}
```

### GET `/payroll/manual-adjustment/automation-options/by-api-key`

Endpoint automation agent untuk mengambil pilihan input siap pakai dari `PR_TASKCODE`/cache taskcode. Endpoint ini memakai header `X-API-Key` dan mengembalikan `ad_code`; `description` hasil bersih dari `TaskDesc`; serta `adjustment_name` yang sama dengan `description`.

Kategori yang dikembalikan:

| `category` | `adjustment_type` untuk save | Aturan dari deskripsi |
|------------|------------------------------|------------------------|
| `premi` | `PREMI` | `(AL)` selain potongan/koreksi, SPSI, dan PPH |
| `koreksi` | `POTONGAN_KOTOR` | Deskripsi mengandung `KOREKSI` |
| `potongan_upah_bersih` | `POTONGAN_BERSIH` | Deskripsi mengandung `POTONGAN`, `POT `, atau `POT_` selain SPSI/PPH |

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `search` | string | ❌ | Cari berdasarkan ADCode, TaskCode, atau TaskDesc sumber |
| `division_code` | string | ❌ | Filter suffix lokasi/divisi jika tersedia |
| `categories` | string | ❌ | Comma separated: `premi,koreksi,potongan_upah_bersih` |
| `limit` | string | ❌ | Maksimal data, default 100, maksimum 200 |

**Example:**

```bash
curl -s "http://localhost:8002/payroll/manual-adjustment/automation-options/by-api-key?division_code=P1A&categories=premi,koreksi,potongan_upah_bersih" \
  -H "X-API-Key: $API_KEY"
```

**Response:**

```json
{
  "success": true,
  "count": 2,
  "data": [
    {
      "category": "premi",
      "adjustment_type": "PREMI",
      "adjustment_name": "INSENTIF PANEN",
      "ad_code": "A100",
      "description": "INSENTIF PANEN",
      "task_code": "A100P1A",
      "task_desc": "(AL) INSENTIF PANEN",
      "base_task_code": "A100",
      "loc_code": "P1A"
    },
    {
      "category": "koreksi",
      "adjustment_type": "POTONGAN_KOTOR",
      "adjustment_name": "KOREKSI PANEN",
      "ad_code": "D200",
      "description": "KOREKSI PANEN",
      "task_code": "D200P1A",
      "task_desc": "(DE) KOREKSI PANEN",
      "base_task_code": "D200",
      "loc_code": "P1A"
    },
    {
      "category": "potongan_upah_bersih",
      "adjustment_type": "POTONGAN_BERSIH",
      "adjustment_name": "POTONGAN PINJAMAN",
      "ad_code": "D300",
      "description": "POTONGAN PINJAMAN",
      "task_code": "D300P1A",
      "task_desc": "(DE) POTONGAN PINJAMAN",
      "base_task_code": "D300",
      "loc_code": "P1A"
    }
  ]
}
```

### GET `/payroll/manual-adjustment/adjustment-name-options/by-api-key`

Endpoint khusus untuk automation mengambil variasi `adjustment_name` yang benar-benar sudah ada di `payroll_manual_adjustments`. Endpoint ini **bukan** daftar dari `PR_TASKCODE`. Pakai endpoint ini jika perlu tahu premi/koreksi/potongan apa saja yang dimiliki suatu estate/divisi sumber atau suatu gang berdasarkan data manual adjustment yang tersimpan.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `adjustment_type` | string | ❌ | Comma separated. Default semua: `PREMI,POTONGAN_KOTOR,POTONGAN_BERSIH`. Alias: `KOREKSI` = `POTONGAN_KOTOR`, `POTONGAN_UPAH_BERSIH` = `POTONGAN_BERSIH`. |
| `period_month` | string | ❌ | Filter bulan payroll, misalnya `4`. Disarankan dikirim agar variasi sesuai periode input. |
| `period_year` | string | ❌ | Filter tahun payroll, misalnya `2026`. |
| `division_code` / `estate` | string | ❌ | Filter estate/lokasi sumber yang tersimpan di DB, misalnya `AB1`, `P1A`, `P2A`. Alias estate seperti `ARB1` ikut dinormalisasi ke `AB1`. |
| `gang_code` | string | ❌ | Filter gang tertentu, misalnya `G1H`. |
| `metadata_only` / `has_metadata` | string | ❌ | Jika `true`, hanya hitung variasi dari row yang punya `metadata_json`/detail transaksi baru. |
| `search` | string | ❌ | Cari berdasarkan `adjustment_name` yang tersimpan. |
| `limit` | string | ❌ | Maksimal variasi yang dikembalikan, default 200, maksimum 500. |

**Ambil semua variasi nama per tipe dalam satu estate:**

```bash
curl -s "http://localhost:8002/payroll/manual-adjustment/adjustment-name-options/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=PREMI,POTONGAN_KOTOR,POTONGAN_BERSIH&limit=200" \
  -H "X-API-Key: ${API_KEY}"
```

**Ambil variasi premi yang dimiliki satu gang:**

```bash
curl -s "http://localhost:8002/payroll/manual-adjustment/adjustment-name-options/by-api-key?period_month=4&period_year=2026&division_code=AB1&gang_code=G1H&adjustment_type=PREMI&metadata_only=true&limit=200" \
  -H "X-API-Key: ${API_KEY}"
```

**Ambil variasi koreksi dan potongan upah bersih yang tersimpan:**

```bash
curl -s "http://localhost:8002/payroll/manual-adjustment/adjustment-name-options/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=POTONGAN_KOTOR,POTONGAN_BERSIH&limit=200" \
  -H "X-API-Key: ${API_KEY}"
```

**Response:**

```json
{
  "success": true,
  "count": 4,
  "adjustment_types": ["PREMI", "POTONGAN_KOTOR", "POTONGAN_BERSIH"],
  "adjustment_names_by_type": {
    "PREMI": ["PREMI PRUNING", "PREMI TBS"],
    "POTONGAN_KOTOR": ["KOREKSI PANEN"],
    "POTONGAN_BERSIH": ["POTONGAN PINJAMAN"]
  },
  "by_type": {
    "PREMI": [
      { "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING" },
      { "adjustment_type": "PREMI", "adjustment_name": "PREMI TBS" }
    ],
    "POTONGAN_KOTOR": [
      { "adjustment_type": "POTONGAN_KOTOR", "adjustment_name": "KOREKSI PANEN" }
    ],
    "POTONGAN_BERSIH": [
      { "adjustment_type": "POTONGAN_BERSIH", "adjustment_name": "POTONGAN PINJAMAN" }
    ]
  },
  "data": [
    { "adjustment_type": "PREMI", "adjustment_name": "PREMI PRUNING" },
    { "adjustment_type": "PREMI", "adjustment_name": "PREMI TBS" },
    { "adjustment_type": "POTONGAN_KOTOR", "adjustment_name": "KOREKSI PANEN" },
    { "adjustment_type": "POTONGAN_BERSIH", "adjustment_name": "POTONGAN PINJAMAN" }
  ]
}
```

Gunakan `adjustment_names_by_type` jika hanya butuh list nama. Query dasarnya sesederhana `SELECT DISTINCT adjustment_name FROM payroll_manual_adjustments WHERE adjustment_type = ... ORDER BY adjustment_name ASC`; endpoint hanya menambahkan filter periode, estate, gang, dan metadata jika dikirim.

Saat agent memakai response endpoint ini:

- `adjustment_type` dari response.
- `adjustment_name` dari response.
- Endpoint ini tidak mengirim `ad_code`, `task_code`, `task_desc`, atau `base_task_code` karena sumbernya hanya variasi nama yang sudah tersimpan di `payroll_manual_adjustments`. Jika proses save membutuhkan ADCode/TaskDesc, ambil dari detail transaksi/row manual adjustment terkait atau endpoint taskcode terpisah.
- Identitas karyawan wajib dipisahkan: `emp_code` berisi EmpCode PTRJ/Plantware, `nik` berisi NIK/KTP, dan `emp_name` hanya berisi nama karyawan. Jangan pernah mengirim NIK di `emp_name`.

**Payload Save Manual Adjustment:**

```json
{
  "period_month": 4,
  "period_year": 2026,
  "emp_code": "A0001",
  "nik": "1902050504860001",
  "emp_name": "BUDI TEST",
  "gang_code": "G1H",
  "division_code": "AB1",
  "adjustment_type": "PREMI",
  "adjustment_name": "PREMI MANUAL",
  "amount": 100000,
  "ad_code": "(AL) BENEFIT IN KIND - ACCOMMODATION",
  "task_code": "AL0001AB1",
  "base_task_code": "AL0001",
  "task_desc": "(AL) BENEFIT IN KIND - ACCOMMODATION",
  "remarks": "AD CODE: (AL) BENEFIT IN KIND - ACCOMMODATION"
}
```

Jika caller tidak yakin nama karyawan benar, jangan kirim `emp_name`; backend akan mencoba resolve nama dari `HR_EMPLOYEE.EmpName` berdasarkan `emp_code`/`nik`. Jangan mengisi `emp_name` dengan NIK numeric atau EmpCode.

Jika `ad_code` kosong untuk kategori selain `AUTO_BUFFER`, API akan menolak request dengan error `ADCode wajib diisi untuk manual adjustment selain auto buffer`.

---

## Endpoints

### 1. GET `/payroll/manual-adjustment/by-api-key`

Ambil data manual adjustment berdasarkan periode.

Endpoint ini adalah endpoint read-only utama untuk agent mengambil isi tabel
`extend_db_ptrj.dbo.payroll_manual_adjustments`. Jika `adjustment_type`
tidak dikirim, response berisi semua kategori yang tersimpan:

- `AUTO_BUFFER`
- `PREMI`
- `POTONGAN_KOTOR`
- `POTONGAN_BERSIH`
- `PENDAPATAN_LAINNYA`

Filter `division_code` menormalisasi format kode divisi 3-kode dan 4-kode
untuk data manual adjustment yang tersimpan dengan format berbeda. Contoh:
`P2A`, `PG2A`, dan `2A` akan mengambil gabungan row `P2A` + `PG2A`.
Alias yang didukung: `P1A/PG1A/1A`, `P1B/PG1B/1B`, `P2A/PG2A/2A`,
`P2B/PG2B/2B`, `AB1/ARB1`, `AB2/ARB2`, dan `ARC/AREC`.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period_month` | string | ✅ | Bulan (1-12) |
| `period_year` | string | ✅ | Tahun (e.g. "2026") |
| `gang_code` | string | ❌ | Filter per gang |
| `emp_code` | string | ❌ | Filter per employee code |
| `division_code` | string | ❌ | Filter per division |
| `adjustment_type` | string | ❌ | Filter per type: `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, `PENDAPATAN_LAINNYA`, `AUTO_BUFFER`, `MANUAL` (alias = semua kecuali AUTO_BUFFER). Mendukung comma-separated, e.g. `PREMI,POTONGAN_KOTOR` |
| `adjustment_name` | string | ❌ | Filter per nama (partial match) |
| `view` | string | ❌ | Format response. Default `flat`. Pakai `grouped` untuk response siap auto input: division -> gang -> employee -> premiums/adjustments. |
| `metadata_only` | string | ❌ | Jika `true`, hanya ambil row yang memiliki `metadata_json`. Ini disarankan untuk data premi detail terbaru; row tanpa metadata adalah format lama. Alias: `has_metadata=true`. |

**Response Fields Penting untuk Agent:**

| Field | Makna |
|-------|-------|
| `emp_code` | Kode karyawan PTRJ/Plantware dari `HR_EMPLOYEE.EmpCode`, contoh `C0763`. Row lama bisa masih berisi NIK numeric, tetapi save baru harus memakai EmpCode PTRJ. |
| `emp_name` | Nama karyawan dari `HR_EMPLOYEE.EmpName` jika tersedia. Field ini bukan NIK. |
| `nik` | NIK/KTP karyawan dari `HR_EMPLOYEE.NewICNo` jika tersedia. |
| `gang_code` | Gang/asistensi asal row manual adjustment. Field ini wajib dipakai agent saat menampilkan atau mengelompokkan detail karyawan. |
| `estate` / `estate_code` | Kode estate/lokasi yang sebelumnya tersimpan sebagai `division_code` di DB, misalnya `AB1`, `P2A`, atau `PG2A`. |
| `division_code` | Kode divisi turunan dari `gang_code`: ambil 2 karakter awal gang lalu pisahkan spasi. Contoh `C2H` menjadi `C 2`, `G1H` menjadi `G 1`. |
| `adjustment_type` | Kategori row: `AUTO_BUFFER`, `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, atau `PENDAPATAN_LAINNYA`. |
| `adjustment_name` | Nama adjustment/kolom. |
| `ad_code` | ADCode terpisah. Diambil dari kolom `ad_code`/`base_task_code`/`task_code`; jika kosong akan diparse dari `remarks`, misalnya `AD CODE: AL0001 - ...` atau `PREMI | AL3PM0601P1A - ...`. |
| `ad_code_desc` | Deskripsi ADCode terpisah dari `task_desc` atau hasil parse `remarks`. |
| `amount` | Total nominal row adjustment di `payroll_manual_adjustments`. Untuk row yang punya `metadata_json`, field ini adalah agregat/total row, bukan detail transaksi tunggal. Jangan pakai field ini sebagai sumber auto input per subblok. |
| `remarks` | Catatan sinkronisasi/manual edit, termasuk ADCode jika ada. |
| `metadata_json` | JSON string detail input jika ada, misalnya detail `blok`, `exp`, `kendaraan`, atau `blok,exp`. Inilah sumber detail transaksi terbaru. |

**Terminologi identitas karyawan di codebase ini:**

| Istilah | Sumber | Makna |
|---------|--------|-------|
| `emp_code` | `HR_EMPLOYEE.EmpCode` | Kode karyawan internal PTRJ/Plantware, biasanya huruf + angka seperti `A0001`, `B0745`, `C0763`. Field ini yang dipakai untuk query payroll PTRJ seperti `PR_ADTRANS.EmpCode`. |
| `nik` | `HR_EMPLOYEE.NewICNo` | NIK/KTP numeric karyawan. Di beberapa flow lama nama field `nik` pernah dipakai untuk EmpCode internal, tetapi pada manual adjustment yang baru `nik` berarti NIK/KTP. |
| `emp_name` | `HR_EMPLOYEE.EmpName` | Nama karyawan, misalnya `BUDI TEST`. Ini bukan identifier dan bukan NIK. |

Catatan penting: saat menyimpan manual adjustment, backend me-resolve input `emp_code`/`nik` ke identitas HR lalu menyimpan `emp_code`, `nik`, dan `emp_name`. Namun kode `saveAdjustment()` masih memprioritaskan `emp_name` dari request sebelum nama hasil resolve HR. Jadi jika caller/agent mengirim NIK numeric di field `emp_name`, nilai itu bisa ikut tersimpan sebagai `emp_name`. Secara konsep data, itu salah isi payload; `emp_name` seharusnya nama dari `HR_EMPLOYEE.EmpName`, sementara NIK harus dikirim di field `nik`.

Catatan: endpoint data manual adjustment (`/manual-adjustment/by-api-key` dan `/manual-adjustment`) selalu mengembalikan `gang_code` pada setiap row data karyawan. Endpoint master opsi seperti `taskcode-options`, `automation-options`, dan `manual-adjustment-presets` bukan data karyawan, sehingga tidak memiliki `gang_code`.

#### `view=grouped` untuk Auto Input per Employee

Pakai `view=grouped` jika agent perlu menginput ulang/otomasi per nama orang. Response akan mengelompokkan data dari atas ke bawah:

```text
estate -> gang -> employee -> premiums/adjustments -> detail transaksi
```

Filter tetap sama seperti response flat. Query parameter `division_code` tetap berarti estate/lokasi sumber seperti `AB1`; pada response, `estate` menyimpan `AB1`, sedangkan `division_code` adalah hasil turunan dari `gang_code`.

Untuk auto input premi detail terbaru, gunakan:

```text
view=grouped&adjustment_type=PREMI&metadata_only=true
```

`metadata_only=true` membuang row lama yang tidak punya `metadata_json`. Alias yang sama: `has_metadata=true`.

**Kontrak penting untuk auto input detail transaksi:**

- Gunakan `employee.premium_transactions[]` sebagai sumber utama auto input. Satu item di array ini = satu detail transaksi dari `metadata_json`, misalnya satu subblok, satu kendaraan, atau satu expense.
- Jangan memakai `premiums[].amount`, `adjustments[].amount`, atau row flat `amount` sebagai detail transaksi. Field itu adalah total row di DB. Contoh `PREMI PRUNING` amount `504900` bisa berasal dari beberapa subblok di metadata.
- Untuk metadata `input_type = "blok"`, nilai per detail diambil dari `metadata_json.items[].jumlah`, lalu endpoint menampilkannya sebagai `premium_transactions[].jumlah` dan `premium_transactions[].amount`.
- Untuk field subblok, endpoint menormalisasi simbol: `subblok` hanya berisi huruf dan angka. Contoh `P09/01-A` menjadi `P0901A`. Jika nilai asli mengandung simbol, nilai aslinya tetap tersedia di `subblok_raw`.
- Untuk data lama tanpa `metadata_json`, endpoint tidak punya subblok/detail transaksi. Pakai `metadata_only=true` supaya automation hanya memproses data detail terbaru.
- Tree preview yang benar tidak berhenti di baris `Division | Gang | Employee | Type | Name | Amount`. Row seperti `AB1 | G1H | AHMAD DARYONO | PREMI | PREMI PRUNING | 504900` adalah total row; detail subbloknya harus dibaca dari `premium_transactions[]` atau `premiums[].detail_items[]`.

**Urutan auto input yang disarankan:**

```text
for each estate in data:
  for each gang in estate.gangs:
    for each employee in gang.employees:
      for each tx in employee.premium_transactions:
        input employee tx.adjustment_name tx.subblok/tx.expense_code/tx.kendaraan tx.amount
```

**Filter umum:**

```text
# Satu divisi, semua gang
period_month=4&period_year=2026&division_code=AB1&adjustment_type=PREMI&metadata_only=true&view=grouped

# Satu gang
period_month=4&period_year=2026&division_code=AB1&gang_code=G1H&adjustment_type=PREMI&metadata_only=true&view=grouped

# Satu employee
period_month=4&period_year=2026&emp_code=A0001&adjustment_type=PREMI&metadata_only=true&view=grouped
```

**Example Request:**

```bash
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=PREMI&metadata_only=true&view=grouped" \
  -H "X-API-Key: ${API_KEY}"
```

**Response Shape:**

```json
{
  "success": true,
  "view": "grouped",
  "metadata_only": true,
  "count": 1,
  "summary": {
    "division_count": 1,
    "gang_count": 1,
    "employee_count": 1,
    "adjustment_count": 1
  },
  "data": [
    {
      "estate": "AB1",
      "estate_code": "AB1",
      "employee_count": 1,
      "gang_count": 1,
      "adjustment_count": 1,
      "premium_count": 1,
      "total_amount": 504900,
      "premium_total": 504900,
      "gangs": [
        {
          "gang_code": "G1H",
          "estate": "AB1",
          "estate_code": "AB1",
          "division_code": "G 1",
          "employee_count": 1,
          "adjustment_count": 1,
          "premium_count": 1,
          "employees": [
            {
              "emp_code": "A0001",
              "nik": "1902050504860001",
              "emp_name": "AHMAD DARYONO",
              "gang_code": "G1H",
              "estate": "AB1",
              "estate_code": "AB1",
              "division_code": "G 1",
              "adjustment_count": 1,
              "premium_count": 1,
              "total_amount": 504900,
              "premium_total": 504900,
              "premium_transactions": [
                {
                  "transaction_index": 1,
                  "adjustment_id": 1,
                  "adjustment_type": "PREMI",
                  "adjustment_name": "PREMI PRUNING",
                  "emp_code": "A0001",
                  "nik": "1902050504860001",
                  "emp_name": "AHMAD DARYONO",
                  "gang_code": "G1H",
                  "estate": "AB1",
                  "estate_code": "AB1",
                  "division_code": "G 1",
                  "ad_code": "AL3PM0601P1A",
                  "ad_code_desc": "PREMI PRUNING",
                  "detail_type": "blok",
                  "subblok": "P0901",
                  "subblok_raw": "P09/01",
                  "jumlah": 304000,
                  "amount": 304000
                },
                {
                  "transaction_index": 2,
                  "adjustment_id": 1,
                  "adjustment_type": "PREMI",
                  "adjustment_name": "PREMI PRUNING",
                  "emp_code": "A0001",
                  "nik": "1902050504860001",
                  "emp_name": "AHMAD DARYONO",
                  "gang_code": "G1H",
                  "estate": "AB1",
                  "estate_code": "AB1",
                  "division_code": "G 1",
                  "ad_code": "AL3PM0601P1A",
                  "ad_code_desc": "PREMI PRUNING",
                  "detail_type": "blok",
                  "subblok": "P0902",
                  "subblok_raw": "P09/02",
                  "jumlah": 200900,
                  "amount": 200900
                }
              ],
              "premiums": [
                {
                  "id": 1,
                  "adjustment_type": "PREMI",
                  "adjustment_name": "PREMI PRUNING",
                  "ad_code": "AL3PM0601P1A",
                  "ad_code_desc": "PREMI PRUNING",
                  "amount": 504900,
                  "metadata_json": "{\"input_type\":\"blok\",\"items\":[{\"subblok\":\"P09/01\",\"gang_code\":\"G1H\",\"jumlah\":304000},{\"subblok\":\"P09/02\",\"gang_code\":\"G1H\",\"jumlah\":200900}],\"total_amount\":504900}",
                  "metadata": {
                    "input_type": "blok",
                    "items": [
                      { "subblok": "P09/01", "gang_code": "G1H", "jumlah": 304000 },
                      { "subblok": "P09/02", "gang_code": "G1H", "jumlah": 200900 }
                    ],
                    "total_amount": 504900
                  },
                  "metadata_parse_error": null,
                  "detail_items": [
                    {
                      "detail_type": "blok",
                      "subblok": "P0901",
                      "subblok_raw": "P09/01",
                      "gang_code": "G1H",
                      "jumlah": 304000,
                      "amount": 304000
                    },
                    {
                      "detail_type": "blok",
                      "subblok": "P0902",
                      "subblok_raw": "P09/02",
                      "gang_code": "G1H",
                      "jumlah": 200900,
                      "amount": 200900
                    }
                  ]
                }
              ],
              "adjustments": [
                {
                  "id": 1,
                  "adjustment_type": "PREMI",
                  "adjustment_name": "PREMI PRUNING",
                  "ad_code": "AL3PM0601P1A",
                  "ad_code_desc": "PREMI PRUNING",
                  "amount": 504900,
                  "metadata_parse_error": null,
                  "detail_items": [
                    { "detail_type": "blok", "subblok": "P0901", "subblok_raw": "P09/01", "gang_code": "G1H", "jumlah": 304000, "amount": 304000 },
                    { "detail_type": "blok", "subblok": "P0902", "subblok_raw": "P09/02", "gang_code": "G1H", "jumlah": 200900, "amount": 200900 }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

Catatan response grouped:

- `premium_transactions` adalah daftar datar per detail transaksi dari seluruh premi employee tersebut. Ini field utama untuk auto input per subblok/kendaraan/expense.
- `premium_transactions[].amount` adalah nominal detail transaksi, sama dengan `jumlah` pada metadata jika metadata memakai field `jumlah`.
- `estate` / `estate_code` adalah estate/lokasi seperti `AB1`; jangan dibaca sebagai division Plantware.
- `division_code` di response adalah turunan dari `gang_code`, misalnya `C2H -> C 2` dan `G1H -> G 1`.
- `ad_code` dan `ad_code_desc` sudah dipisahkan dari `remarks`; automation tidak perlu parse string remarks lagi.
- `premiums` hanya berisi row `adjustment_type = "PREMI"` milik employee tersebut. `premiums[].amount` tetap total row.
- `adjustments` berisi semua row adjustment employee tersebut sesuai filter request. Jika request `adjustment_type=PREMI`, isinya sama dengan row premi.
- `metadata_json` tetap ditampilkan sebagai raw JSON string dari DB.
- `metadata` adalah hasil parse `metadata_json` agar agent tidak perlu parse manual.
- `detail_items` adalah bentuk datar dari detail transaksi di `metadata`, tersedia di setiap row premium/adjustment.
- Row tanpa `metadata_json` dianggap data lama. Pakai `metadata_only=true` untuk fokus ke data detail terbaru saja.

**Bentuk metadata yang dipecah menjadi detail transaksi:**

| `metadata.input_type` | Sumber detail | Field nominal detail | Output di grouped response |
|-----------------------|---------------|----------------------|----------------------------|
| `blok` | `metadata.items[]` | `jumlah` atau `amount` | `premium_transactions[]` dengan `detail_type: "blok"`, `subblok` alphanumeric, `subblok_raw` jika asalnya mengandung simbol, `gang_code`, `jumlah`, `amount` |
| `kendaraan` | `metadata.items[]` | `jumlah` atau `amount` | `premium_transactions[]` dengan `detail_type: "kendaraan"`, `vehicle_code` dari `vehicle_code`/`nomor_kendaraan`/`NOMOR_KENDARAAN`, dan `vehicle_expense_code` dari `vehicle_expense_code` atau `expense_code` metadata |
| `exp` | object metadata langsung atau `expense` | `amount`, `jumlah`, atau `total_amount` | `premium_transactions[]` dengan `detail_type: "exp"` plus field expense dari metadata |
| `blok,exp` | `metadata.blok_items[]` + `metadata.expense` | `jumlah` atau `amount` | Gabungan detail `blok` dan `exp` dalam satu `premium_transactions[]` employee |

Aturan vehicle-based untuk agent:

- Jika detail metadata punya `subblok`, form yang dipakai adalah block-based.
- Jika detail metadata punya `vehicle_code`, `nomor_kendaraan`, `NOMOR_KENDARAAN`, `nomorKendaraan`, `no_kendaraan`, atau `vehicle_number`, form yang dipakai adalah vehicle-based.
- Pada vehicle-based, nilai kendaraan harus dikirim ke runner sebagai `vehicle_code`; jangan dimasukkan ke employee, NIK, atau description.
- `expense_code` dari item metadata adalah sumber `Vehicle Expense Code` Plantware jika `vehicle_expense_code` belum tersedia.
- Contoh P1B gang B1T `PREMI ANGKUT`: `metadata_json.items[].nomor_kendaraan = "T0020"` dan `expense_code = "DRIVER"` harus menjadi `vehicle_code = "T0020"` dan `vehicle_expense_code = "DRIVER"` pada payload auto key-in.

Halaman testing lokal untuk endpoint ini tersedia di:

```text
Browser Automation/manual-adjustment-grouped-tester.html
```

Halaman tersebut menyediakan dropdown sederhana untuk `view`, `division_code`, `gang_code`, `adjustment_type`, periode, dan field optional lain. Tree preview harus menampilkan employee lalu dropdown/detail subblok dari `metadata_json` (`premium_transactions[]`/`detail_items[]`), bukan hanya total row `amount`.

**Example:**

```bash
curl -X GET "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&gang_code=H1H" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"
```

**Filter Examples:**

```bash
# Ambil semua kategori manual adjustment dalam satu division
# Termasuk AUTO_BUFFER, PREMI, POTONGAN_KOTOR, POTONGAN_BERSIH, PENDAPATAN_LAINNYA
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Ambil semua kategori untuk satu employee
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&emp_code=B0745" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Ambil detail satu employee dalam divisi 2A, tetap membawa gang_code
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=P2A&emp_code=C0763" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter by adjustment_type = AUTO_BUFFER only
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=AUTO_BUFFER" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter by adjustment_type = PREMI only
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=PREMI" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter koreksi/potongan kotor only
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=POTONGAN_KOTOR" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter potongan upah bersih only
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=POTONGAN_BERSIH" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter by adjustment_name (partial match - contains "SPSI")
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_name=SPSI" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter by adjustment_name (contains "MASA")
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_name=MASA" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Combined filters: division + type
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=PREMI" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter MANUAL alias (semua kecuali AUTO_BUFFER: PREMI, POTONGAN_KOTOR, POTONGAN_BERSIH, PENDAPATAN_LAINNYA)
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=MANUAL" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter comma-separated types (PREMI + POTONGAN_KOTOR)
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=PREMI,POTONGAN_KOTOR" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter comma-separated (PREMI + POTONGAN_BERSIH)
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=PREMI,POTONGAN_BERSIH" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Via proxy
curl -s "http://localhost/backend/upah/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_name=SPSI" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter by specific AUTO_BUFFER names
# AUTO SPSI only
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_name=AUTO%20SPSI" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# AUTO MASA KERJA only
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_name=MASA%20KERJA" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# AUTO TUNJANGAN JABATAN only
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_name=TUNJANGAN%20JABATAN" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"
```

**Response:**

```json
{
  "success": true,
  "count": 411,
  "data": [
    {
      "id": 10730,
      "period_month": 4,
      "period_year": 2026,
      "emp_code": "G0007",
      "gang_code": "G1H",
      "division_code": "AB1",
      "adjustment_type": "AUTO_BUFFER",
      "adjustment_name": "AUTO TUNJANGAN JABATAN",
      "amount": 0,
      "remarks": "AUTO TUNJANGAN JABATAN | tunjangan jabatan | 0",
      "created_by": "api_key_admin",
      "created_at": "2026-04-25T13:41:38.107Z"
    },
    {
      "id": 10731,
      "period_month": 4,
      "period_year": 2026,
      "emp_code": "G0007",
      "gang_code": "G1H",
      "division_code": "AB1",
      "adjustment_type": "AUTO_BUFFER",
      "adjustment_name": "AUTO MASA KERJA",
      "amount": 27000,
      "remarks": "AUTO MASA KERJA | masa kerja | 27000",
      "created_by": "api_key_admin",
      "created_at": "2026-04-25T13:41:38.160Z"
    },
    {
      "id": 10732,
      "period_month": 4,
      "period_year": 2026,
      "emp_code": "G0007",
      "gang_code": "G1H",
      "division_code": "AB1",
      "adjustment_type": "AUTO_BUFFER",
      "adjustment_name": "AUTO SPSI",
      "amount": 4000,
      "remarks": "AUTO SPSI | potongan spsi | 4000",
      "created_by": "api_key_admin",
      "created_at": "2026-04-25T13:41:38.187Z"
    }
  ]
}
```

**Contoh Response Detail Employee dengan `gang_code`:**

```json
{
  "success": true,
  "count": 3,
  "data": [
    {
      "emp_code": "C0763",
      "emp_name": "INDAR JAYA ( SAHUTI )",
      "gang_code": "C1B",
      "division_code": "PG2A",
      "adjustment_type": "POTONGAN_KOTOR",
      "adjustment_name": "Koreksi Brondol",
      "amount": 3500,
      "remarks": "KOREKSI BRONDOL | DE0004 - (DE) POTONGAN PREMI | 3500 | sync:MANUAL | match:MANUAL"
    },
    {
      "emp_code": "C0763",
      "emp_name": "INDAR JAYA ( SAHUTI )",
      "gang_code": "C1B",
      "division_code": "PG2A",
      "adjustment_type": "POTONGAN_BERSIH",
      "adjustment_name": "POTONGAN LAINNYA POTONGAN TIKET",
      "amount": 749053,
      "remarks": "POTONGAN TIKET | DE0002 - (DE) POTONGAN HUTANG | 0 | sync:MISS | match:MISMATCH"
    },
    {
      "emp_code": "C0763",
      "emp_name": "INDAR JAYA ( SAHUTI )",
      "gang_code": "C1B",
      "division_code": "PG2A",
      "adjustment_type": "PREMI",
      "adjustment_name": "PREMI PRUNING",
      "amount": 266900,
      "remarks": "PREMI PRUNING | MANUAL EDIT | 266900 | sync:MANUAL | match:MANUAL"
    }
  ]
}
```

**Note:** GET endpoint mengembalikan semua adjustment_type termasuk `AUTO_BUFFER` dari seeder.

---

### 2. POST `/payroll/manual-adjustment/by-api-key`

Simpan manual adjustment baru atau update yang sudah ada (upsert berdasarkan unique key).

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `period_month` | number | ✅ | Bulan (1-12) |
| `period_year` | number | ✅ | Tahun |
| `nik` | string | ❌ | NIK/KTP numeric dari `HR_EMPLOYEE.NewICNo`; kirim jika tersedia |
| `emp_code` | string | ✅ | EmpCode PTRJ/Plantware dari `HR_EMPLOYEE.EmpCode`, contoh `C0001`; jangan isi dengan NIK |
| `emp_name` | string | ❌ | Nama karyawan dari `HR_EMPLOYEE.EmpName`; jangan isi dengan NIK/EmpCode |
| `gang_code` | string | ✅ | Gang code |
| `division_code` | string | ❌ | Division code |
| `adjustment_type` | string | ✅ | `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, `PENDAPATAN_LAINNYA`, `AUTO_BUFFER` |
| `adjustment_name` | string | ✅ | Nama adjustment |
| `amount` | number | ✅ | Jumlah nominal |
| `remarks` | string | ❌ | Catatan |

Rule identitas untuk save:

- Benar: `emp_code = "C0001"`, `nik = "1902050504860001"`, `emp_name = "BUDI TEST"`.
- Salah: `emp_name = "1902050504860001"` atau `emp_name = "C0001"`.
- Jika caller tidak yakin nama benar, jangan kirim `emp_name`; backend akan mencoba resolve dari `HR_EMPLOYEE`.

**Adjustment Types:**

| Type | Description |
|------|-------------|
| `PREMI` | Tunjangan bonus/premi tambahan |
| `POTONGAN_KOTOR` | Potongan dari upah kotor (koreksi) |
| `POTONGAN_BERSIH` | Potongan dari upah bersih |
| `PENDAPATAN_LAINNYA` | Pendapatan lain (THR, bonus, dll) |
| `AUTO_BUFFER` | Auto-generated Jabatan/Masa Kerja/SPSI (dari seeder) |

**Example:**

```bash
curl -X POST "http://localhost:8002/payroll/manual-adjustment/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "emp_code": "C0001",
    "nik": "1902050504860001",
    "emp_name": "BUDI TEST",
    "gang_code": "H1H",
    "division_code": "AB1",
    "adjustment_type": "PREMI",
    "adjustment_name": "BONUS LEBARAN",
    "amount": 500000,
    "remarks": "Bonus hari raya 2026"
  }'
```

**Response:**

```json
{
  "success": true,
  "id": 42,
  "message": "Manual adjustment saved successfully."
}
```

---

## Upsert Behavior

Manual adjustment menggunakan **upsert** — jika kombinasi berikut sudah ada, nilainya di-update:

- `period_month` + `period_year`
- employee identity match: resolved `emp_code`, resolved `nik`, atau original identifier legacy
- `adjustment_type`
- normalized `adjustment_name`

Jika belum ada, akan dibuat record baru.

---

## Cache

Setiap save/delete operation secara otomatis membersihkan cache payroll:

```
Pattern: :{period_month}:{period_year}
```

Ini memastikan data terbaru langsung dipakai pada request berikutnya.

---

## Error Responses

| Status | Message | Description |
|--------|---------|-------------|
| 400 | `period_month harus 1-12` | Bulan tidak valid |
| 400 | `period_year tidak valid` | Tahun tidak valid |
| 401 | `Unauthorized: invalid x-api-key` | API key tidak valid |
| 500 | `{error message}` | Error server |

---

## System Token Alternative

Jika `SYSTEM_TOKEN` dikonfigurasi di `.env`, bisa juga dipakai sebagai Bearer fallback:

```bash
# Menggunakan system token
curl -H "Authorization: Bearer system-internal-secret-token" \
     http://localhost:8002/payroll/divisions
```

---

## Auto Buffer Seeder

Seeder untuk generate otomatis adjustment tipe `AUTO_BUFFER`. Digunakan untuk mengisi `AUTO TUNJANGAN JABATAN`, `AUTO MASA KERJA`, dan `AUTO SPSI` secara otomatis dari data payroll.

### Endpoint

```
POST /payroll/manual-adjustment/seed-auto-buffer
```

atau via proxy:

```
POST /backend/upah/payroll/manual-adjustment/seed-auto-buffer
```

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `period_month` | number | ✅ | Bulan (1-12) |
| `period_year` | number | ✅ | Tahun |
| `division_code` | string | ✅ | Kode divisi (e.g. `AB1`, `PG1A`) |
| `gang_code` | string | ❌ | Kode gang (default: `ALL`) |
| `replace_existing` | boolean | ❌ | Hapus existing auto buffer sebelum seed (default: `true`) |
| `use_history_db` | boolean | ❌ | Pakai history DB (default: `false`) |
| `snapshot_version` | number | ❌ | Snapshot version |
| `created_by` | string | ❌ | User creator (default: `system`) |

### Response

```json
{
  "period_month": 4,
  "period_year": 2026,
  "division_code": "AB1",
  "gang_code": "ALL",
  "source_rows": 25,
  "seeded_entries": 75,
  "inserted": 70,
  "updated": 5,
  "deleted_existing": 0,
  "replace_existing": true,
  "value_priority_mode_source": "db_ptrj_only"
}
```

---

## Remarks Format for Auto Buffer

Setiap auto buffer entry memiliki remarks dengan format konsisten:

```
AUTO TUNJANGAN JABATAN | tunjangan jabatan | {amount}
AUTO MASA KERJA | masa kerja | {amount}
AUTO SPSI | potongan spsi | {amount}
```

Format: `{adjustment_name} | {adcode} | {amount}`

### Adcode Mapping

| Adjustment Name | Adcode | Description |
|-----------------|--------|-------------|
| `AUTO TUNJANGAN JABATAN` | `tunjangan jabatan` | Jabatan allowance |
| `AUTO MASA KERJA` | `masa kerja` | Masa kerja allowance |
| `AUTO SPSI` | `potongan spsi` | SPSI deduction |

### Example

```
AUTO TUNJANGAN JABATAN | tunjangan jabatan | 200000
AUTO MASA KERJA | masa kerja | 150000
AUTO SPSI | potongan spsi | 4000
```

---

## Proxy / Base URL Configuration

Backend bisa diakses via direct atau proxy path tergantung deployment:

### Direct Access (localhost / LAN IP)

```
http://localhost:8002
http://10.0.0.128:8002
```

### Via Reverse Proxy

```
http://{proxy_host}/backend/upah
```

Proxy prefix `/backend/upah` akan di-strip oleh middleware (aktifkan `USE_PROXY=true` di `.env`).

### Contoh Complete dengan Semua Base URL

```bash
API_KEY="88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# ===== DIRECT ACCESS =====
# Localhost
curl -X POST "http://localhost:8002/payroll/manual-adjustment/seed-auto-buffer" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"period_month":4,"period_year":2026,"division_code":"AB1"}'

# LAN IP
curl -X POST "http://10.0.0.128:8002/payroll/manual-adjustment/seed-auto-buffer" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"period_month":4,"period_year":2026,"division_code":"AB1"}'

# ===== VIA PROXY =====
# Local proxy
curl -X POST "http://localhost/backend/upah/payroll/manual-adjustment/seed-auto-buffer" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"period_month":4,"period_year":2026,"division_code":"AB1"}'

# Remote proxy
curl -X POST "http://10.0.0.128/backend/upah/payroll/manual-adjustment/seed-auto-buffer" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"period_month":4,"period_year":2026,"division_code":"AB1"}'

# ===== GET DATA =====
# Ambil data adjustment via proxy
curl -s "http://localhost/backend/upah/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1" \
  -H "X-API-Key: ${API_KEY}"
```

### Endpoint dengan Proxy Path

| Direct Path | Proxy Path |
|-------------|------------|
| `/payroll/manual-adjustment/by-api-key` | `/backend/upah/payroll/manual-adjustment/by-api-key` |
| `/payroll/manual-adjustment/seed-auto-buffer` | `/backend/upah/payroll/manual-adjustment/seed-auto-buffer` |

---

## Reference: DocDesc, TaskCode, TaskDesc Patterns

### Sumber Data

Data premi dan potongan berasal dari tabel **PR_ADTRANS** dan **PR_ADTRANSLN**:
- **Header**: PR_ADTRANS (mengandung DocDesc)
- **Detail**: PR_ADTRANSLN (mengandung Amount)

Data lembur berasal dari **PR_TASKREGLN** (OT=1) dan **PR_TASKCODE**.

---

### DocDesc untuk PREMI

**Query Pattern:**
```sql
WHERE UPPER(t.DocDesc) LIKE '%PREMI%'
  AND UPPER(t.DocDesc) NOT LIKE '%PPH%'  -- exclude PPH
  AND UPPER(t.DocDesc) NOT LIKE '%ADJ%'  -- exclude adjustment
```

| DocDesc Pattern | Normalized Key | Category | Notes |
|-----------------|----------------|----------|-------|
| `PREMI PANEN AL` | `premi_panen_al` | PREMI_PANEN | Air Larangan harvest |
| `PREMI PANEN BRONDOL` | `premi_brondol` | PREMI_BRONDOL | Brondol loose fruit |
| `PREMI PRUNING` | `premi_pruning` | PREMI_PRUNING | Pruning作业 |
| `PREMI INSENTIF` | `premi_insentif` | PREMI_INSENTIF | Insentif Panen |
| `PREMI KINERJA` | `premi_kinerja` | PREMI_KINERJA | Kinerja bonus |
| `PREMI PPH` | `premi_pph` | SPECIAL | Ditambahkan ke upah_bersih (bukan potongan) |
| `TUNJANGAN PREMI ...` | dynamic | PREMI | Dynamic premi dengan prefix |

**Excluded dari PREMI (tidak masuk calculation):**
- `PPH`, `PPH21`, `PPh21` → PPh21 tax (calculated terpisah)
- `LEMBUR` → Overtime (dari PR_TASKREGLN)
- `BRONDOL` → Sudah masuk `premi_brondol`
- `PRUN`, `PRUNING` → Sudah masuk `premi_pruning`
- `KOREKSI`, `KOREKSI PANEN`, `POTONGAN KOREKSI` → Koreksi (handled terpisah)
- `SPSI`, `IURAN SPSI` → Union dues (potongan)
- `TUNJANGAN JABATAN`, `TUNJANGAN MASA KERJA`, `TUNJANGAN BERAS` → Tunjangan (bukan premi)

---

### DocDesc untuk POTONGAN (Deductions)

**Query Pattern:**
```sql
WHERE ln.Amount < 0  -- negative = deduction
  AND UPPER(t.DocDesc) NOT LIKE 'POT%'     -- exclude koreksi
  AND UPPER(t.DocDesc) NOT LIKE '%PPH%'    -- exclude PPH
  AND UPPER(t.DocDesc) NOT LIKE 'SPSI'      -- exclude SPSI
  AND UPPER(t.DocDesc) NOT LIKE 'BERAS'     -- exclude beras
  AND UPPER(t.DocDesc) NOT LIKE 'JABATAN'   -- exclude jabatan
  AND UPPER(t.DocDesc) NOT LIKE 'MASA%'     -- exclude masa kerja
  AND UPPER(t.DocDesc) NOT LIKE 'LEMBUR%'  -- exclude lembur
```

| DocDesc Pattern | Normalized Key | Description |
|-----------------|----------------|-------------|
| `PPH21`, `POTONGAN PPH21`, `PPh21` | `pot_pph21` | PPh21 tax (via TER calculation) |
| `BPJS KESEHATAN` | `pot_bpjs_kesehatan` | Health insurance |
| `BPJS PENSIUN` | `pot_bpjs_pensiun` | Pension insurance |
| `SPSI`, `IURAN SPSI` | `pot_spsi` | Union dues (fixed Rp 4,000/bulan) |
| `KOREKSI*`, `POT KOREKSI*` | `pot_koreksi` | Correction deductions |
| `POTONGAN LAIN-LAIN` | `pot_lain` | Other deductions |
| `PINJAMAN KOPERASI` | `pot_pinjaman` | Loan deductions |

**Koreksi Special Handling:**
- DocDesc LIKE `POT%` → `pot_koreksi`
- DITAMBAHKAN ke `jumlah_upah_kotor` (untuk tampilan)
- TIDAK masuk `total_potongan` (untuk avoid double deduction)

---

### TaskCode dan TaskDesc untuk LEMBUR (Overtime)

**Sumber:** PR_TASKREGLN (OT=1) + PR_TASKCODE

**Query Pattern:**
```sql
-- Active Table
SELECT l.EmpCode, l.TrxDate, l.Hours, l.TaskCode, l.Amount, l.Rate
FROM PR_TASKREGLN l
JOIN PR_TASKREG m ON l.MasterID = m.ID
JOIN PR_TASKCODE tc ON l.TaskCode = tc.TaskCode
WHERE l.EmpCode = ? AND l.TrxDate >= ? AND l.TrxDate <= ? AND l.OT = 1

UNION ALL

-- Archive Table
SELECT l.EmpCode, l.TrxDate, l.Hours, l.TaskCode, l.Amount, l.Rate
FROM PR_TASKREGLN_ARC l
JOIN PR_TASKREG_ARC m ON l.MasterID = m.ID
JOIN PR_TASKCODE tc ON l.TaskCode = tc.TaskCode
WHERE l.EmpCode = ? AND l.TrxDate >= ? AND l.TrxDate <= ? AND l.OT = 1
```

**Struktur Record Lembur:**

```typescript
interface LemburRecord {
    trx_date: string;      // Tanggal transaksi (YYYY-MM-DD)
    task_code: string;     // Kode task dari PR_TASKCODE
    task_desc: string;     // Deskripsi task dari PR_TASKCODE
    day_type: string;      // "Hari Kerja", "Jumat", "Minggu", "Libur Umum", "Libur Keagamaan"
    hours: number;         // Jumlah jam lembur
    rate: number;          // Rate total (weighted average dari tier)
    amount: number;        // Jumlah (hours × UPJ × tier rates)
}
```

**Day Type Classification:**

| Day Type | Description | Tier 1 Rate | Tier 2 Rate | Tier 3 Rate | Tier 1 Boundary |
|----------|-------------|-------------|-------------|-------------|-----------------|
| `WORKDAY_LONG` | Mon-Thu, Sat | 1.5x | 2x | - | 1 hour |
| `WORKDAY_SHORT` | Friday | 1.5x | 2x | - | 1 hour |
| `SUNDAY` | Sunday | 2x | 3x | 4x | 5/7 hours |
| `HOLIDAY_REGULAR` | Non-religious holiday | 2x | 3x | 4x | 5/7 hours |
| `HOLIDAY_RELIGIOUS` | Religious holiday | 3x | 4x | 4x | 5/7 hours |

**Common TaskCode Patterns:**

| TaskCode | TaskDesc | Category |
|----------|----------|----------|
| `GA9115` | (Associated with PPH) | Tax |
| `GA9112` | (Associated with SPSI) | Union |
| `PANEN` | Panen Manual | Harvest |
| `PUPUK` | Aplikasi Pupuk | Fertilizer |
| `SEMprot` | Penyemprotan | Spraying |
| `ROGNU` | Rogaming | Weeding |

**Note:** TaskCode bervariasi tergantung pekerjaan overtime yang dilakukan. Gunakan endpoint `/payroll/report/division-raw-tree` untuk mendapatkan data aktual.

---

### Tunjangan (Allowances) - Bukan Premi

Tunjangan adalah komponen Gaji Pokok, bukan premi:

| DocDesc Pattern | Normalized Key | Description |
|-----------------|----------------|-------------|
| `TUNJANGAN JABATAN` | `tunjangan_jabatan` | Jabatan allowance |
| `TUNJANGAN MASA KERJA` | `tunjangan_masa_kerja` | Masa kerja allowance |
| `TUNJANGAN BERAS` | `tunjangan_beras` | Rice allowance |
| `LEMBUR` | `lembur_jumlah` | Overtime (from PR_ADTRANS) |

**AUTO_BUFFER Seeder Menggenerate:**
- `AUTO TUNJANGAN JABATAN` → dari `tunjangan jabatan`
- `AUTO MASA KERJA` → dari `masa kerja`
- `AUTO SPSI` → dari `potongan spsi` (Rp 4,000)

---

### TaskCode Reference (Payroll Components) - ACTUAL DATA

Data actual dari database `PR_TASKCODE` dan `PR_ADTRANS`:

#### TaskCode untuk Cuti (Leave) - GA912x Series

| TaskCode Prefix | Leave Type | TaskDesc |
|----------------|------------|----------|
| `GA9129%` | Cuti Tahunan | `(AL) PERSONNEL ANNUAL LEAVE` |
| `GA9126%` | Cuti Sakit/Haid | `(AL) PERSONNEL SICK LEAVE` |
| `GA9127%` | Cuti Minggu | - |
| `GA9128%` | Cuti Nasional | `(AL) PERSONNEL TUNJANGAN JABATAN` |

#### TaskCode untuk Accounting/Tunjangan (Dari PR_TASKCODE)

| TaskCode | TaskDesc | Usage |
|----------|----------|-------|
| `GA9110` | `PERSONNEL - SALARIES & WAGES - LOCAL` | Gaji Pokok |
| `GA9111` | `BIAYA RAPEL` | Rapel |
| `GA9116` | `(AL)Tunjangan Hari Raya` | THR |
| `GA9118` | `RAWAT GUEST HOUSE` | Guest house |
| `GA9126` | `(AL) PERSONNEL SICK LEAVE` | Cuti Sakit |
| `GA9128` | `(AL) PERSONNEL TUNJANGAN JABATAN` | Tunjangan Jabatan |
| `GA9129` | `(AL) PERSONNEL ANNUAL LEAVE` | Cuti Tahunan |
| `GA9228` | `SUNDRY EXPENSES` | Expenses |
| `GA9234` | `UPKEEP OF BUILDINGS` | Building maintenance |
| `GA9237` | `UPKEEP OF MOTOR VEHICLE` | Vehicle maintenance |
| `AL0013` | `MONTHLY WAGES` | Gaji Bulanan |
| `AL0014` | `(AL) TUNJANGAN BERAS` | Tunjangan Beras |
| `AL0019` | `(AL) TUNJANGAN LEMBUR` | Tunjangan Lembur |
| `ALBPJS` | `(ME) BPJS - WORKERS (EMPLOYER)` | BPJS |
| `ALJHT` | `(ME) JHT - WORKERS (EMPLOYER)` | JHT |
| `ALJK` | `(ME) JK - WORKERS (EMPLOYER)` | JK |
| `ALJKK` | `(ME) JKK - WORKERS (EMPLOYER)` | JKK |
| `ALJP` | `(ME) JP - WORKERS (EMPLOYER)` | JP |

---

### DocDesc ACTUAL dari Database (PR_ADTRANS + PR_ADTRANS_ARC)

**Query untuk melihat semua DocDesc:**
```bash
# Menggunakan SQL Gateway API via proxy
curl -X POST "http://10.0.0.110:3001/query" \
  -H "Content-Type: application/json" \
  -H "x-api-key: 2a993486e7a448474de66bfaea4adba7a99784defbcaba420e7f906176b94df6" \
  -d '{"sql": "SELECT DISTINCT DocDesc FROM PR_ADTRANS_ARC ORDER BY DocDesc", "server": "SERVER_PROFILE_2", "database": "db_ptrj"}'
```

#### DocDesc untuk PREMI (Actual Variations)

| DocDesc Pattern | Normalized Key | Notes |
|----------------|----------------|-------|
| `PREMI HARVESTING` | dynamic | Harvesting premium |
| `PREMI TUNJANGAN HARVESTING` | dynamic | Tunjangan harvesting premium |
| `TUNJANGAN PREMI HARVESTING` | dynamic | Tunjangan harvesting |
| `PREMI PANEN` | dynamic | Panen premium |
| `Premi Harvesting` | dynamic | (various spellings) |
| `PREMI BRONDOL` | `premi_brondol` | Brondol premium |
| `Premi Brondolan` | `premi_brondol` | (various spellings) |
| `PREMI PRUNING` | `premi_pruning` | Pruning premium |
| `Premi Prunning` | `premi_pruning` | (various spellings) |
| `PREMI INSENTIF` | `premi_insentif` | Insentif premium |
| `Premi Insentif Panen` | `premi_insentif` | (various spellings) |
| `PREMI KINERJA` | `premi_kinerja` | Kinerja premium |
| `PREMI ANGKUT TBS` | dynamic | Angkut TBS premium |
| `PREMI ANGKUT PUPUK` | dynamic | Angkut pupuk premium |
| `PREMI TRANSPORT` | dynamic | Transport premium |
| `PREMI TBS` | dynamic | TBS premium |
| `PREMI CUCI UNIT` | dynamic | Cuci unit premium |
| `PREMI GENSET` | dynamic | Genset premium |
| `PREMI JAGA GENSET` | dynamic | Jaga genset premium |
| `PREMI OPERATOR` | dynamic | Operator premium |
| `PREMI LOADING` | dynamic | Loading premium |
| `PREMI RITASE` | dynamic | Ritase premium |
| `PREMI RETASE` | dynamic | Retase premium |
| `PREMI SIRTU` | dynamic | Sirtu premium |
| `PREMI BENGKEL` | dynamic | Bengkel premium |
| `PREMI POKOK TINGGI` | dynamic | Pokok tinggi premium |
| `PREMI MANDOR PANEN` | dynamic | Mandor panen premium |
| `PREMI KRANI PANEN` | dynamic | Krani panen premium |
| `PREMI TANGGUNG JAWAB` | dynamic | Tanggung jawab premium |
| `TUNJANGAN PREMI` | dynamic | Tunjangan premium |
| `TUNJANGAN PREMI PRUNING` | dynamic | Tunjangan pruning |
| `TUNJANGAN PREMI PUPUK` | dynamic | Tunjangan pupuk |
| `TUNJANGAN PREMI TRANSPORT` | dynamic | Tunjangan transport |
| `TUNJANGAN PREMI BRONDOL` | dynamic | Tunjangan brondol |
| `TUNJANGAN PREMI KINERJA` | dynamic | Tunjangan kinerja |
| `TUNJANGAN PREMI BIBIT` | dynamic | Bibit premium |
| `TUNJANGAN PREMI BLOWER` | dynamic | Blower premium |
| `TUNJANGAN PREMI ANGKUT TBS` | dynamic | Angkut TBS |
| `TUNJANGAN PREMI ANGKUT PUPUK` | dynamic | Angkut pupuk |
| `TUNJANGAN PREMI BIG BUCKET` | dynamic | Big bucket |
| `(AL) TUNJANGAN PREMI ((PM) HARVESTING LABOUR - HARVESTING)` | dynamic | Harvesting labour |

#### DocDesc untuk POTONGAN (Actual Variations)

| DocDesc Pattern | Normalized Key | Notes |
|----------------|----------------|-------|
| `PPH21` | `pot_pph21` | PPh21 |
| `PPH 21` | `pot_pph21` | PPh21 (with space) |
| `POTONGAN PPH21` | `pot_pph21` | Potongan PPh21 |
| `POTONGAN PPH 21` | `pot_pph21` | Potongan PPh21 (with space) |
| `POTONGAN SPSI` | `pot_spsi` | Potongan SPSI |
| `SPSI` | `pot_spsi` | SPSI |
| `POTONGAN PREMI` | `pot_premi` | Potongan premi |
| `POTONGAN HARVESTING` | `pot_premi` | Potongan harvesting |
| `POTONGAN BRONDOL` | `pot_brondol` | Potongan brondol |
| `POTONGAN BERAS` | `pot_beras` | Potongan beras |
| `POTONGAN MASA KERJA` | `pot_masa_kerja` | Potongan masa kerja |
| `POTONGAN GAJI` | `pot_gaji` | Potongan gaji |
| `POTONGAN TIKET` | `pot_tiket` | Potongan tiket |
| `POTONGAN PINJAMAN` | `pot_pinjaman` | Potongan pinjaman |
| `POTONGAN HUTANG` | `pot_hutang` | Potongan hutang |
| `POTONGAN IURAN SPSI` | `pot_spsi` | Iuran SPSI |
| `POTONGAN  SPSI` | `pot_spsi` | (extra space) |
| `POTONGAN ALAT` | `pot_alat` | Potongan alat |
| `POTONGAN BIAYA TIKET` | `pot_tiket` | Biaya tiket |
| `POTONGAN BPJS` | `pot_bpjs` | Potongan BPJS |
| `POTONGAN PENSIUN` | `pot_pensiun` | Potongan pensiun |
| `POTONGAN LEBIH HK` | dynamic | Lebih HK |
| `POTONGAN KOREKSI` | `pot_koreksi` | Koreksi |
| `POTONGAN EXGRATIA PP21` | dynamic | Ex-gratia |
| `POTONGAN EXGRATIA PPH21` | dynamic | Ex-gratia PPh21 |

#### TaskCode untuk LEMBUR (Overtime) - OT=1 Transactions

Dari `PR_TASKREGLN WHERE OT = 1`, TaskCode yang paling sering digunakan:

| TaskCode | TaskDesc | Division | Usage Count |
|----------|----------|---------|-------------|
| `PT2340ARC` | `(PM) DRIVER` | ARC | 295 |
| `PT2341ARC` | `(PM) HELPER` | ARC | 243 |
| `PT2340P1A` | `(PM) DRIVER` | P1A | 156 |
| `PT2340P2A` | `(PM) DRIVER` | P2A | 132 |
| `PT2340AB1` | `(PM) DRIVER` | AB1 | 126 |
| `PT2341P2A` | `(PM) HELPER` | P2A | 120 |
| `PM2301ARC` | `(PM) LOADING` | ARC | 111 |
| `PT2341AB1` | `(PM) HELPER` | AB1 | 98 |
| `PT2340P2B` | `(PM) DRIVER` | P2B | 97 |
| `PT2340ARA` | `(PM) DRIVER` | ARA | 96 |
| `PT2341P2B` | `(PM) HELPER` | P2B | 90 |
| `GA9234P1A` | `UPKEEP OF BUILDINGS` | P1A | 88 |
| `PT2340AB2` | `(PM) DRIVER` | AB2 | 82 |
| `PT2340DME` | `(PM) DRIVER` | DME | 113 |
| `GA9110AB2` | `PERSONNEL - SALARIES & WAGES - LOCAL` | AB2 | 60 |

**Pattern TaskCode Lembur:**
- `PT2340` + Division = DRIVER (e.g., `PT2340ARC`, `PT2340P1A`)
- `PT2341` + Division = HELPER (e.g., `PT2341ARC`, `PT2341P1A`)
- `PM2301` + Division = LOADING (e.g., `PM2301ARC`, `PM2301ARA`)
- `GA9234` + Division = UPKEEP OF BUILDINGS

#### Special TaskCode Patterns

| TaskCode | TaskDesc | Notes |
|---------|---------|-------|
| `AL3CL3310` | `ACCRUALS-CHECKROLL` | Premi PPH (Tax) |
| `CL3310` | `ACCRUALS - CHECKROLL` | Accruals checkroll |
| `DE0004` | `(DE) POTONGAN PREMI` | Potongan premi |
| `DE0005` | `(DE) POTONGAN SPSI` | Potongan SPSI |
| `DEBPJS` | `(DE) BPJS - WORKERS (EMPLOYEE)` | BPJS employee |
| `DEJHT` | `(DE) JHT - WORKERS (EMPLOYEE)` | JHT employee |
| `DEJP` | `(DE) JP - WORKERS (EMPLOYEE)` | JP employee |
| `DEPH21` | `(DE) POTONGAN PPH21` | PPh21 employee |

---

### Kategori Premi dari Database (Summary)

**Dari `PR_ADTRANS_ARC` - Distinct DocDesc containing PREMI:**

| Category | Example DocDesc |
|----------|----------------|
| **HARVESTING** | `PREMI HARVESTING`, `PREMI TUNJANGAN HARVESTING`, `TUNJANGAN PREMI HARVESTING`, `Premi Harvesting`, `PREMI HARVESTING LABOUR`, `PREMI HERVESTING` |
| **BRONDOL** | `PREMI BRONDOL`, `Premi borondolan`, `PREMI BRONDOLAN`, `PREMI BRONDOL PLASMA...` |
| **PRUNING** | `PREMI PRUNING`, `Premi Prunning`, `PRUNING`, `PRUNIG`, `TUNJANGAN PREMI PRUNING` |
| **INSENTIF/PANEN** | `PREMI INSENTIF`, `Premi Insentif Panen`, `INSENTIF PREMI`, `PREMI ISENTIF`, `PREMI INCENTIVE PANEN`, `Premi Iisentif Panen` |
| **KINERJA** | `PREMI KINERJA`, `Premi kinerja`, `TUNJANGAN PREMI KINERJA` |
| **ANGKUT** | `PREMI ANGKUT TBS`, `PREMI ANGKUT PUPUK`, `TUNJANGAN PREMI ANGKUT TBS`, `TUNJANGAN PREMI ANGKUT PUPUK`, `PREMI ANGKUT PC` |
| **TBS** | `PREMI TBS`, `PREMI TBS ARE A`, `PREMI TBS PLASMA`, `PREMI TBS INTI` |
| **TRANSPORT** | `PREMI TRANSPORT`, `PREMI TRANSPORTASI`, `TUNJANGAN PREMI TRANSPORT` |
| **RITASE** | `PREMI RITASE`, `PREMI RETASE`, `TUNJANGAN PREMI RITASE` |
| **LOADING** | `PREMI LOADING`, `PREMI LOADING PUPUK` |
| **JABATAN** | `PREMI JABATAN`, `TUNJANGAN PREMI JABATAN` |
| **MANDOR/KERANI** | `PREMI MANDOR PANEN`, `PREMI KRANI PANEN`, `Premi Insentif Mandor` |
| **LAINNYA** | `PREMI GENSET`, `PREMI JAGA GENSET`, `PREMI OPERATOR`, `PREMI BENGKEL`, `PREMI BAG`, `PREMI CUCI UNIT` |

---

### Kategori Potongan dari Database (Summary)

| Category | Example DocDesc |
|----------|----------------|
| **PPH21** | `PPH21`, `PPH 21`, `PPH-21`, `PPH12`, `POTONGAN PPH21`, `POTONGAN PPH 21`, `POTONGAN PPH21 THR`, `POTONGAN PPH21 EXGRATIA` |
| **SPSI** | `SPSI`, `POTONGAN SPSI`, `POTONGAN IURAN SPSI`, `(DE) POTONGAN SPSI` |
| **PREMI** | `POTONGAN PREMI`, `POTONGAN PREMI HARVESTING`, `POTONGAN PREMI BRONDOL`, `POTONGAN PREMI TBS`, `POTONGAN PREMI ANGKUT` |
| **BRONDOL** | `POTONGAN BRONDOL`, `POTONGAN BRONDOL KONTANAN`, `POTONGAN BRONDOLAN KONTANAN` |
| **BERAS** | `POTONGAN BERAS`, `POTONGAN DUIT BERAS` |
| **GAJI** | `POTONGAN GAJI`, `POTONGAN GAJI 75%`, `POTONGAN 75% DARI GAJI` |
| **TIKET** | `POTONGAN TIKET`, `POTONGAN BIAYA TIKET`, `POTONGAN UANG TIKET` |
| **PINJAMAN** | `POTONGAN PINJAMAN`, `POTONGAN PINJAMAM`, `POTONGAN PINJAMAN UANG` |
| **KOREKSI** | `POTONGAN KOREKSI`, `KOREKSI`, `KOREKSI PANEN`, `KOREKSI BRONDOL`, `KOREKSI INTI` |
| **LEMBUR** | `POTONGAN LEMBUR`, `POTONGAN OT`, `KEKURANGAN LEMBUR`, `PENGEMBALIAN LEMBUR` |
| **LAINNYA** | `POTONGAN ALAT`, `POTONGAN ALAT KERJA`, `POTONGAN CUTI SAKIT`, `POTONGAN MASA KERJA`, `POTONGAN CS BERKEPANJANGAN` |

---

### Query Reference untuk Automation

**Get all unique DocDesc dari archive:**
```sql
SELECT DISTINCT DocDesc 
FROM PR_ADTRANS_ARC 
WHERE DocDesc IS NOT NULL 
  AND DocDesc != ''
ORDER BY DocDesc
```

**Get all TaskCode yang digunakan untuk Lembur (OT=1):**
```sql
SELECT DISTINCT tr.TaskCode, tc.TaskDesc, COUNT(*) as cnt 
FROM PR_TASKREGLN tr 
LEFT JOIN PR_TASKCODE tc ON tr.TaskCode = tc.TaskCode 
WHERE tr.OT = 1 
  AND tr.TaskCode IS NOT NULL 
GROUP BY tr.TaskCode, tc.TaskDesc 
ORDER BY cnt DESC
```

**Get all TaskCode (unique):**
```sql
SELECT TaskCode, TaskDesc 
FROM PR_TASKCODE 
WHERE TaskCode NOT LIKE '%AB1%' 
  AND TaskCode NOT LIKE '%AB2%' 
  AND TaskCode NOT LIKE '%P1A%' 
  AND TaskCode NOT LIKE '%P1B%' 
  AND TaskCode NOT LIKE '%P2A%' 
  AND TaskCode NOT LIKE '%P2B%' 
  AND TaskCode NOT LIKE '%ARC%' 
  AND TaskCode NOT LIKE '%ARA%' 
  AND TaskCode NOT LIKE '%DME%' 
  AND TaskCode NOT LIKE '%IJL%' 
ORDER BY TaskCode
```

---

## Query Reference untuk Automation

**Get all unique DocDesc dari archive:**
```sql
SELECT DISTINCT DocDesc 
FROM PR_ADTRANS_ARC 
WHERE DocDesc IS NOT NULL 
  AND DocDesc != ''
ORDER BY DocDesc
```

**Get all TaskCode yang digunakan untuk Lembur (OT=1):**
```sql
SELECT DISTINCT tr.TaskCode, tc.TaskDesc, COUNT(*) as cnt 
FROM PR_TASKREGLN tr 
LEFT JOIN PR_TASKCODE tc ON tr.TaskCode = tc.TaskCode 
WHERE tr.OT = 1 
  AND tr.TaskCode IS NOT NULL 
GROUP BY tr.TaskCode, tc.TaskDesc 
ORDER BY cnt DESC
```

**Get semua adjustment untuk employee tertentu:**
```sql
SELECT emp_code, gang_code, division_code, adjustment_name, adjustment_type, amount
FROM payroll_manual_adjustments
WHERE period_month = {month}
  AND period_year = {year}
  AND emp_code = '{emp_code}'
```

**Get adjustment via SQL Gateway (direct database - WORKAROUND jika API auth tidak bekerja):**
```bash
curl -X POST "http://10.0.0.110:8001/v1/query" \
  -H "Content-Type: application/json" \
  -H "x-api-key: 2a993486e7a448474de66bfaea4adba7a99784defbcaba420e7f906176b94df6" \
  -d '{
    "sql": "SELECT emp_code, gang_code, division_code, adjustment_name, adjustment_type, amount FROM payroll_manual_adjustments WHERE period_month = 4 AND period_year = 2026 AND emp_code = '\''B0745'\''",
    "server": "SERVER_PROFILE_1",
    "database": "extend_db_ptrj"
  }'
```

**Database Configuration untuk Manual Adjustments:**
- **Table:** `payroll_manual_adjustments`
- **Database:** `extend_db_ptrj`
- **Profile:** `SERVER_PROFILE_1`
- **API Endpoint:** SQL Gateway at `10.0.0.110:8001`

---

### Catatan Penting untuk Automation

1. **Spelling Variations**: DocDesc memiliki banyak variasi spelling (e.g., `PREMI HARVESTING` vs `Premi Harvesting` vs `PREMI HERVESTING`). Gunakan case-insensitive matching.

2. **Division Suffix**: Banyak TaskCode memiliki suffix divisi (e.g., `PT2340ARC`, `PT2340P1A`, `PT2340AB1`). Base code adalah `PT2340`.

3. **Prefixes**: Ada berbagai prefix seperti `(AL)`, `(PM)`, `(PI)`, `(PN)`, `(DE)`, `(ME)` yang menunjukkan jenis transaksi.

4. **ACCRUALS-CHECKROLL**: TaskCode `AL3CL3310` atau `CL3310` dengan TaskDesc `ACCRUALS-CHECKROLL` digunakan untuk Premi PPH (tax-related premium).

5. **Normalisasi**: Untuk automation, selalu normalisasi DocDesc ke lowercase dan hapus extra spaces sebelum matching.

Dari analisis code, berikut TaskCode yang digunakan dalam payroll system:

#### TaskCode untuk Cuti (Leave) - GA912x Series

| TaskCode Prefix | Leave Type | Description |
|----------------|------------|-------------|
| `GA9129%` | Cuti Tahunan | Annual leave |
| `GA9126%` | Cuti Sakit/Haid | Sick leave / menstrual leave |
| `GA9127%` | Cuti Minggu | Sunday leave |
| `GA9128%` | Cuti Nasional | National holiday leave |

#### TaskCode untuk Accounting/Tunjangan

| TaskCode | Description | Usage |
|----------|-------------|-------|
| `GA9110` | Gaji Pokok | Base salary account |
| `GA9112` | Tunjangan Lembur | Overtime allowance account |
| `GA9115` | Premi PPH | PPH Premium (ACCRUALS-CHECKROLL) |
| `GA9116` | THR | Thr年终奖 |
| `GA9117` | Bonus | Bonus account |
| `GA9120` | BPJS Kesehatan Majikan | Health insurance employer |
| `GA9121` | Astek JHT Majikan | JHT insurance employer |
| `GA9128` | Tunjangan Jabatan | Position allowance |
| `GA9131` | Tunjangan Beras | Rice allowance |
| `AL0013` | Gaji Pokok (Alt) | Alternative base salary code |
| `AL0014` | Tunjangan Beras (Alt) | Alternative rice allowance |
| `AL0019` | Tunjangan Lembur (Alt) | Alternative overtime |
| `ALBPJS` | BPJS (Alt) | Alternative BPJS code |
| `ALASTK` | Astek (Alt) | Alternative labor insurance |
| `PT9129` | Masa Kerja | Years of service |

#### TaskCode untuk PREMI (DocDesc Pattern)

**Dari PR_ADTRANS DocDesc:**

| DocDesc Pattern | TaskCode | Normalized Key | Notes |
|----------------|----------|----------------|-------|
| `PREMI PANEN AL` | - | `premi_panen_al` | Air Larangan harvest premium |
| `PREMI PANEN BRONDOL` | - | `premi_brondol` | Brondol loose fruit premium |
| `PREMI PRUNING` | - | `premi_pruning` | Pruning premium |
| `PREMI INSENTIF` | - | `premi_insentif` | Insentif Panen premium |
| `PREMI KINERJA` | - | `premi_kinerja` | Kinerja bonus premium |
| `PREMI PPH` | `GA9115` | `premi_pph` | Dihitung terpisah, ditambahkan ke upah_bersih |
| `ACCRUALS-CHECKROLL` | `GA9115` | - | TaskDesc untuk Premi PPH |

#### TaskCode untuk POTONGAN (Deductions)

| DocDesc Pattern | TaskCode | Normalized Key | Notes |
|----------------|----------|----------------|-------|
| `PPH21` | - | `pot_pph21` | PPh21 tax (via TER calculation) |
| `BPJS KESEHATAN` | - | `pot_bpjs_kesehatan` | Health insurance |
| `BPJS PENSIUN` | - | `pot_bpjs_pensiun` | Pension insurance |
| `SPSI` | `GA9112` | `pot_spsi` | Union dues (Rp 4,000/bulan) |
| `KOREKSI` | - | `pot_koreksi` | Correction (DocDesc LIKE 'POT%') |
| `PINJAMAN KOPERASI` | - | `pot_pinjaman` | Loan deduction |

#### TaskCode untuk LEMBUR (Overtime)

**Sumber:** `PR_TASKREGLN` dengan `OT = 1` + `PR_TASKCODE`

Lembur TaskCode bervariasi tergantung pekerjaan overtime. Contoh:

| TaskCode | TaskDesc | Category |
|----------|----------|----------|
| - | PANEN MANUAL | Harvest overtime |
| - | PUPUK | Fertilizer application overtime |
| - | SEMprot | Spraying overtime |
| - | ROGNU | Rogaming/weeding overtime |

**Note:** TaskCode dan TaskDesc untuk lembur dynamically berasal dari data actual PR_TASKCODE per transaksi overtime. Untuk melihat task code/task desc yang actual, gunakan endpoint:

```bash
# Ambil data payroll dengan overtime breakdown
curl -s "http://localhost:8002/payroll/report/division-raw-tree?month=4&year=2026&division_code=AB1" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.gangs[].employees[].lembur_records[] | {task_code, task_desc}'
```

---

### Flow Perhitungan Payroll

```
1. Gaji Pokok = hari_kerja × pay_rate

2. Total Tunjangan = beras_jumlah + jabatan_jumlah + masa_kerja_jumlah + lembur_jumlah

3. Total Premi = premi_brondol + SUM(dynamic_premi)

4. Upah Kotor = gaji_pokok_aktual + total_tunjangan + total_premi

5. Jumlah Upah Kotor = upah_kotor - pot_koreksi + pendapatan_lainnya
   (koreksi di-ADD untuk tampilan saja)

6. Penghasilan Bruto = jumlah_upah_kotor + astek_m + bpjs_m
   (koreksi & lainnya adalah bagian penghasilan kena pajak)

7. Total Potongan = astek + bpjs_kes + bpjs_pensiun + spsi + pph21 + other + pendapatan_lainnya
   (koreksi TIDAK masuk - sudah di jumlah_upah_kotor)
   (pendapatan_lainnya WAJIB masuk untuk offset)

8. Upah Bersih = jumlah_upah_kotor - total_potongan + premi_pph
   (premi_pph = ADDITION, bukan potongan)
```

---

### Kategori Premi dan Potongan Reference

#### Premi Categories

| Category | DocDesc Pattern | Target Column |
|----------|----------------|---------------|
| PREMI_PANEN_AL | `%PREMI%PANEN%AL%` atau `%PREMI%AL%` | `premi_panen_al` |
| PREMI_PANEN | `%PREMI%PANEN%` | dynamic |
| PREMI_KINERJA | `%PREMI%KINERJA%` | `premi_kinerja` |
| PREMI_BRONDOL | `%PREMI%BRONDOL%` | `premi_brondol` |
| PREMI_INSENTIF | `%PREMI%INSENTIF%` | `premi_insentif` |
| PREMI_LAIN | `%PREMI%` (catchall) | dynamic column |

#### Potongan Categories

| Category | DocDesc Pattern | Target Column |
|----------|----------------|---------------|
| POTONGAN_PPH21 | `%PPH%` AND NOT `%PREMI%` | `pot_pph21` |
| POTONGAN_BPJS_KESEHATAN | `%BPJS%KESEHATAN%` | `pot_bpjs_kesehatan` |
| POTONGAN_BPJS_PENSIUN | `%BPJS%PENSIUN%` | `pot_bpjs_pensiun` |
| POTONGAN_SPSI | `%SPSI%` | `pot_spsi` |
| POTONGAN_KOREKSI | `%KOREKSI%` atau `POT%` | `pot_koreksi` |
| POTONGAN_PINJAMAN | `%PINJAM%` | `pot_pinjaman` |
| POTONGAN_LAIN | `POT%` (catchall) | dynamic column |

---

## CLI Helper Script

Untuk testing cepat dari command line, bisa pakai script `curl_test.ts` yang ada di `_dev_utils`:

```bash
cd backend
bun run src/scripts/curl_test.ts
```

Atau buat script bash sederhana:

```bash
#!/bin/bash
API_KEY="88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"
BASE_URL="http://localhost:8002"

# Get adjustments
curl -s -X GET "${BASE_URL}/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&gang_code=H1H" \
  -H "X-API-Key: ${API_KEY}" | jq .

# Save adjustment
curl -s -X POST "${BASE_URL}/payroll/manual-adjustment/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{"period_month":4,"period_year":2026,"emp_code":"C0001","nik":"1902050504860001","emp_name":"BUDI TEST","gang_code":"H1H","adjustment_type":"PREMI","adjustment_name":"BONUS LEBARAN","amount":500000}' | jq .
```


### 4. Verifikasi Data Langsung ke `db_ptrj` (`PR_ADTRANS`)

**Endpoint:** `POST /payroll/manual-adjustment/check-adtrans/by-api-key`  
**Access:** Protected, wajib menggunakan header `X-API-Key`.

Endpoint ini digunakan untuk mengecek nilai allowance/deduction/premi yang sudah benar-benar tersimpan di Plantware `db_ptrj`, bukan dari tabel manual adjustment di `extend_db_ptrj`. Gunakan endpoint ini ketika ingin memverifikasi employee tertentu pada periode tertentu, misalnya setelah sync/update Plantware untuk SPSI, tunjangan masa kerja, tunjangan jabatan, atau premi dynamic.

Endpoint membaca data melalui SQL Gateway/API query dengan koneksi database yang dipilih dari konfigurasi `.env`, lalu mengambil sumber berikut:

- `db_ptrj.dbo.PR_ADTRANS`
- `db_ptrj.dbo.PR_ADTRANS_ARC`
- `db_ptrj.dbo.PR_ADTRANSLN`
- `db_ptrj.dbo.PR_ADTRANSLN_ARC`

> **Penting — aturan periode:** query ini menggunakan `PhyMonth` dan `PhyYear`, bukan `AccMonth`/`AccYear`. `period_month` dikirim sebagai filter `PhyMonth`, dan `period_year` dikirim sebagai filter `PhyYear`. Field `PhyMonth` dan `PhyYear` adalah real month/year sesuai kalender.

#### Request Body

Cek berdasarkan list employee tertentu:

```json
{
  "period_month": 4,
  "period_year": 2026,
  "emp_codes": ["B0065", "B0070"],
  "filters": ["spsi", "masa kerja", "jabatan", "premi", "potongan"]
}
```

Cek langsung semua employee dalam satu divisi:

```json
{
  "period_month": 4,
  "period_year": 2026,
  "division_code": "P2A",
  "filters": ["spsi", "masa kerja", "jabatan"]
}
```

| Field | Type | Required | Keterangan |
|-------|------|----------|------------|
| `period_month` | number | Yes | Bulan kalender yang akan dicek. Dipakai sebagai `PhyMonth`. |
| `period_year` | number | Yes | Tahun kalender yang akan dicek. Dipakai sebagai `PhyYear`. |
| `emp_codes` | string[] | Conditional | List `EmpCode` yang akan dicek langsung ke `PR_ADTRANS` dan archive. Wajib jika `division_code` tidak dikirim. |
| `division_code` | string | Conditional | Filter semua employee dalam satu divisi berdasarkan `PR_ADTRANS.LocCode`. Bisa kirim kode Plantware 3 karakter seperti `P2A`, `AB1`, `ARA`, `ARC`, `DME`, `IJL`, atau alias seperti `PG2A`/`2A` yang akan dinormalisasi ke `P2A`. Wajib jika `emp_codes` kosong/tidak dikirim. |
| `filters` | string[] | Yes | List keyword komponen yang akan dicocokkan ke pola `DocDesc`. |

Kirim salah satu atau keduanya: `emp_codes` dan/atau `division_code`. Jika keduanya dikirim, scope query mencakup employee dalam `emp_codes` **atau** record dengan `LocCode = normalized division_code`.

Normalisasi `division_code` untuk `LocCode`:

| Input | Dipakai ke `PR_ADTRANS.LocCode` |
|-------|---------------------------------|
| `PG1A`, `1A`, `P1A` | `P1A` |
| `PG1B`, `1B`, `P1B` | `P1B` |
| `PG2A`, `2A`, `P2A` | `P2A` |
| `PG2B`, `2B`, `P2B` | `P2B` |
| `ARB1`, `AB1` | `AB1` |
| `ARB2`, `AB2` | `AB2` |
| `AREC`, `ARC` | `ARC` |
| `ARA`, `DME`, `IJL` | tetap sesuai input |

#### Mapping Filter ke `DocDesc`

| Input Filter | SQL Pattern ke `DocDesc` | Contoh Penggunaan |
|--------------|---------------------------|-------------------|
| `spsi` / `potongan spsi` | `%SPSI%` | Cek potongan SPSI. |
| `masa kerja` / `tunjangan masa kerja` | `%MASA%KERJA%` | Cek tunjangan masa kerja, termasuk `TUNJANGAN MASA KERJA`. |
| `jabatan` / `tunjangan jabatan` | `%JABATAN%` | Cek tunjangan jabatan. |
| `premi` | `%PREMI%`, `%INSENTIF%`, `%PANEN%`, `%KINERJA%`, `%RAWAT%`, `%PRUN%` | Cek premi dynamic. Keyword ini tidak menjadi kolom static. |
| `brondol` | `%BRONDOL%` | Brondol special/static: jumlahkan ke kolom `brondol` yang sudah ada. |
| `koreksi` | `%KOREKSI%` | Koreksi selalu masuk `potongan upah kotor` sebagai kolom dynamic. |
| `potongan` | `POT%`, `POTONGAN%` | Cek potongan umum dynamic; tidak mencakup static SPSI/PPH dan tidak double-count `koreksi` jika filter `koreksi` juga dikirim. |
| filter lain | `%FILTER%` | Cek premi/komponen dynamic berdasarkan keyword yang dikirim. |

#### Contoh cURL

```bash
API_KEY="your-api-key"
BASE_URL="http://localhost:8002"

# Cek employee tertentu
curl -s -X POST "${BASE_URL}/payroll/manual-adjustment/check-adtrans/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "emp_codes": ["B0065", "B0070"],
    "filters": ["spsi", "masa kerja", "jabatan", "premi"]
  }' | jq .

# Cek semua employee dalam divisi dan tampilkan ringkasan duplicate
curl -s -X POST "${BASE_URL}/payroll/manual-adjustment/check-adtrans/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "P2A",
    "filters": ["spsi", "masa kerja", "jabatan", "premi", "koreksi", "potongan"]
  }' | jq '.data.duplicate_report'
```

#### Success Response

Response berisi dua bagian utama:

- `data.totals`: hasil agregasi `SUM(Amount)` per `emp_code` untuk setiap filter yang diminta.
- `data.duplicate_report`: daftar employee + kategori yang memiliki lebih dari satu record `PR_ADTRANS` pada periode/scope yang sama.

```json
{
  "success": true,
  "message": "Adtrans check completed successfully",
  "data": {
    "totals": [
      {
        "emp_code": "B0065",
        "spsi": 4000,
        "masa kerja": 125000,
        "jabatan": 250000,
        "premi": 150000
      },
      {
        "emp_code": "B0070",
        "spsi": 0,
        "masa kerja": 0,
        "jabatan": 250000,
        "premi": 87500
      }
    ],
    "duplicate_report": {
      "duplicate_count": 1,
      "duplicates": [
        {
          "emp_code": "C0028",
          "emp_name": "ASBI AL GHIFARI ( YUNENGSIH",
          "category": "spsi",
          "record_count": 2,
          "keep_id": "674653",
          "keep_doc_id": "ADP2A26041438",
          "delete_ids": ["674398"],
          "delete_doc_ids": ["ADP2A26041177"],
          "records": [
            {
              "id": "674398",
              "doc_id": "ADP2A26041177",
              "doc_date": "2026-04-27",
              "doc_desc": "POTONGAN SPSI",
              "amount": 4000,
              "action": "DELETE_OLD"
            },
            {
              "id": "674653",
              "doc_id": "ADP2A26041438",
              "doc_date": "2026-04-27",
              "doc_desc": "POTONGAN SPSI",
              "amount": 4000,
              "action": "KEEP_NEWEST"
            }
          ]
        }
      ]
    }
  }
}
```

#### Duplicate Detection Rules

Duplicate dihitung per kombinasi:

```text
emp_code + normalized filter/category
```

Contoh: employee `C0028` dengan dua record `DocDesc` yang match `spsi` akan muncul sebagai satu item duplicate kategori `spsi`.

Aturan rekomendasi hapus:

- `keep_id` / `keep_doc_id`: record dengan `ID` paling besar, dianggap record terbaru yang dipertahankan.
- `delete_ids` / `delete_doc_ids`: record dengan `ID` lebih kecil, dianggap record lama yang disarankan dihapus.
- Endpoint ini hanya memberi rekomendasi; tidak menjalankan delete.

#### Catatan Penggunaan

- Endpoint ini hanya untuk **membaca dan memverifikasi** data real di `db_ptrj`.
- Endpoint ini **tidak mengupdate** manual adjustment, remarks, atau data di `extend_db_ptrj`.
- Jika hasil filter bernilai `0`, artinya tidak ada `DocDesc` yang match untuk employee/filter tersebut pada `PhyMonth` dan `PhyYear` yang dikirim.
- Untuk cek satu divisi penuh, cukup kirim `division_code` tanpa `emp_codes`; endpoint akan memakai `PR_ADTRANS.LocCode` sebagai scope.
- `duplicate_report` cocok untuk kasus auto buffer/Plantware input yang seharusnya satu record per employee per kategori, misalnya potongan SPSI double di Divisi P2A.
- Untuk mengecek data yang baru di-update oleh user tertentu seperti `UpdatedBy = 'adm075'`, gunakan query investigasi terpisah; endpoint ini saat ini fokus ke pengecekan berdasarkan `EmpCode`/`division_code`, periode, dan filter `DocDesc`.

---

### 4. POST `/payroll/manual-adjustment/compare-adtrans/by-api-key`

**Komparasi langsung** antara nilai PR_ADTRANS di `db_ptrj` (source of truth) dan nilai `payroll_manual_adjustments` di `extend_db_ptrj`. Menampilkan per-employee per-category apakah nilai sudah **MATCH**, **MISMATCH**, atau **MISSING** (tidak ada di extend_db).

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `period_month` | number | ✅ | Bulan (1-12) |
| `period_year` | number | ✅ | Tahun |
| `division_code` | string | ✅ | Kode divisi (e.g. `AB1`, `PG2A`) |
| `filters` | string[] | ❌ | Kategori filter (default: `['spsi', 'masa kerja', 'jabatan', 'premi', 'koreksi', 'potongan']`) |

**Example:**

```bash
curl -X POST "http://localhost:8002/payroll/manual-adjustment/compare-adtrans/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "AB1",
    "filters": ["spsi", "masa kerja", "jabatan", "premi", "koreksi", "potongan"]
  }'
```

**Response:**

```json
{
  "success": true,
  "message": "Comparison completed successfully",
  "data": {
    "division": "AB1",
    "period_month": 4,
    "period_year": 2026,
    "compared_categories": ["spsi", "masa kerja", "jabatan", "premi", "koreksi", "potongan"],
    "total_employees": 25,
    "match_count": 60,
    "mismatch_count": 5,
    "missing_in_adjustments": 10,
    "comparisons": [
      {
        "emp_code": "G0007",
        "category": "spsi",
        "adjustment_name": "AUTO SPSI",
        "source_amount": 4000,
        "stored_amount": 4000,
        "diff": 0,
        "status": "MATCH",
        "gang_code": "G1H",
        "remarks": "AUTO SPSI | potongan spsi | 4000 | sync:SYNC | match:MATCH"
      },
      {
        "emp_code": "G0010",
        "category": "jabatan",
        "adjustment_name": "AUTO TUNJANGAN JABATAN",
        "source_amount": 150000,
        "stored_amount": 0,
        "diff": 150000,
        "status": "MISMATCH",
        "gang_code": "G1H",
        "remarks": "AUTO TUNJANGAN JABATAN | tunjangan jabatan | 0 | sync:MISS | match:MISMATCH"
      },
      {
        "emp_code": "G0015",
        "category": "masa kerja",
        "adjustment_name": "AUTO MASA KERJA",
        "source_amount": 25000,
        "stored_amount": null,
        "diff": null,
        "status": "MISSING",
        "gang_code": null,
        "remarks": null
      }
    ]
  }
}
```

**Comparison Status:**

| Status | Description | Insight yang diberikan |
|--------|-------------|------------------------|
| `MATCH` | Nilai di `db_ptrj` sama dengan `extend_db_ptrj` (toleransi ≤ 0.01) | Data manual adjustment sudah sinkron dengan Plantware. |
| `MISMATCH` | Nilai berbeda antara `db_ptrj` dan `extend_db_ptrj` | Ada record di kedua sisi, tetapi nominal tidak sama. Lihat `source_amount`, `stored_amount`, dan `diff`. |
| `MISSING` | Tidak ada record di `extend_db_ptrj` untuk employee+category ini | Plantware punya nilai, tetapi manual adjustment belum punya record. Ini kandidat untuk dibuat/sync dari `db_ptrj`. |

**Cara membaca detail comparison:**

| Field | Makna |
|-------|-------|
| `emp_code` | Selalu EmpCode PTRJ letter dari `db_ptrj`, misalnya `A0001`, `B0745`. |
| `category` | Kategori hasil mapping `DocDesc`: `spsi`, `masa kerja`, `jabatan`, `premi`, `koreksi`, atau `potongan`. |
| `adjustment_name` | Nama record yang dicari/dibandingkan di `payroll_manual_adjustments`. Untuk premi/potongan manual, mengikuti `adjustment_name` dari extend DB jika ada. |
| `source_amount` / `db_ptrj_amount` | Total nominal dari `db_ptrj.PR_ADTRANS` + `PR_ADTRANS_ARC`. |
| `stored_amount` / `extend_db_ptrj_amount` | Nominal di `extend_db_ptrj.payroll_manual_adjustments`; `null` berarti missing. |
| `diff` | `source_amount - stored_amount`; `null` untuk status `MISSING`. |
| `status` | `MATCH`, `MISMATCH`, atau `MISSING`. |
| `db_ptrj_doc_desc_details` | Detail baris pembentuk nilai source dari Plantware: `doc_desc`, `doc_id`, dan `amount`. Dipakai untuk tahu nilai `db_ptrj` berasal dari DocDesc apa saja. |
| `extend_db_ptrj_remarks` | Remarks/catatan dari record manual adjustment di `extend_db_ptrj`. |
| `gang_code` | Gang dari record manual adjustment jika tersedia. |
| `remarks` | Alias lama dari `extend_db_ptrj_remarks` untuk kompatibilitas response. |

**Contoh insight dari response compare:**

```bash
# Semua data Plantware yang belum ada di manual adjustment
jq '.data.comparisons[] | select(.status == "MISSING")'

# Ringkasan jumlah masalah per kategori
jq '.data.comparisons
  | map(select(.status != "MATCH"))
  | group_by(.category)
  | map({category: .[0].category, count: length, statuses: (group_by(.status) | map({status: .[0].status, count: length}))})'

# Selisih nominal terbesar antara db_ptrj dan extend_db_ptrj
jq '.data.comparisons
  | map(select(.status == "MISMATCH"))
  | sort_by((.diff | if . < 0 then -. else . end))
  | reverse
  | .[0:20]'

# Lihat detail DocDesc db_ptrj dan remarks extend_db_ptrj untuk data yang beda
jq '.data.comparisons[]
  | select(.status != "MATCH")
  | {emp_code, category, db_ptrj_amount, extend_db_ptrj_amount, diff, db_ptrj_doc_desc_details, extend_db_ptrj_remarks}'
```

**Category → Adjustment Name Mapping:**

| ADTRANS Category | Adjustment Name |
|-----------------|-----------------|
| `spsi` | `AUTO SPSI` |
| `masa kerja` | `AUTO MASA KERJA` |
| `jabatan` | `AUTO TUNJANGAN JABATAN` |
| `premi` | `adjustment_type = 'PREMI'`, nama sesuai `adjustment_name` |
| `koreksi` | `adjustment_type = 'POTONGAN_KOTOR'` dan `adjustment_name` mengandung `KOREKSI` |
| `potongan` | `adjustment_type = 'POTONGAN_KOTOR'` selain `KOREKSI` |

---

### 5. POST `/payroll/manual-adjustment/reverse-compare-adtrans/by-api-key`

**Reverse komparasi** dari `payroll_manual_adjustments` di `extend_db_ptrj` ke nilai real `PR_ADTRANS` di `db_ptrj`. Endpoint ini dipakai untuk menemukan data yang **ada di extend_db_ptrj tetapi tidak ada / bernilai 0 di db_ptrj**, misalnya `AUTO SPSI` masih tersimpan 4000 di manual adjustment padahal Plantware sudah tidak punya record SPSI untuk employee tersebut.

Endpoint ini memakai bypass API key yang sama: header `X-API-Key` wajib diisi.

**Aturan EmpCode PTRJ:** saat endpoint mengecek `PR_ADTRANS` / `PR_ADTRANS_ARC`, identifier employee selalu di-resolve dulu ke format `EmpCode` PTRJ yang diawali huruf, misalnya `A0001` atau `B0745`. Jika `payroll_manual_adjustments.emp_code` berisi NIK/KTP numeric, endpoint akan mencari pasangan di `HR_EMPLOYEE.NewICNo` lalu memakai `HR_EMPLOYEE.EmpCode` untuk query `PR_ADTRANS.EmpCode`. Field response `emp_code` juga memakai EmpCode PTRJ letter; nilai numeric asal hanya muncul sebagai `stored_emp_identifier` jika berbeda. Jangan memakai NIK numeric langsung untuk query `PR_ADTRANS.EmpCode` karena akan menghasilkan false `EXTRA_IN_ADJUSTMENTS`.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `period_month` | number | ✅ | Bulan (1-12), dipakai sebagai `PhyMonth` saat cek `db_ptrj` |
| `period_year` | number | ✅ | Tahun, dipakai sebagai `PhyYear` saat cek `db_ptrj` |
| `division_code` | string | ✅ | Kode divisi, termasuk virtual division seperti `NRS` |
| `filters` | string[] | ❌ | Kategori filter (default: `['spsi', 'masa kerja', 'jabatan', 'premi', 'koreksi', 'potongan']`) |

**Example:**

```bash
curl -X POST "http://localhost:8002/payroll/manual-adjustment/reverse-compare-adtrans/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "NRS",
    "filters": ["spsi", "masa kerja", "jabatan", "premi", "koreksi", "potongan"]
  }'
```

**Ambil hanya yang extra di extend:**

```bash
curl -s -X POST "http://localhost:8002/payroll/manual-adjustment/reverse-compare-adtrans/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "NRS",
    "filters": ["spsi", "masa kerja", "jabatan", "premi", "koreksi", "potongan"]
  }' | jq '.data.comparisons[] | select(.status == "EXTRA_IN_ADJUSTMENTS")'
```

**Response:**

```json
{
  "success": true,
  "message": "Reverse comparison completed successfully",
  "data": {
    "division": "NRS",
    "period_month": 4,
    "period_year": 2026,
    "compared_categories": ["spsi", "masa kerja", "jabatan", "premi", "koreksi", "potongan"],
    "total_adjustments": 3,
    "match_count": 1,
    "mismatch_count": 1,
    "extra_in_adjustments": 1,
    "comparisons": [
      {
        "emp_code": "B0745",
        "category": "spsi",
        "adjustment_name": "AUTO SPSI",
        "stored_amount": 4000,
        "source_amount": 4000,
        "diff": 0,
        "status": "MATCH",
        "gang_code": "B2N",
        "division_code": "NRS",
        "remarks": "AUTO SPSI | potongan spsi | 4000"
      },
      {
        "emp_code": "B0746",
        "category": "spsi",
        "adjustment_name": "AUTO SPSI",
        "stored_amount": 4000,
        "source_amount": 0,
        "diff": -4000,
        "status": "EXTRA_IN_ADJUSTMENTS",
        "gang_code": "B2N",
        "division_code": "NRS",
        "remarks": "AUTO SPSI | potongan spsi | 4000"
      },
      {
        "emp_code": "B0747",
        "category": "masa kerja",
        "adjustment_name": "AUTO MASA KERJA",
        "stored_amount": 2500,
        "source_amount": 5000,
        "diff": 2500,
        "status": "MISMATCH",
        "gang_code": "B2N",
        "division_code": "NRS",
        "remarks": "AUTO MASA KERJA | masa kerja | 2500"
      }
    ]
  }
}
```

**Reverse Comparison Status:**

| Status | Description | Insight yang diberikan |
|--------|-------------|------------------------|
| `MATCH` | Nilai di `extend_db_ptrj` sama dengan `db_ptrj` (toleransi ≤ 0.01) | Record manual adjustment masih sesuai dengan Plantware. |
| `MISMATCH` | Nilai ada di kedua sisi tetapi nominal berbeda | Manual adjustment masih ada dan Plantware juga ada, tetapi nominal perlu ditinjau. |
| `EXTRA_IN_ADJUSTMENTS` | Record ada di `extend_db_ptrj`, tetapi nilai source `db_ptrj` = 0 / tidak ada untuk employee+category tersebut | Manual adjustment kemungkinan sudah tidak punya pasangan di Plantware dan perlu dibersihkan/diupdate. |

**Cara membaca detail reverse comparison:**

| Field | Makna |
|-------|-------|
| `emp_code` | EmpCode PTRJ letter yang dipakai untuk query `PR_ADTRANS.EmpCode`. |
| `stored_emp_identifier` | Identifier asal dari `payroll_manual_adjustments.emp_code` jika berbeda dari EmpCode PTRJ; biasanya NIK/KTP numeric. |
| `category` | Kategori hasil mapping: `spsi`, `masa kerja`, `jabatan`, `premi`, `koreksi`, atau `potongan`. |
| `adjustment_name` | Nama record di `payroll_manual_adjustments`. |
| `stored_amount` / `extend_db_ptrj_amount` | Nominal yang tersimpan di `extend_db_ptrj.payroll_manual_adjustments`. |
| `source_amount` / `db_ptrj_amount` | Total nominal pembanding dari `db_ptrj.PR_ADTRANS` + `PR_ADTRANS_ARC`. |
| `diff` | `source_amount - stored_amount`; negatif berarti nilai manual adjustment lebih besar dari source Plantware. |
| `status` | `MATCH`, `MISMATCH`, atau `EXTRA_IN_ADJUSTMENTS`. |
| `db_ptrj_doc_desc_details` | Detail baris pembentuk nilai source dari Plantware: `doc_desc`, `doc_id`, dan `amount`. Jika source kosong, array ini kosong. |
| `extend_db_ptrj_remarks` | Remarks/catatan dari record manual adjustment di `extend_db_ptrj`. |
| `gang_code` / `division_code` | Scope asal record manual adjustment. |
| `remarks` | Alias lama dari `extend_db_ptrj_remarks` untuk kompatibilitas response. |

**Contoh insight dari response reverse compare:**

```bash
# Semua manual adjustment yang tidak punya pasangan/nilai di db_ptrj
jq '.data.comparisons[] | select(.status == "EXTRA_IN_ADJUSTMENTS")'

# Ringkasan extra/mismatch per kategori
jq '.data.comparisons
  | map(select(.status != "MATCH"))
  | group_by(.category)
  | map({category: .[0].category, count: length, statuses: (group_by(.status) | map({status: .[0].status, count: length}))})'

# Cek kasus identifier numeric yang sudah dikonversi ke EmpCode PTRJ letter
jq '.data.comparisons[] | select(.stored_emp_identifier != null) | {emp_code, stored_emp_identifier, category, status, stored_amount, source_amount}'

# Top 20 selisih nominal terbesar dari manual adjustment ke db_ptrj
jq '.data.comparisons
  | map(select(.status != "MATCH"))
  | sort_by((.diff | if . < 0 then -. else . end))
  | reverse
  | .[0:20]'

# Lihat detail DocDesc db_ptrj dan remarks extend_db_ptrj untuk data yang beda/extra
jq '.data.comparisons[]
  | select(.status != "MATCH")
  | {emp_code, stored_emp_identifier, category, db_ptrj_amount, extend_db_ptrj_amount, diff, db_ptrj_doc_desc_details, extend_db_ptrj_remarks}'
```

**Perbedaan dengan compare biasa:**

| Endpoint | Arah cek | Cocok untuk |
|----------|----------|-------------|
| `sync-status/by-api-key` | browser automation -> db_ptrj -> remarks | Setelah browser automation input ke Plantware, verifikasi row sudah muncul di PR_ADTRANS lalu ubah hanya segmen `sync:` pada remarks manual adjustment. |
| `compare-adtrans/by-api-key` | `db_ptrj` → `extend_db_ptrj` | Mencari data real Plantware yang belum ada (`MISSING`) atau nominalnya beda (`MISMATCH`) di manual adjustment. |
| `reverse-compare-adtrans/by-api-key` | `extend_db_ptrj` → `db_ptrj` | Mencari manual adjustment yang masih ada padahal tidak ada/nol di Plantware (`EXTRA_IN_ADJUSTMENTS`) atau nominalnya beda (`MISMATCH`). |

---

### 6. POST `/payroll/manual-adjustment/sync-status/by-api-key`

Endpoint ini dipakai oleh browser automation atau agent lain setelah selesai input manual adjustment ke Plantware. Tujuannya bukan membuat nominal baru, tetapi memverifikasi data sudah masuk ke `db_ptrj` (`PR_ADTRANS`/`PR_ADTRANS_ARC`) lalu mengubah status `sync:` pada `remarks`.

Aturan penting:

- Hanya memproses `PREMI`, `POTONGAN_KOTOR`, dan `POTONGAN_BERSIH`.
- Tidak memproses `AUTO_BUFFER`.
- Hanya mengubah segmen pipe `sync:<status>` dari `remarks.split("|")`; segmen lain seperti adjustment name, task desc/ADCode, amount, dan `match:` tidak diubah.
- Jika `only_if_adtrans_exists=true`, row hanya diubah menjadi `sync:SYNC` kalau transaksi terkait sudah ditemukan di `db_ptrj`.
- Untuk premi yang punya `metadata_json` detail, pembanding nominal memakai total detail metadata. Jika baru sebagian detail/subblok yang terinput di Plantware, response memberi `skip_reason: "ADTRANS_AMOUNT_PARTIAL"` dan remarks tidak diubah.
- Untuk automation client, segmen `sync:SYNC` di remarks adalah status authoritative bahwa row sudah sync. Segmen lain seperti `match:MANUAL` tidak boleh dipakai untuk retry/input ulang jika `sync` sudah `SYNC`.

Jangan tertukar dengan `sync-adtrans/by-api-key`. Endpoint `sync-adtrans` membuat atau mengubah data manual adjustment dari ADTRANS. Endpoint `sync-status` hanya menandai row manual adjustment yang sudah berhasil diinput ke Plantware.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `period_month` | number | yes | Bulan payroll/PhyMonth |
| `period_year` | number | yes | Tahun payroll/PhyYear |
| `division_code` / `estate` | string | no | Estate/LocCode seperti `AB1`; disarankan selalu isi |
| `gang_code` | string | no | Filter gang tertentu |
| `emp_code` | string | no | Filter employee tertentu |
| `adjustment_type` | string | no | `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, atau comma-separated |
| `adjustment_types` | string[] | no | Alternatif array untuk type |
| `adjustment_name` | string | no | Filter nama adjustment |
| `ids` | number[] | no | Target row spesifik `payroll_manual_adjustments.id` |
| `sync_status` | string | no | Status tujuan, default `SYNC` |
| `only_if_adtrans_exists` | boolean | no | Jika `true`, verifikasi ke `db_ptrj` dulu sebelum update |
| `dry_run` | boolean | no | Jika `true`, hanya verifikasi dan preview, tidak update DB |
| `updated_by` | string | no | User/agent pencatat |
| `limit` | number | no | Batas row, default 1000, max 5000 |

**Cara endpoint memverifikasi ADTRANS:**

- Scope utama adalah `period_month`, `period_year`, `division_code`/`estate`, `gang_code`, `emp_code`, `adjustment_type`, `adjustment_name`, atau `ids`.
- Untuk `PREMI`, kategori ADTRANS adalah dokumen premi dinamis.
- Untuk `POTONGAN_KOTOR`, kategori ADTRANS adalah `koreksi` jika nama adjustment mengandung `KOREKSI`; selain itu dianggap `potongan`.
- Untuk `POTONGAN_BERSIH`, kategori ADTRANS dianggap `potongan`.
- Matching memakai employee (`emp_code`), LocCode/estate, kategori DocDesc, dan teks TaskDesc/ADCode dari remarks/definition jika tersedia.
- Jika `metadata_json` punya detail, `target_amount` memakai total detail metadata. Ini penting untuk premi per subblok: row baru boleh `SYNC` kalau nominal ADTRANS sudah menutup total detail yang seharusnya diinput.

**Flow browser automation yang disarankan:**

1. Ambil data input dari `GET /payroll/manual-adjustment/by-api-key?view=grouped&metadata_only=true`.
2. Browser automation input satu atau beberapa employee/detail ke Plantware.
3. Panggil endpoint ini dengan `only_if_adtrans_exists=true` dan `dry_run=true` untuk preview.
4. Jika `updated_count` sesuai dan `partial_count=0`, panggil lagi dengan `dry_run=false`.
5. Jika ada `ADTRANS_AMOUNT_PARTIAL`, lanjutkan input detail/subblok yang belum masuk; jangan paksa `sync:SYNC`.

**Catatan UI Auto Key In Refactor:**

- Kolom `Input Status` hanya menunjukkan hasil runner/browser untuk baris tersebut.
- Kolom `API Sync` dan `API Match` harus diperbarui dari endpoint ini, bukan dari asumsi bahwa browser berhasil klik Add.
- Setelah event `row.success`, app boleh langsung mengantrekan id row ke endpoint ini untuk status realtime, tetapi final verification tetap perlu dijalankan lagi setelah Save/Submit tab selesai karena ADTRANS bisa baru muncul setelah submit.
- Status `ADTRANS_AMOUNT_PARTIAL` atau `ADTRANS_NOT_FOUND` tidak boleh dianggap sukses sync dan tidak boleh dipaksa update remarks.

**Contoh dry run untuk AB1 premi:**

```bash
curl -X POST "http://localhost:8002/payroll/manual-adjustment/sync-status/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "AB1",
    "adjustment_type": "PREMI",
    "sync_status": "SYNC",
    "only_if_adtrans_exists": true,
    "dry_run": true,
    "updated_by": "browser_automation"
  }'
```

**Contoh update setelah dry run aman:**

```bash
curl -X POST "http://localhost:8002/payroll/manual-adjustment/sync-status/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "AB1",
    "adjustment_type": "PREMI",
    "sync_status": "SYNC",
    "only_if_adtrans_exists": true,
    "dry_run": false,
    "updated_by": "browser_automation"
  }'
```

**Contoh update satu row spesifik setelah input satu employee selesai:**

```bash
curl -X POST "http://localhost:8002/payroll/manual-adjustment/sync-status/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "AB1",
    "ids": [12345],
    "sync_status": "SYNC",
    "only_if_adtrans_exists": true,
    "dry_run": false,
    "updated_by": "browser_automation"
  }'
```

**Contoh update per gang setelah batch browser automation selesai:**

```bash
curl -X POST "http://localhost:8002/payroll/manual-adjustment/sync-status/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "AB1",
    "gang_code": "G1H",
    "adjustment_type": "PREMI",
    "sync_status": "SYNC",
    "only_if_adtrans_exists": true,
    "dry_run": false,
    "updated_by": "browser_automation"
  }'
```

**Contoh response partial detail:**

```json
{
  "success": true,
  "data": {
    "matched_count": 1,
    "eligible_count": 1,
    "adtrans_matched_count": 1,
    "updated_count": 0,
    "partial_count": 1,
    "rows": [
      {
        "id": 14,
        "emp_code": "A0001",
        "adjustment_type": "PREMI",
        "adjustment_name": "PREMI PRUNING",
        "target_amount": 500000,
        "metadata_detail_total": 500000,
        "adtrans_amount": 350000,
        "old_sync_status": "MANUAL",
        "new_sync_status": "SYNC",
        "status": "SKIPPED",
        "skip_reason": "ADTRANS_AMOUNT_PARTIAL",
        "remarks_before": "PREMI PRUNING | AL3PM0601P1A - PRUNING MANUAL | 500000 | sync:MANUAL | match:MANUAL",
        "remarks_after": null
      }
    ]
  }
}
```

**Field response utama:**

| Field | Arti |
|-------|------|
| `matched_count` | Jumlah row manual adjustment yang masuk filter awal |
| `eligible_count` | Row yang punya format remarks pipe dengan segmen `sync:` |
| `adtrans_matched_count` | Row yang menemukan transaksi cocok di ADTRANS |
| `updated_count` | Row yang remarks-nya benar-benar diubah |
| `unchanged_count` | Row yang sudah berada di target `sync_status` |
| `skipped_count` | Row yang dilewati karena tidak memenuhi syarat |
| `partial_count` | Row detail/metadata yang baru sebagian nominalnya ditemukan di ADTRANS |
| `rows[]` | Detail keputusan per row, termasuk `remarks_before`, `remarks_after`, dan `skip_reason` |

**Skip reason utama:**

| skip_reason | Arti |
|-------------|------|
| `SYNC_SEGMENT_NOT_FOUND` | Remarks tidak punya format pipe `sync:<status>` |
| `ADTRANS_NOT_FOUND` | Belum ada transaksi cocok di `db_ptrj` |
| `ADTRANS_AMOUNT_PARTIAL` | Ada transaksi cocok, tapi nominal belum menutup total row/detail metadata |

---

### 7. POST `/payroll/manual-adjustment/sync-adtrans/by-api-key`

**Sync real-time** dari PR_ADTRANS (`db_ptrj`) ke `payroll_manual_adjustments` (`extend_db_ptrj`). Hanya mensync item yang **MISMATCH** atau **MISSING** berdasarkan hasil komparasi.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `period_month` | number | ✅ | Bulan (1-12) |
| `period_year` | number | ✅ | Tahun |
| `division_code` | string | ✅ | Kode divisi (e.g. `AB1`, `PG2A`) |
| `filters` | string[] | ❌ | Kategori filter (default: `['spsi', 'masa kerja', 'jabatan', 'premi', 'koreksi', 'potongan']`) |
| `sync_mode` | string | ❌ | Mode sync: `MISSING_ONLY`, `MISMATCH_AND_MISSING`, `ALL` (default: `MISMATCH_AND_MISSING`) |
| `created_by` | string | ❌ | User pencatat (default: `sync_adtrans_api`) |

**Sync Modes:**

| Mode | Description |
|------|-------------|
| `MISSING_ONLY` | Hanya insert record yang belum ada di extend_db |
| `MISMATCH_AND_MISSING` | Insert yang belum ada + update yang nilainya beda (default) |
| `ALL` | Sync semua termasuk yang sudah MATCH (overwrite) |

**Example:**

```bash
# Sync default (MISMATCH + MISSING only)
curl -X POST "http://localhost:8002/payroll/manual-adjustment/sync-adtrans/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "AB1"
  }'

# Sync hanya yang missing (tidak overwrite yang sudah ada)
curl -X POST "http://localhost:8002/payroll/manual-adjustment/sync-adtrans/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "AB1",
    "sync_mode": "MISSING_ONLY"
  }'

# Force sync semua (overwrite match juga)
curl -X POST "http://localhost:8002/payroll/manual-adjustment/sync-adtrans/by-api-key" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "period_month": 4,
    "period_year": 2026,
    "division_code": "AB1",
    "sync_mode": "ALL"
  }'
```

**Response:**

```json
{
  "success": true,
  "message": "Sync completed: 15 records synced, 60 matches skipped",
  "data": {
    "division": "AB1",
    "period_month": 4,
    "period_year": 2026,
    "sync_mode": "MISMATCH_AND_MISSING",
    "total_compared": 75,
    "synced_count": 15,
    "skipped_match": 60,
    "synced_details": [
      {
        "emp_code": "G0010",
        "category": "jabatan",
        "adjustment_name": "AUTO TUNJANGAN JABATAN",
        "old_amount": 0,
        "new_amount": 150000,
        "action": "UPDATE"
      },
      {
        "emp_code": "G0015",
        "category": "masa kerja",
        "adjustment_name": "AUTO MASA KERJA",
        "old_amount": null,
        "new_amount": 25000,
        "action": "INSERT"
      }
    ]
  }
}
```

**Sync Behavior:**

- **INSERT**: Jika record tidak ada di `extend_db_ptrj` (status `MISSING`), buat record baru dengan `adjustment_type = 'AUTO_BUFFER'`.
- **UPDATE**: Jika record ada tapi nilainya beda (status `MISMATCH`), update amount dan remarks.
- **Remarks**: Setelah sync, remarks berformat `{adjustment_name} | {adcode} | {amount} | sync:SYNC | match:MATCH`.
- **Cache**: Cache payroll otomatis di-clear setelah sync agar data terbaru langsung terpakai.

**Data Flow:**

```text
PR_ADTRANS + PR_ADTRANS_ARC (db_ptrj)
  ↓ query by PhyMonth/PhyYear + LocCode
  ↓ group by EmpCode + DocDesc category
  ↓
compareAdtransWithAdjustments()
  ↓ compare with payroll_manual_adjustments (extend_db_ptrj)
  ↓ identify MATCH / MISMATCH / MISSING
  ↓
syncAdtransToAdjustments()
  ↓ INSERT missing records
  ↓ UPDATE mismatched records
  ↓ clear cache
  ↓
payroll_manual_adjustments (extend_db_ptrj) updated
```
