import type { ManualAdjustmentRecord } from "../types.js";

export interface CategoryStrategy {
  key: string;
  adcode: string;
  matches(record: ManualAdjustmentRecord): boolean;
  description(record: ManualAdjustmentRecord): string;
}

function cleanDescription(value: string): string {
  return value.toUpperCase().startsWith("AUTO ") ? value.slice(5) : value;
}

/**
 * Aturan deskripsi yang diinput ke Plantware (field DocDesc):
 *
 * AUTO_BUFFER categories:
 * - SPSI          → "POTONGAN SPSI" (bukan "SPSI")
 * - Masa Kerja    → "TUNJANGAN MASA KERJA" (bukan "MASA KERJA")
 * - Tunjangan Jabatan → "TUNJANGAN JABATAN" (sudah benar dari cleanDescription)
 *
 * Non-AUTO_BUFFER categories:
 * - Ikuti adjustment_name apa adanya (strip prefix "AUTO " jika ada)
 */
export const CATEGORY_STRATEGIES: CategoryStrategy[] = [
  {
    key: "spsi",
    adcode: "spsi",
    matches: (record) => record.adjustment_name.toUpperCase().includes("SPSI"),
    description: () => "POTONGAN SPSI"
  },
  {
    key: "masa_kerja",
    adcode: "masa kerja",
    matches: (record) => record.adjustment_name.toUpperCase().includes("MASA"),
    description: () => "TUNJANGAN MASA KERJA"
  },
  {
    key: "tunjangan_jabatan",
    adcode: "tunjangan jabatan",
    matches: (record) => record.adjustment_name.toUpperCase().includes("JABATAN"),
    description: () => "TUNJANGAN JABATAN"
  }
];

export function resolveCategory(record: ManualAdjustmentRecord, fallbackKey: string): CategoryStrategy {
  const requestedKey = record.category_key || fallbackKey;
  const byRequestedKey = CATEGORY_STRATEGIES.find((strategy) => strategy.key === requestedKey);
  if (byRequestedKey) return byRequestedKey;

  if (requestedKey) {
    throw new Error(`Unsupported runner category: ${requestedKey}`);
  }

  const byRecordContent = CATEGORY_STRATEGIES.find((strategy) => strategy.matches(record));
  if (byRecordContent) return byRecordContent;

  throw new Error(`Cannot resolve runner category for ${record.adjustment_name || record.emp_code}`);
}
