export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Severity = "low" | "medium" | "high" | "critical";

export type Incident = {
  id: string;
  title: string;
  description: string;
  severity: Severity;
  status: string;
  source: string;
  created_at: string;
  latest_run_id: string | null;
};

export type Run = {
  id: string;
  incident_id: string;
  status: string;
  thread_id: string;
  started_at: string | null;
  finished_at: string | null;
  step_count: number;
  token_count: number;
  llm_calls: number;
  cost_usd: number;
  stop_reason: string | null;
  error: string | null;
  replayed: boolean;
};

export type Citation = { tool: string; source_ref: string; excerpt: string };

export type Hypothesis = {
  id: string;
  statement: string;
  category: string;
  status: "open" | "confirmed" | "refuted" | "inconclusive";
  confidence: number;
  evidence_for: Citation[];
  evidence_against: Citation[];
};

export type ToolCall = {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  tests_hypothesis: string;
  why: string;
  summary: string;
  refs: string[];
  latency_ms: number;
  error: string | null;
};

/** One line on the live timeline. `tool_call` carries the evidence behind it. */
export type RunEvent = {
  seq: number;
  type?: string;
  ts?: string;
  node: string;
  note: string;
  tool_call?: ToolCall;
  hypotheses?: Hypothesis[];
  usage?: { calls: number; input_tokens: number; output_tokens: number; cost_usd: number };
  report?: AgentReport;
  stop_reason?: string;
  status?: string;
  error?: string | null;
};

/** The stored report, as the API returns it. */
export type Report = {
  root_cause: string;
  confidence: string;
  fix_proposal: string;
  unchecked_areas: string[];
  body_markdown: string;
  approved_by: string | null;
  github_issue_url: string | null;
};

/** The report as it arrives on a live event: the agent's own shape. */
export type AgentReport = {
  root_cause: string;
  confidence: string;
  fix: { summary: string; change: string; rollback: string };
  unchecked_areas: string[];
  is_external: boolean;
};

/** One shape for the UI, whichever side it came from. */
export type ReportView = {
  root_cause: string;
  confidence: string;
  fix: string;
  unchecked_areas: string[];
  is_external?: boolean;
};

export const asReportView = (r: Report | AgentReport | null | undefined): ReportView | null =>
  r
    ? {
        root_cause: r.root_cause,
        confidence: r.confidence,
        fix: "fix_proposal" in r ? r.fix_proposal : r.fix.summary,
        unchecked_areas: r.unchecked_areas,
        is_external: "is_external" in r ? r.is_external : undefined,
      }
    : null;

export type RunDetail = Run & {
  events: RunEvent[];
  hypotheses: Hypothesis[];
  report: Report | null;
};

export type DashboardStats = {
  org: string;
  plan: string;
  open_incidents: number;
  runs_awaiting_approval: number;
  completed_runs: number;
  failed_runs: number;
  avg_seconds_to_root_cause: number | null;
  avg_cost_usd: number | null;
  usage: {
    runs: number;
    run_limit: number;
    cost_usd: number;
    cost_limit_usd: number;
    tokens: number;
  };
};

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`);
  return res.json();
}

export const api = {
  incidents: () => json<Incident[]>("/incidents"),
  incident: (id: string) => json<Incident>(`/incidents/${id}`),
  createIncident: (body: { title: string; description: string; severity?: Severity }) =>
    json<Incident>("/incidents", { method: "POST", body: JSON.stringify(body) }),
  /** `replay` names a cassette, which runs the investigation with no API calls. */
  investigate: (id: string, replay?: string) =>
    json<Run>(`/incidents/${id}/investigate`, {
      method: "POST",
      body: JSON.stringify({ replay: replay ?? null }),
    }),
  run: (id: string) => json<RunDetail>(`/runs/${id}`),
  runs: () => json<Run[]>("/runs"),
  dashboard: () => json<DashboardStats>("/dashboard"),
  streamUrl: (id: string, lastSeq = 0) => `${API_URL}/runs/${id}/stream?last_seq=${lastSeq}`,
};

export const STATUS_COLOR: Record<string, string> = {
  confirmed: "var(--ok)",
  refuted: "var(--err)",
  inconclusive: "var(--warn)",
  open: "var(--muted)",
};
