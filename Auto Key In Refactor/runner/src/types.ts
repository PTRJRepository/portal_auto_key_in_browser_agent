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
}

export interface RowResult {
  emp_code: string;
  adjustment_name: string;
  category_key?: string | null;
  status: "success" | "skipped" | "failed";
  message: string;
  tab_index?: number;
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
  rows: RowResult[];
}
