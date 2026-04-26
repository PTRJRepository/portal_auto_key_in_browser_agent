# Manual Adjustment API

Dokumentasi API untuk mengelola manual adjustment (koreksi) daftar upah melalui API key bypass.

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
| `adjustment_type` | string | ❌ | Filter per type: `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, `PENDAPATAN_LAINNYA`, `AUTO_BUFFER` |
| `adjustment_name` | string | ❌ | Filter per nama (partial match) |

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

## Endpoints

### 1. GET `/payroll/manual-adjustment/by-api-key`

Ambil data manual adjustment berdasarkan periode.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period_month` | string | ✅ | Bulan (1-12) |
| `period_year` | string | ✅ | Tahun (e.g. "2026") |
| `gang_code` | string | ❌ | Filter per gang |
| `emp_code` | string | ❌ | Filter per employee code |
| `division_code` | string | ❌ | Filter per division |
| `adjustment_type` | string | ❌ | Filter per type: `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, `PENDAPATAN_LAINNYA`, `AUTO_BUFFER` |
| `adjustment_name` | string | ❌ | Filter per nama (partial match) |

**Example:**

```bash
curl -X GET "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&gang_code=H1H" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"
```

**Filter Examples:**

```bash
# Filter by division only (get all adjustment types)
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1" \
  -H "X-API-Key: 88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a"

# Filter by adjustment_type = AUTO_BUFFER only
curl -s "http://localhost:8002/payroll/manual-adjustment/by-api-key?period_month=4&period_year=2026&division_code=AB1&adjustment_type=AUTO_BUFFER" \
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

**Note:** GET endpoint mengembalikan semua adjustment_type termasuk `AUTO_BUFFER` dari seeder.

---

### 2. POST `/payroll/manual-adjustment/by-api-key`

Simpan manual adjustment baru atau update yang sudah ada (upsert berdasarkan unique key).

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `period_month` | number | ✅ | Bulan (1-12) |
| `period_year` | number | ✅ | Tahun |
| `nik` | string | ❌ | NIK (KTP) - untuk PENDAPATAN_LAINNYA |
| `emp_code` | string | ✅ | Employee code |
| `gang_code` | string | ✅ | Gang code |
| `division_code` | string | ❌ | Division code |
| `adjustment_type` | string | ✅ | `PREMI`, `POTONGAN_KOTOR`, `POTONGAN_BERSIH`, `PENDAPATAN_LAINNYA`, `AUTO_BUFFER` |
| `adjustment_name` | string | ✅ | Nama adjustment |
| `amount` | number | ✅ | Jumlah nominal |
| `remarks` | string | ❌ | Catatan |

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

- `period_month` + `period_year` + `emp_code` + `adjustment_name`

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
  -d '{"period_month":4,"period_year":2026,"emp_code":"C0001","gang_code":"H1H","adjustment_type":"PREMI","adjustment_name":"BONUS LEBARAN","amount":500000}' | jq .
```
