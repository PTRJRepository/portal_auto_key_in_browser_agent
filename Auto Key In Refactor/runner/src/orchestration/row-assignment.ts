import { employeeAutocompleteValue } from "../plantware/page-actions.js";
import type { CategoryStrategy } from "../categories/registry.js";
import type { ManualAdjustmentRecord } from "../types.js";

export function assignRowsToTabs(
  rows: ManualAdjustmentRecord[],
  tabCount: number,
  fallbackCategoryKey: string
): ManualAdjustmentRecord[][] {
  const safeTabCount = Math.max(1, tabCount);
  const assignedRows = Array.from({ length: safeTabCount }, () => [] as ManualAdjustmentRecord[]);
  const groups = assignmentGroups(rows, fallbackCategoryKey);

  for (let groupIndex = 0; groupIndex < groups.length; groupIndex++) {
    const groupRows = groups[groupIndex];
    assignedRows[groupIndex % safeTabCount].push(...groupRows);
  }

  return assignedRows;
}

export function duplicateInputRowKeys(rows: ManualAdjustmentRecord[], fallbackCategoryKey: string): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const record of rows) {
    const key = inputRowIdentityKey(record, fallbackCategoryKey);
    if (seen.has(key)) {
      duplicates.add(key);
    } else {
      seen.add(key);
    }
  }
  return [...duplicates].sort();
}

export function findCrossTabEmployeeSplits(
  assignedRows: ManualAdjustmentRecord[][],
  fallbackCategoryKey: string
): string[] {
  const ownerByEmployee = new Map<string, number>();
  const splits = new Set<string>();
  for (let tabIndex = 0; tabIndex < assignedRows.length; tabIndex++) {
    for (const record of assignedRows[tabIndex]) {
      const key = employeeAssignmentGroupKey(record, fallbackCategoryKey);
      const owner = ownerByEmployee.get(key);
      if (owner === undefined) {
        ownerByEmployee.set(key, tabIndex);
      } else if (owner !== tabIndex) {
        splits.add(key);
      }
    }
  }
  return [...splits].sort();
}

function assignmentGroups(rows: ManualAdjustmentRecord[], fallbackCategoryKey: string): ManualAdjustmentRecord[][] {
  const groups: ManualAdjustmentRecord[][] = [];
  const employeeGroups = new Map<string, ManualAdjustmentRecord[]>();

  for (const record of rows) {
    const groupKey = employeeAssignmentGroupKey(record, fallbackCategoryKey);
    let group = employeeGroups.get(groupKey);
    if (!group) {
      group = [];
      employeeGroups.set(groupKey, group);
      groups.push(group);
    }
    group.push(record);
  }

  return groups;
}

export function employeeAssignmentGroupKey(record: ManualAdjustmentRecord, _fallbackCategoryKey: string): string {
  return [
    employeeAutocompleteValue(record),
    (record.estate || record.division_code || "").trim().toUpperCase()
  ].join("|");
}

export function premiumEmployeeGroupKey(record: ManualAdjustmentRecord, category: CategoryStrategy): string {
  return [
    employeeAutocompleteValue(record),
    (record.estate || record.division_code || "").trim().toUpperCase()
  ].join("|");
}

function inputRowIdentityKey(record: ManualAdjustmentRecord, fallbackCategoryKey: string): string {
  const explicitDetailKey = (record.detail_key ?? "").trim();
  if (explicitDetailKey) return explicitDetailKey;
  return [
    record.period_month ?? "",
    record.period_year ?? "",
    employeeAssignmentGroupKey(record, fallbackCategoryKey),
    (record.adjustment_type ?? "").trim().toUpperCase(),
    (record.adjustment_name ?? "").trim().toUpperCase(),
    (record.detail_type ?? "").trim().toUpperCase(),
    (record.subblok ?? record.subblok_raw ?? record.vehicle_code ?? "").trim().toUpperCase(),
    record.transaction_index ?? "",
    record.amount ?? 0
  ].join("|");
}
