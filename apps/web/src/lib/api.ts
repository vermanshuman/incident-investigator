export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Incident = {
  id: string;
  title: string;
  description: string;
  severity: "low" | "medium" | "high" | "critical";
  status: string;
  source: string;
  created_at: string;
};

export type Run = {
  id: string;
  incident_id: string;
  status: string;
  step_count: number;
  token_count: number;
  cost_usd: number;
  started_at: string | null;
  finished_at: string | null;
};

export type RunEvent = {
  seq: number;
  type: "node" | "tool_call" | "hypothesis_update" | "approval";
  payload: Record<string, unknown>;
  ts: string;
};

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

export const api = {
  incidents: () => json<Incident[]>("/incidents"),
  incident: (id: string) => json<Incident>(`/incidents/${id}`),
  investigate: (id: string) => json<Run>(`/incidents/${id}/investigate`, { method: "POST" }),
  run: (id: string) => json<Run>(`/runs/${id}`),
  runEvents: (id: string) => json<RunEvent[]>(`/runs/${id}/events`),
  streamUrl: (id: string) => `${API_URL}/runs/${id}/stream`,
};
