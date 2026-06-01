#!/usr/bin/env tsx
import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

type ApiVehicleTransaction = {
  transaction_index?: number | null;
  adjustment_id?: number | null;
  adjustment_type?: string | null;
  adjustment_name?: string | null;
  emp_code?: string | null;
  emp_name?: string | null;
  nik?: string | null;
  gang_code?: string | null;
  estate?: string | null;
  estate_code?: string | null;
  division_code?: string | null;
  ad_code?: string | null;
  ad_code_desc?: string | null;
  detail_type?: string | null;
  subblok?: string | null;
  subblok_raw?: string | null;
  jumlah?: number | string | null;
  amount?: number | string | null;
  expense_code?: string | null;
  vehicle_code?: string | null;
  nomor_kendaraan?: string | null;
  vehicle_expense_code?: string | null;
};

type ApiGroupedEmployee = { premium_transactions?: ApiVehicleTransaction[] };
type ApiGroupedGang = { employees?: ApiGroupedEmployee[] };
type ApiGroupedEstate = { gangs?: ApiGroupedGang[] };

type ManualAdjustmentRecord = {
  emp_code: string;
  emp_name?: string | null;
  nik?: string | null;
  gang_code: string;
  division_code: string;
  estate?: string | null;
  divisioncode?: string | null;
  adjustment_type: string;
  adjustment_name: string;
  amount: number;
  remarks: string;
  category_key: string;
  ad_code: string;
  ad_code_desc?: string | null;
  description: string;
  task_code: string;
  task_desc: string;
  base_task_code: string;
  loc_code: string;
  automation_category: string;
  detail_type?: string | null;
  subblok?: string | null;
  subblok_raw?: string | null;
  jumlah?: number | null;
  expense_code?: string | null;
  vehicle_code?: string | null;
  vehicle_expense_code?: string | null;
  transaction_index?: number | null;
  adjustment_id?: number | null;
  detail_key?: string | null;
};

type RunnerPayload = {
  period_month: number;
  period_year: number;
  division_code: string;
  gang_code: string;
  category_key: string;
  runner_mode: "dry_run" | "session_reuse_single";
  max_tabs: number;
  headless: boolean;
  only_missing_rows: boolean;
  row_limit: number | null;
  records: ManualAdjustmentRecord[];
};

const DEFAULT_API_KEY = "88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a";
const REPO_ROOT = path.resolve(__dirname, "..");
const REFAC_DIR = path.join(REPO_ROOT, "Auto Key In Refactor");
const RUNNER_PACKAGE_DIR = path.join(REFAC_DIR, "runner");
const RUNNER_CLI_TS = path.join(RUNNER_PACKAGE_DIR, "src", "cli.ts");

