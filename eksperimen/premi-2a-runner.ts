#!/usr/bin/env tsx
import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

type AutomationOption = {
  category?: string;
  adjustment_type?: string;
  adjustment_name?: string;
  ad_code?: string;
  description?: string;
  task_code?: string;
  task_desc?: string;
  base_task_code?: string;
  loc_code?: string | null;
};

type ApiPremiumTransaction = {
  transaction_index?: number | null;
  adjustment_id?: number | null;
  adjustment_type?: string | null;
  adjustment_name?: string | null;
  emp_code?: string;
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
  vehicle_expense_code?: string | null;
};

type ApiGroupedEmployee = {
  premium_transactions?: ApiPremiumTransaction[];
};

type ApiGroupedGang = {
  employees?: ApiGroupedEmployee[];
};

type ApiGroupedEstate = {
  gangs?: ApiGroupedGang[];
};

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
  category_key: string;
  runner_mode: "dry_run" | "session_reuse_single" | "multi_tab_shared_session";
  max_tabs: number;
  headless: boolean;
  only_missing_rows: boolean;
  row_limit: number | null;
  records: ManualAdjustmentRecord[];
};

const DEFAULT_API_KEY = "88217c42101662147aee16779663caa22ff1e896b57568a6576ed56f2f3d124a";
const REPO_ROOT = path.resolve(__dirname, "..");
const REFAC_DIR = path.join(REPO_ROOT, "Auto Key In Refactor");
const RUNNER_CLI_TS = path.join(REFAC_DIR, "runner", "src", "cli.ts");
const RUNNER_PACKAGE_DIR = path.join(REFAC_DIR, "runner");

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

function normalizeDivision(input: string): string {
  const value = input.trim().toUpperCase();
  const aliases: Record<string, string> = {
    "1A": "P1A",
    PG1A: "P1A",
    "1B": "P1B",
    PG1B: "P1B",
    "2A": "P2A",
    PG2A: "P2A",
    "2B": "P2B",
    PG2B: "P2B",
    ARB1: "AB1",
    ARB2: "AB2",
    AREC: "ARC"
  };
  return aliases[value] ?? value;
}

