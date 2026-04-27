# Aturan Deskripsi (DocDesc) di Plantware

## Konteks

Saat runner menginput data ke Plantware, field `#MainContent_txtDocDesc` (Document Description) diisi berdasarkan aturan per kategori adjustment, **bukan** langsung dari `adjustment_name` API.

## Aturan AUTO_BUFFER

Untuk adjustment_type `AUTO_BUFFER`, deskripsi mengikuti aturan tetap per kategori:

| Category Key | Adjustment Name di API | Deskripsi yang Diinput ke Plantware |
|-------------|----------------------|-----------------------------------|
| `spsi` | AUTO SPSI | **POTONGAN SPSI** |
| `masa_kerja` | AUTO MASA KERJA | **TUNJANGAN MASA KERJA** |
| `tunjangan_jabatan` | AUTO TUNJANGAN JABATAN | **TUNJANGAN JABATAN** |

### Penjelasan

- **SPSI** diinput sebagai **POTONGAN** SPSI karena merupakan potongan iuran SPSI.
- **Masa Kerja** diinput sebagai **TUNJANGAN** MASA KERJA karena merupakan tunjangan.
- **Tunjangan Jabatan** diinput sebagai **TUNJANGAN JABATAN** (sudah mengandung kata "tunjangan").

## Aturan Non-AUTO_BUFFER

Untuk adjustment_type selain `AUTO_BUFFER` (contoh: `PREMI`, `POTONGAN_KOTOR`), deskripsi mengikuti adjustment_name apa adanya. Jika adjustment_name diawali prefix "AUTO ", prefix tersebut dihapus.

Contoh:
- `AUTO PREMI HADIR` → deskripsi: `PREMI HADIR`
- `POTONGAN MANGKIR` → deskripsi: `POTONGAN MANGKIR`

## Implementasi

### TypeScript Runner (`runner/src/categories/registry.ts`)

Setiap `CategoryStrategy` memiliki fungsi `description()` yang mengembalikan deskripsi tetap:

```typescript
// SPSI
description: () => "POTONGAN SPSI"

// Masa Kerja
description: () => "TUNJANGAN MASA KERJA"

// Tunjangan Jabatan
description: () => "TUNJANGAN JABATAN"
```

### Config (`configs/adjustment-categories.json`)

Field `description` ditambahkan per kategori:

```json
{"key":"spsi", ..., "description":"POTONGAN SPSI"}
{"key":"masa_kerja", ..., "description":"TUNJANGAN MASA KERJA"}
{"key":"tunjangan_jabatan", ..., "description":"TUNJANGAN JABATAN"}
```

Kategori tanpa aturan khusus memiliki `"description": null`.

### Python Registry (`app/core/category_registry.py`)

Field `description` tersedia di `AdjustmentCategory` dataclass untuk referensi UI/logging.

## Catatan

- Aturan ini berlaku untuk field DocDesc saja, bukan untuk adcode autocomplete.
- Adcode tetap menggunakan: `spsi`, `masa kerja`, `tunjangan jabatan`.
- Deskripsi diisi pada setiap row/input attempt; `isFirstRow` hanya untuk setup form-level seperti division/charge-to.