function readDotenv(filePath: string): Record<string, string> {
  if (!fs.existsSync(filePath)) return {};
  return Object.fromEntries(
    fs.readFileSync(filePath, "utf-8")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#") && line.includes("="))
      .map((line) => {
        const [key, ...valueParts] = line.split("=");
        return [key.trim(), valueParts.join("=").trim().replace(/^["']|["']$/g, "")];
      })
  );
}

function argValue(name: string, fallback: string): string {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  if (match) return match.slice(prefix.length);
  const index = process.argv.indexOf(`--${name}`);
  if (index >= 0 && process.argv[index + 1]) return process.argv[index + 1];
  return fallback;
}

function hasFlag(name: string): boolean {
  return process.argv.includes(`--${name}`);
}

function toNumber(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "string") return Number(value.replace(/,/g, ""));
  return 0;
}

function cleanText(value: string | null | undefined): string {
  return (value || "").replace(/^\((AL|DE|PM|PI|PN|ME)\)\s*/i, "").replace(/\s+/g, " ").trim();
}

async function requestJson<T>(url: URL, apiKey: string): Promise<T> {
  const response = await fetch(url, { headers: { "X-API-Key": apiKey } });
  const text = await response.text();
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${text}`);
  return JSON.parse(text) as T;
}

function flattenPremiumTransactions(estates: ApiGroupedEstate[]): ApiVehicleTransaction[] {
  return estates.flatMap((estate) =>
    (estate.gangs ?? []).flatMap((gang) =>
      (gang.employees ?? []).flatMap((employee) => employee.premium_transactions ?? [])
    )
  );
}

export function filterVehicleTransactions(
  transactions: ApiVehicleTransaction[],
  filters: { divisionCode: string; gangCode: string }
): ApiVehicleTransaction[] {
  const divisionCode = filters.divisionCode.trim().toUpperCase();
  const gangCode = filters.gangCode.trim().toUpperCase();
  return transactions.filter((tx) => {
    const estate = (tx.estate_code || tx.estate || "").trim().toUpperCase();
    if (estate && estate !== divisionCode) return false;
    if ((tx.gang_code || "").trim().toUpperCase() !== gangCode) return false;
    const vehicleCode = tx.vehicle_code || tx.nomor_kendaraan || "";
    return (tx.detail_type || "").trim().toLowerCase() === "kendaraan" && Boolean(vehicleCode.trim());
  });
}

function recordFromVehicleTransaction(tx: ApiVehicleTransaction, divisionCode: string): ManualAdjustmentRecord | null {
  const empCode = (tx.emp_code || "").trim().toUpperCase();
  const amount = toNumber(tx.amount ?? tx.jumlah);
  const adjustmentName = cleanText(tx.adjustment_name) || "PREMI VEHICLE";
  const vehicleCode = (tx.vehicle_code || tx.nomor_kendaraan || "").trim().toUpperCase();
  const adCode = (tx.ad_code_desc || tx.ad_code || adjustmentName).trim();
  const plantwareDivision = (tx.division_code || "").trim().toUpperCase();
  if (!empCode || !amount || !vehicleCode || !plantwareDivision) return null;
  const detailKeyParts = [tx.adjustment_id, tx.transaction_index, vehicleCode].filter((part) => part !== undefined && part !== null && String(part).trim());
  return {
    emp_code: empCode,
    emp_name: tx.emp_name ?? null,
    nik: tx.nik ?? null,
    gang_code: (tx.gang_code || "").trim().toUpperCase(),
    division_code: divisionCode,
    estate: tx.estate_code || tx.estate || divisionCode,
    divisioncode: plantwareDivision,
    adjustment_type: tx.adjustment_type || "PREMI",
    adjustment_name: adjustmentName,
    amount,
    remarks: `AD CODE: ${adCode} - ${tx.ad_code_desc || adjustmentName}`,
    category_key: "premi",
    ad_code: tx.ad_code || adCode,
    ad_code_desc: tx.ad_code_desc || null,
    description: adjustmentName,
    task_code: tx.ad_code || adCode,
    task_desc: tx.ad_code_desc || adjustmentName,
    base_task_code: tx.ad_code || adCode,
    loc_code: tx.estate_code || tx.estate || divisionCode,
    automation_category: "premi",
    detail_type: "kendaraan",
    subblok: null,
    subblok_raw: null,
    jumlah: amount,
    expense_code: tx.expense_code || "L",
    vehicle_code: vehicleCode,
    vehicle_expense_code: tx.vehicle_expense_code || tx.expense_code || "L",
    transaction_index: tx.transaction_index ?? null,
    adjustment_id: tx.adjustment_id ?? null,
    detail_key: detailKeyParts.join(":") || null
  };
}

export function buildVehicleExperimentPayload(
  transactions: ApiVehicleTransaction[],
  options: { month: number; year: number; divisionCode: string; gangCode: string; execute: boolean; limit?: number }
): RunnerPayload {
  const records = transactions
    .map((tx) => recordFromVehicleTransaction(tx, options.divisionCode))
    .filter((record): record is ManualAdjustmentRecord => record !== null)
    .slice(0, options.limit ?? transactions.length);
  return {
    period_month: options.month,
    period_year: options.year,
    division_code: options.divisionCode,
    gang_code: options.gangCode,
    category_key: "premi",
    runner_mode: options.execute ? "session_reuse_single" : "dry_run",
    max_tabs: 1,
    headless: false,
    only_missing_rows: true,
    row_limit: records.length,
    records
  };
}

async function main(): Promise<void> {
  const env = { ...readDotenv(path.join(REPO_ROOT, ".env")), ...readDotenv(path.join(REFAC_DIR, ".env")), ...process.env };
  const baseUrl = argValue("base-url", env.MANUAL_ADJUSTMENT_BASE_URL || env.PAYROLL_API_BASE_URL || env.API_BASE_URL || "http://localhost:8002").replace(/\/$/, "");
  const apiKey = argValue("api-key", env.MANUAL_ADJUSTMENT_API_KEY || env.API_KEY || DEFAULT_API_KEY);
  const divisionCode = argValue("division", "P1B").trim().toUpperCase();
  const gangCode = argValue("gang-code", "B1T").trim().toUpperCase();
  const month = Number(argValue("month", "4"));
  const year = Number(argValue("year", "2026"));
  const limitArg = argValue("limit", "1");
  const limit = limitArg.toUpperCase() === "ALL" ? Number.POSITIVE_INFINITY : Number(limitArg);
  const execute = hasFlag("execute");

  const fetchUrl = new URL(`${baseUrl}/payroll/manual-adjustment/by-api-key`);
  fetchUrl.searchParams.set("period_month", String(month));
  fetchUrl.searchParams.set("period_year", String(year));
  fetchUrl.searchParams.set("division_code", divisionCode);
  fetchUrl.searchParams.set("gang_code", gangCode);
  fetchUrl.searchParams.set("adjustment_type", "PREMI");
  fetchUrl.searchParams.set("metadata_only", "true");
  fetchUrl.searchParams.set("view", "grouped");

  const fetchPayload = await requestJson<{ success: boolean; data: ApiGroupedEstate[] }>(fetchUrl, apiKey);
  const candidates = flattenPremiumTransactions(fetchPayload.data ?? []);
  const vehicleTransactions = filterVehicleTransactions(candidates, { divisionCode, gangCode });
  const payload = buildVehicleExperimentPayload(vehicleTransactions, { month, year, divisionCode, gangCode, execute, limit });
  const outputPath = path.join(REPO_ROOT, "eksperimen", `vehicle-${divisionCode.toLowerCase()}-${gangCode.toLowerCase()}-payload.json`);
  fs.writeFileSync(outputPath, JSON.stringify(payload, null, 2));

  console.log(JSON.stringify({
    event: "experiment.vehicle_payload.ready",
    division_code: divisionCode,
    gang_code: gangCode,
    period_month: month,
    period_year: year,
    premium_transactions: candidates.length,
    vehicle_transactions: vehicleTransactions.length,
    runner_records: payload.records.length,
    payload_path: outputPath,
    mode: payload.runner_mode
  }));

  if (!execute) {
    console.log(JSON.stringify({ event: "experiment.not_executed", message: "Run again with --execute to start Plantware vehicle-based input." }));
    return;
  }

  const result = spawnSync(process.execPath, [
    path.join(RUNNER_PACKAGE_DIR, "node_modules", "tsx", "dist", "cli.mjs"),
    RUNNER_CLI_TS,
    "--payload",
    outputPath
  ], {
    cwd: REFAC_DIR,
    stdio: "inherit",
    env: { ...process.env, PLANTWARE_DIVISION: divisionCode }
  });
  process.exit(result.status ?? 1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch((error) => {
    console.error(JSON.stringify({ event: "experiment.failed", message: error instanceof Error ? error.message : String(error) }));
    process.exit(1);
  });
}
