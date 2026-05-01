import type { ManualAdjustmentRecord } from "../types.js";

export interface CategoryStrategy {
  key: string;
  adcode(record: ManualAdjustmentRecord): string;
  matches(record: ManualAdjustmentRecord): boolean;
  description(record: ManualAdjustmentRecord): string;
  requiresGangAfterAdCode?: boolean;
  expenseCode(record: ManualAdjustmentRecord): string;
}

function cleanDescription(value: string): string {
  return value.toUpperCase().startsWith("AUTO ") ? value.slice(5) : value;
}

function extractAdcodeFromRemarks(remarks: string): string {
  const explicit = remarks.match(/\bAD\s*CODE\s*:\s*([^|\-]+)/i);
  if (explicit?.[1]?.trim()) return explicit[1].trim().toUpperCase();
  const parts = remarks.split("|").map((part) => part.trim()).filter(Boolean);
  return parts.length >= 2 ? parts[1] : "";
}

function manualAdcode(record: ManualAdjustmentRecord, fallback: string): string {
  const displayAdcode = [record.ad_code_desc, record.task_desc, record.description]
    .map((value) => value?.trim() ?? "")
    .find((value) => isTaskDescAdcode(value));
  const explicit = displayAdcode || record.ad_code?.trim() || extractAdcodeFromRemarks(record.remarks || "");
  if (explicit) return explicit;
  if (fallback === "premi" && hasPremiumDetail(record)) {
    throw new Error(`PREMI detail row for ${record.emp_code} / ${record.adjustment_name} is missing ad_code`);
  }
  return fallback;
}

function isTaskDescAdcode(value: string): boolean {
  return /^\((AL|DE)\)\s+/i.test(value.trim());
}

function hasPremiumDetail(record: ManualAdjustmentRecord): boolean {
  const detailType = (record.detail_type ?? "").trim().toLowerCase();
  return Boolean(
    ["blok", "block", "subblok", "sub_block", "kendaraan", "vehicle", "veh"].includes(detailType) ||
    (record.subblok ?? record.subblok_raw ?? record.vehicle_code ?? "").trim()
  );
}

function labourExpense(): string {
  return "Labour";
}

function fieldExpense(): string {
  return "PM";
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
    adcode: () => "spsi",
    matches: (record) => record.adjustment_name.toUpperCase().includes("SPSI"),
    description: () => "POTONGAN SPSI",
    expenseCode: labourExpense
  },
  {
    key: "masa_kerja",
    adcode: () => "masa kerja",
    matches: (record) => record.adjustment_name.toUpperCase().includes("MASA"),
    description: () => "TUNJANGAN MASA KERJA",
    expenseCode: labourExpense
  },
  {
    key: "tunjangan_jabatan",
    adcode: () => "tunjangan jabatan",
    matches: (record) => record.adjustment_name.toUpperCase().includes("JABATAN"),
    description: () => "TUNJANGAN JABATAN",
    expenseCode: labourExpense
  },
  {
    key: "premi_tunjangan",
    adcode: (record) => manualAdcode(record, "premi"),
    matches: (record) => record.adjustment_name.toUpperCase().includes("TUNJANGAN PREMI"),
    description: (record) => cleanDescription(record.adjustment_name),
    requiresGangAfterAdCode: true,
    expenseCode: fieldExpense
  },
  {
    key: "premi",
    adcode: (record) => manualAdcode(record, "premi"),
    matches: (record) => record.adjustment_type === "PREMI" || record.adjustment_name.toUpperCase().includes("PREMI"),
    description: (record) => cleanDescription(record.adjustment_name),
    requiresGangAfterAdCode: true,
    expenseCode: fieldExpense
  },
  {
    key: "potongan_upah_kotor",
    adcode: (record) => manualAdcode(record, "potongan"),
    matches: (record) => {
      const name = record.adjustment_name.toUpperCase();
      return record.adjustment_type === "POTONGAN_KOTOR" || name.includes("POTONGAN") || name.includes("KOREKSI");
    },
    description: (record) => cleanDescription(record.adjustment_name),
    expenseCode: labourExpense
  },
  {
    key: "potongan_upah_bersih",
    adcode: (record) => manualAdcode(record, "potongan upah bersih"),
    matches: (record) => record.adjustment_type === "POTONGAN_BERSIH" || record.adjustment_name.toUpperCase().includes("POTONGAN UPAH BERSIH"),
    description: (record) => cleanDescription(record.adjustment_name),
    expenseCode: labourExpense
  }
];

export function resolveCategory(record: ManualAdjustmentRecord, fallbackKey: string): CategoryStrategy {
  const requestedKey = record.category_key || fallbackKey;
  const normalizedRequestedKey = requestedKey === "koreksi" ? "potongan_upah_kotor" : requestedKey;
  const byRequestedKey = CATEGORY_STRATEGIES.find((strategy) => strategy.key === normalizedRequestedKey);
  if (byRequestedKey) return byRequestedKey;

  if (normalizedRequestedKey) {
    throw new Error(`Unsupported runner category: ${requestedKey}`);
  }

  const byRecordContent = CATEGORY_STRATEGIES.find((strategy) => strategy.matches(record));
  if (byRecordContent) return byRecordContent;

  throw new Error(`Cannot resolve runner category for ${record.adjustment_name || record.emp_code}`);
}
