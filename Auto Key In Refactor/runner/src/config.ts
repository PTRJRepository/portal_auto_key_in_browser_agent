import * as fs from "node:fs";
import * as path from "node:path";

function loadDotenv(): void {
  const envPath = path.resolve(process.cwd(), ".env");
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, "utf-8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...valueParts] = trimmed.split("=");
    if (!key || process.env[key]) continue;
    process.env[key] = valueParts.join("=").trim().replace(/^['\"]|['\"]$/g, "");
  }
}

loadDotenv();

const baseUrl = process.env.PLANTWARE_BASE_URL ?? "http://plantwarep3:8001";

export const PLANTWARE_CONFIG = {
  baseUrl,
  entryUrl: `${baseUrl}/`,
  username: process.env.PLANTWARE_USERNAME ?? "adm075",
  password: process.env.PLANTWARE_PASSWORD ?? "adm075",
  division: process.env.PLANTWARE_DIVISION ?? "P1B",
  listPage: "/en/PR/trx/frmPrTrxADLists.aspx",
  detailPage: "/en/PR/trx/frmPrTrxADDets.aspx",
  maxTabs: 10
};
