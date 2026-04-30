export interface ManualAdjustmentRecord {
  id?: number | null;
  period_month?: number | null;
  period_year?: number | null;
  emp_code: string;
  gang_code: string;
  division_code: string;
  adjustment_type: string;
  adjustment_name: string;
  amount: number;
  remarks: string;
  category_key?: string | null;
  ad_code?: string | null;
  description?: string | null;
  task_code?: string | null;
  task_desc?: string | null;
  base_task_code?: string | null;
  loc_code?: string | null;
  automation_category?: string | null;
}

export interface DuplicateDocIdTarget {
  master_id: string;
  doc_id: string;
  doc_date: string;
  emp_code: string;
  emp_name: string;
  doc_desc: string;
  amount?: number | null;
  action: string;
  keep_doc_id: string;
  category: string;
  raw?: Record<string, unknown>;
}

export interface RunPayload {
  period_month: number;
  period_year: number;
  division_code: string;
  gang_code?: string | null;
  emp_code?: string | null;
  adjustment_type?: string | null;
  adjustment_name?: string | null;
  category_key: string;
  runner_mode: "multi_tab_shared_session" | "session_reuse_single" | "fresh_login_single" | "get_session" | "test_session" | "dry_run" | "mock";
  max_tabs: number;
  headless: boolean;
  only_missing_rows: boolean;
  row_limit?: number | null;
  records: ManualAdjustmentRecord[];
  operation?: "input" | "delete_duplicates" | "debug_duplicate_scan";
  duplicate_targets?: DuplicateDocIdTarget[];
  delete_dry_run?: boolean;
}

export interface RowResult {
  emp_code: string;
  adjustment_name: string;
  category_key?: string | null;
  status: "success" | "skipped" | "failed";
  message: string;
  tab_index?: number;
}

export interface DeleteDuplicateRowResult {
  doc_id: string;
  emp_code?: string;
  doc_desc?: string;
  status: "deleted" | "dry_run" | "not_found" | "skipped" | "failed";
  message: string;
  page_index?: number;
}

export interface RunResult {
  success: boolean;
  started_at: string;
  finished_at: string;
  runner_mode: RunPayload["runner_mode"];
  session_reused: boolean;
  total_records: number;
  attempted_rows: number;
  inserted_rows: number;
  skipped_existing_rows: number;
  failed_rows: number;
  error_summary: string | null;
  rows: RowResult[] | DeleteDuplicateRowResult[];
  deleted_rows?: number;
  dry_run_rows?: number;
  not_found_rows?: number;
}
