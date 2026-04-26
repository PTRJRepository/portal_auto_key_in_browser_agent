# Normalisasi Kode Divisi

## Daftar Kode Divisi (4 Kode)

| Kode Normalisasi | Alias API | Label | Kategori |
|-------------------|-----------|-------|----------|
| `PG1A` | `P1A` | Plasma 1 Afdeling | Plantation |
| `PG1B` | `P1B` | Plasma 1 Blok | Plantation |
| `PG2A` | `P2A` | Plasma 2 Afdeling | Plantation |
| `PG2B` | `P2B` | Plasma 2 Blok | Plantation |

## Contoh Penggunaan 3 Divisi

### 1. PG1A (Plasma 1 Afdeling)

```json
{
  "division_code": "PG1A"
}
```

- **Alias API:** `P1A`
- **Data Count (Period 4/2026):** ~555 records
- **Contoh Gang:** B2N, J2M

### 2. PG2B (Plasma 2 Blok)

```json
{
  "division_code": "PG2B"
}
```

- **Alias API:** `P2B`
- **Data Count (Period 4/2026):** ~378 records
- **Contoh Gang:** D1H

### 3. ARA (Area)

```json
{
  "division_code": "ARA"
}
```

- **Alias API:** `ARA`
- **Data Count (Period 4/2026):** ~414 records
- **Contoh Gang:** -

## Catatan Penting

### Masalah Normalisasi

| Config | API Actual | Result |
|--------|------------|--------|
| `PG1B` | `P1B` | 0 records (salah) |
| `P1B` | `P1B` | 561 records (benar) |

**Penyebab:** API Plantware menggunakan kode singkatan 3 karakter, bukan kode normalisasi 4 karakter.

### Solusi di `configs/app.json`

```json
{
  "default_division_code": "P1B"
}
```

**Jangan gunakan** `PG1A`, `PG1B`, `PG2A`, `PG2B` saat fetch data. Gunakan alias API 3 karakter.

## Semua Divisi yang Tersedia

| Kode | Label | Alias |
|------|-------|-------|
| `PG1A` | Plasma 1 Afdeling | `P1A` |
| `PG1B` | Plasma 1 Blok | `P1B` |
| `PG2A` | Plasma 2 Afdeling | `P2A` |
| `PG2B` | Plasma 2 Blok | `P2B` |
| `AB1` | Afdeling 1 | `AB1` |
| `AB2` | Afdeling 2 | `AB2` |
| `ARA` | Area | `ARA` |
| `ARC` | Air Ruak Central | `ARC`, `AREC` |
| `DME` | Dempo | `DME` |
| `IJL` | Ijuk | `IJL` |
| `INF` | Infrastruktur | `INF` |
| `NRS` | Nursery | `NRS` |
| `WKS_AR` | Workshop Air Ruak | - |
| `WKS_PG` | Workshop Parit Gunung | - |

## Filter Division di Aplikasi

1. Buka aplikasi: `python -m app.main`
2. Isi field **Division** dengan kode alias API (3 karakter)
3. Contoh: `P1B` bukan `PG1B`
4. Klik **Test Get Data** untuk verify

## Troubleshooting

**Masalah:** Fetch menghasilkan 0 records
**Penyebab:** Salah kode division
**Solusi:** Gunakan kode 3 karakter (alias API), bukan kode 4 karakter (normalisasi)
