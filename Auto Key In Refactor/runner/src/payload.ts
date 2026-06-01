import type { RunPayload } from "./types.js";

export function sessionDivisionCode(payload: Pick<RunPayload, "division_code" | "session_division_code">): string {
  return String(payload.session_division_code || payload.division_code || "").trim().toUpperCase();
}