async function requestJson<T>(url: URL, options: RequestInit & { apiKey: string }): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-API-Key", options.apiKey);
  if (options.body) headers.set("Content-Type", "application/json");
  const response = await fetch(url, { ...options, headers });
  const text = await response.text();
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${text}`);
  return JSON.parse(text) as T;
}

async function requestJsonOrNull<T>(url: URL, options: RequestInit & { apiKey: string }): Promise<T | null> {
  try {
    return await requestJson<T>(url, options);
  } catch (error) {
    console.log(JSON.stringify({ event: "experiment.optional_endpoint_unavailable", url: url.toString(), message: error instanceof Error ? error.message : String(error) }));
    return null;
  }
}

function cleanDocDesc(value: string): string {
  return value.replace(/^\((AL|DE|PM|PI|PN|ME)\)\s*/i, "").replace(/\s+/g, " ").trim();
}

function adCodeForDescription(description: string): string {
  const upper = description.toUpperCase();
  if (upper.includes("KINERJA")) return "premi kinerja";
  if (upper.includes("BRONDOL")) return "premi brondol";
  if (upper.includes("PRUN")) return "premi pruning";
  if (upper.includes("INSENTIF")) return "premi insentif";
  if (upper.includes("PANEN")) return "premi panen";
  if (upper.includes("ANGKUT")) return "premi angkut";
  if (upper.includes("RITASE") || upper.includes("RETASE")) return "premi ritase";
  if (upper.includes("TBS")) return "premi tbs";
  return "premi";
}

function flattenPremiumTransactions(estates: ApiGroupedEstate[]): ApiPremiumTransaction[] {
  return estates.flatMap((estate) =>
    (estate.gangs ?? []).flatMap((gang) =>
      (gang.employees ?? []).flatMap((employee) => employee.premium_transactions ?? [])
    )
  );
}

export function filterPremiumTransactions(
  transactions: ApiPremiumTransaction[],
  filters: { empCode?: string; gangCode?: string }
): ApiPremiumTransaction[] {
  const empCode = filters.empCode?.trim().toUpperCase();
  const gangCode = filters.gangCode?.trim().toUpperCase();
  return transactions.filter((tx) => {
    if (empCode && tx.emp_code?.trim().toUpperCase() !== empCode) return false;
    if (gangCode && tx.gang_code?.trim().toUpperCase() !== gangCode) return false;
    return true;
  });
}

function buildRecordsFromTransactions(
  transactions: ApiPremiumTransaction[],
  estateCode: string,
  optionsByAdjustmentName: Map<string, AutomationOption> = new Map()
): ManualAdjustmentRecord[] {
  return transactions
    .map((tx) => {
      const amount = toNumber(tx.amount ?? tx.jumlah);
      const empCode = tx.emp_code?.trim().toUpperCase();
      const description = cleanDocDesc(tx.adjustment_name || "");
      const option = optionsByAdjustmentName.get(description.toUpperCase());
      const plantwareDivision = (tx.division_code || "").trim().toUpperCase();
      const adCode = (tx.ad_code_desc || option?.task_desc || option?.ad_code || tx.ad_code || adCodeForDescription(description)).trim();
      if (!empCode || !amount || !description || !plantwareDivision || !adCode) return null;
      const detailKeyParts = [tx.adjustment_id, tx.transaction_index, tx.subblok || tx.vehicle_code || tx.detail_type].filter((part) => part !== undefined && part !== null && String(part).trim());
      return {
        emp_code: empCode,
        emp_name: tx.emp_name ?? null,
        nik: tx.nik ?? null,
        gang_code: (tx.gang_code || "").trim().toUpperCase(),
        division_code: estateCode,
        estate: tx.estate_code || tx.estate || estateCode,
        divisioncode: plantwareDivision,
        adjustment_type: tx.adjustment_type || "PREMI",
        adjustment_name: description,
        amount,
        remarks: `AD CODE: ${adCode} - ${tx.ad_code_desc || option?.task_desc || description}`,
        category_key: "premi",
        ad_code: tx.ad_code || option?.task_code || option?.base_task_code || adCode,
        ad_code_desc: tx.ad_code_desc || option?.task_desc || option?.ad_code || null,
        description,
        task_code: tx.ad_code || option?.task_code || adCode,
        task_desc: tx.ad_code_desc || option?.task_desc || option?.ad_code || description,
        base_task_code: tx.ad_code || option?.base_task_code || option?.task_code || adCode,
        loc_code: tx.estate_code || tx.estate || estateCode,
        automation_category: "premi",
        detail_type: tx.detail_type ?? null,
        subblok: tx.subblok ?? null,
        subblok_raw: tx.subblok_raw ?? null,
        jumlah: amount,
        expense_code: tx.expense_code || "L",
        vehicle_code: tx.vehicle_code ?? null,
        vehicle_expense_code: tx.vehicle_expense_code ?? null,
        transaction_index: tx.transaction_index ?? null,
        adjustment_id: tx.adjustment_id ?? null,
        detail_key: detailKeyParts.join(":") || null
      };
    })
    .filter((item): item is ManualAdjustmentRecord => item !== null);
}

async function main(): Promise<void> {
  const env = { ...readDotenv(path.join(REPO_ROOT, ".env")), ...readDotenv(path.join(REFAC_DIR, ".env")), ...process.env };
  const baseUrl = argValue("base-url", env.MANUAL_ADJUSTMENT_BASE_URL || env.PAYROLL_API_BASE_URL || env.API_BASE_URL || "http://localhost:8002").replace(/\/$/, "");
  const apiKey = argValue("api-key", env.MANUAL_ADJUSTMENT_API_KEY || env.API_KEY || DEFAULT_API_KEY);
  const divisionCode = normalizeDivision(argValue("division", "2A"));
  const month = Number(argValue("month", "4"));
  const year = Number(argValue("year", "2026"));
  const limitArg = argValue("limit", "1");
  const limit = limitArg.toUpperCase() === "ALL" ? Number.POSITIVE_INFINITY : Number(limitArg);
  const adjustmentName = argValue("adjustment-name", "PRUNING");
  const empCode = argValue("emp-code", "");
  const gangCode = argValue("gang-code", "");
  const execute = hasFlag("execute");

  const optionsUrl = new URL(`${baseUrl}/payroll/manual-adjustment/automation-options/by-api-key`);
  optionsUrl.searchParams.set("division_code", divisionCode);
  optionsUrl.searchParams.set("categories", "premi");
  optionsUrl.searchParams.set("limit", "200");

  const optionsPayload = await requestJsonOrNull<{ success: boolean; data: AutomationOption[] }>(optionsUrl, { method: "GET", apiKey });
  const adjustmentNamesUrl = new URL(`${baseUrl}/payroll/manual-adjustment/adjustment-name-options/by-api-key`);
  adjustmentNamesUrl.searchParams.set("division_code", divisionCode);
  adjustmentNamesUrl.searchParams.set("adjustment_type", "PREMI");
  adjustmentNamesUrl.searchParams.set("limit", "200");
  const adjustmentNamesPayload = await requestJsonOrNull<{ success: boolean; data?: AutomationOption[]; by_type?: Record<string, AutomationOption[]> }>(adjustmentNamesUrl, { method: "GET", apiKey });
  const adjustmentNameOptions = adjustmentNamesPayload?.by_type?.PREMI ?? adjustmentNamesPayload?.data ?? [];
  const options = [
    ...(optionsPayload?.data ?? []),
    ...adjustmentNameOptions
  ];
  if (!options.length) {
    options.push({
      category: "premi",
      adjustment_type: "PREMI",
      adjustment_name: "PREMI",
      ad_code: "premi",
      description: "PREMI",
      task_code: "premi",
      task_desc: "PREMI",
      base_task_code: "premi",
      loc_code: divisionCode
    });
  }

  const fetchUrl = new URL(`${baseUrl}/payroll/manual-adjustment/by-api-key`);
  fetchUrl.searchParams.set("period_month", String(month));
  fetchUrl.searchParams.set("period_year", String(year));
  fetchUrl.searchParams.set("division_code", divisionCode);
  if (empCode) fetchUrl.searchParams.set("emp_code", empCode);
  if (gangCode) fetchUrl.searchParams.set("gang_code", gangCode);
  fetchUrl.searchParams.set("adjustment_type", "PREMI");
  if (adjustmentName.toUpperCase() !== "ALL") {
    fetchUrl.searchParams.set("adjustment_name", adjustmentName);
  }
  fetchUrl.searchParams.set("metadata_only", "true");
  fetchUrl.searchParams.set("view", "grouped");
  const fetchPayload = await requestJson<{ success: boolean; data: ApiGroupedEstate[] }>(fetchUrl, { method: "GET", apiKey });

  const optionsByAdjustmentName = new Map(
    options
      .filter((option) => option.adjustment_name)
      .map((option) => [cleanDocDesc(option.adjustment_name || "").toUpperCase(), option] as const)
  );
  const candidates = flattenPremiumTransactions(fetchPayload.data ?? []);
  const filteredCandidates = filterPremiumTransactions(candidates, { empCode, gangCode });
  const records = buildRecordsFromTransactions(filteredCandidates, divisionCode, optionsByAdjustmentName).slice(0, limit);

  const payload: RunnerPayload = {
    period_month: month,
    period_year: year,
    division_code: divisionCode,
    category_key: "premi",
    runner_mode: execute ? "session_reuse_single" : "dry_run",
    max_tabs: 1,
    headless: false,
    only_missing_rows: true,
    row_limit: records.length,
    records
  };

  const filterSuffix = [empCode, gangCode, adjustmentName.toUpperCase() === "ALL" ? "all" : adjustmentName]
    .filter(Boolean)
    .map((value) => value.toLowerCase().replace(/[^a-z0-9]+/g, "-"))
    .join("-");
  const outputPath = path.join(REPO_ROOT, "eksperimen", `premi-${divisionCode.toLowerCase()}${filterSuffix ? `-${filterSuffix}` : ""}-payload.json`);
  fs.writeFileSync(outputPath, JSON.stringify(payload, null, 2));

  console.log(JSON.stringify({
    event: "experiment.payload.ready",
    division_code: divisionCode,
    period_month: month,
    period_year: year,
    automation_options: options.length,
    adjustment_name: adjustmentName,
    emp_code: empCode || null,
    gang_code: gangCode || null,
    premi_transactions: candidates.length,
    filtered_transactions: filteredCandidates.length,
    runner_records: records.length,
    payload_path: outputPath,
    mode: payload.runner_mode
  }));

  if (!execute) {
    console.log(JSON.stringify({ event: "experiment.not_executed", message: "Run again with --execute to start Plantware browser input." }));
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

main().catch((error) => {
  console.error(JSON.stringify({ event: "experiment.failed", message: error instanceof Error ? error.message : String(error) }));
  process.exit(1);
});
