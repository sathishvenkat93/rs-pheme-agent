// Shape of report/execution_report.json (schema_version 1), as written by pheme-report.

export interface Stats {
  avg: number;
  min: number;
  max: number;
  n: number;
}

export interface Flag {
  field: string;
  note: string;
}

export interface TimelineEvent {
  time: string;
  offset_s: number;
  kind: string;
  name: string;
  details: string[];
}

export interface ExportEvent {
  id: string | null;
  received_at: number | null;
  session_id: string | null;
  type: string | null;
  name: string | null;
  description: string | null;
  text: string | null;
}

export interface DltMessage {
  index: number | null;
  app_id: string | null;
  ctx_id: string | null;
  level: string | null;
  text: string | null;
  payload: string | null;
}

export interface Assertion {
  expected: string | null;
  actual: string | null;
  verdict: string | null;
  similarity_pct: number | null;
  latency_ms: number | null;
  [extra: string]: string | number | null;
}

export interface CaseFacts {
  case_id: string;
  key: string;
  log_file: string;
  sheet: string | null;
  excel_row: number | null;
  category: string | null;
  utterance: string | null;
  stimulus: Record<string, string>;
  assertion: Assertion;
  flags: Flag[];
  telemetry_errors: string[];
  timeline: { declared_events: number | null; events: TimelineEvent[] };
  other_sections: Record<string, string[]>;
  raw_log: string;
  export: { file: string; total: number; truncated: boolean; events: ExportEvent[] } | null;
  dlt: {
    file: string;
    total: number;
    truncated: boolean;
    by_level: Record<string, number>;
    messages: DltMessage[];
  } | null;
}

export interface CaseAnalysis {
  likely_cause: string;
  explanation: string;
  evidence: string[];
  evidence_dropped: number;
  suggested_action: string;
  confidence: "low" | "medium" | "high";
}

export interface RunAi {
  status: "ok" | "skipped" | "error";
  reason?: string;
  error?: string;
  model?: string;
  generated_at?: string;
  input_truncated?: boolean;
  summary?: {
    headline: string;
    overview: string;
    key_findings: string[];
    recommended_actions: string[];
  };
  cases?: Record<string, CaseAnalysis>;
  failure_groups?: FailureGroup[];
  failure_groups_truncated?: boolean;
}

export interface FailureGroup {
  title: string;
  likely_cause: string;
  description: string;
  case_ids: string[];
  shared_evidence: string[];
  evidence_dropped: number;
  suggested_action: string;
}

export type Outcome = "pass" | "fail" | "other";

export interface Metrics {
  cases_total: number;
  cases_selected: number | null;
  cases_completed: number | null;
  passed: number;
  failed: number;
  other: number;
  pass_rate_pct: number | null;
  verdict_counts: Record<string, number>;
  latency_ms: Stats | null;
  similarity_pct: Stats | null;
  cases_with_telemetry_errors: number;
  cases_with_flags: number;
  dlt_messages_by_level: Record<string, number>;
  duration_s: number | null;
}

export interface Run {
  stamp: string;
  source_present: boolean;
  facts: {
    execution: Record<string, unknown> | null;
    baseline: Record<string, unknown> | null;
    cases: CaseFacts[];
  };
  facts_sha256: string;
  computed: { metrics: Metrics; case_outcomes: Record<string, Outcome>; consistency: string[] };
  sources: { path: string; sha256: string; bytes: number }[];
  parse_warnings: string[];
  ai: RunAi;
}

export interface TrendPoint {
  stamp: string;
  started: string | null;
  sheet: string | null;
  outcome: string | null;
  cases_total: number;
  cases_selected: number | null;
  cases_completed: number | null;
  passed: number;
  failed: number;
  other: number;
  pass_rate_pct: number | null;
  verdict_counts: Record<string, number>;
  avg_latency_ms: number | null;
  avg_similarity_pct: number | null;
  cases_with_telemetry_errors: number;
  cases_with_flags: number;
  duration_s: number | null;
}

export interface CaseHistoryEntry {
  stamp: string;
  case_id: string;
  verdict: string | null;
  outcome: Outcome;
  similarity_pct: number | null;
  latency_ms: number | null;
}

export interface VerdictChange {
  case_key: string;
  from_stamp: string;
  to_stamp: string;
  from_verdict: string | null;
  to_verdict: string | null;
  from_outcome: Outcome;
  to_outcome: Outcome;
}

export interface TrendSummary {
  runs: number;
  status: "no_runs" | "single_run" | "ok";
  note: string;
  latest_stamp: string | null;
  previous_stamp: string | null;
  direction: "improving" | "declining" | "stable" | null;
  pass_rate_change_pts: number | null;
  passed_change: number | null;
  failed_change: number | null;
  newly_failing: string[];
  newly_passing: string[];
}

export interface Summary {
  runs_total: number;
  runs_completed: number;
  cases_selected: number;
  cases_completed: number;
  cases_executed: number;
  passed: number;
  failed: number;
  other: number;
  pass_rate_pct: number | null;
}

export interface FlakyCase {
  case_key: string;
  runs: number;
  flips: number;
  passed: number;
  failed: number;
  other: number;
  latest_outcome: Outcome;
}

export interface AiSection<T> {
  status: "ok" | "skipped" | "error";
  reason?: string;
  error?: string;
  items: T[];
}

export interface ChangeExplanation extends VerdictChange {
  id: string;
  model: string;
  generated_at: string;
  explanation: string;
  differences: string[];
  evidence_before: string[];
  evidence_after: string[];
  evidence_dropped: number;
  confidence: "low" | "medium" | "high";
}

export interface FlakyAnalysis {
  id: string;
  case_key: string;
  model: string;
  generated_at: string;
  pattern: string;
  explanation: string;
  evidence: string[];
  evidence_dropped: number;
  suggested_action: string;
  confidence: "low" | "medium" | "high";
}

export interface CausesOfRun {
  stamp: string;
  analysed: boolean;
  failed_cases: number;
  failed_by_cause: Record<string, number>;
}

export interface AiAnalytics {
  causes_by_run: CausesOfRun[];
  changes: AiSection<ChangeExplanation>;
  flaky: AiSection<FlakyAnalysis>;
}

export interface AskAnswer {
  answer: string;
  referenced_cases: { case_id: string; stamp: string; excel_row: number | null; utterance: string | null }[];
  model: string;
  coverage: string;
}

export interface TrendAi {
  status: "ok" | "skipped" | "error";
  reason?: string;
  error?: string;
  model?: string;
  generated_at?: string;
  headline?: string;
  narrative?: string;
  notable_changes?: string[];
}

export interface Report {
  schema_version: number;
  created_at: string;
  updated_at: string;
  policy: string;
  outcome_rules: { pass: string[]; fail: string[] };
  summary: Summary;
  runs: Run[];
  trend: {
    summary: TrendSummary;
    points: TrendPoint[];
    case_history: Record<string, CaseHistoryEntry[]>;
    changes: VerdictChange[];
    flaky_cases: FlakyCase[];
    failing_streaks: Record<string, number>;
  };
  ai_trend: TrendAi;
  ai_analytics: AiAnalytics;
}
