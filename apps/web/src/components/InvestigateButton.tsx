"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

const CASSETTES = [
  { value: "", label: "Live (calls the model)" },
  { value: "cassettes/s01_null_check.jsonl", label: "Replay: bad deploy" },
  { value: "cassettes/s03_pool_exhaustion.jsonl", label: "Replay: pool exhaustion" },
  { value: "cassettes/s08_provider_outage.jsonl", label: "Replay: provider outage" },
];

export function InvestigateButton({ incidentId }: { incidentId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [replay, setReplay] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const run = await api.investigate(incidentId, replay || undefined);
      router.push(`/runs/${run.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not start the run");
      setBusy(false);
    }
  }

  return (
    <div className="actions">
      <button className="btn" onClick={start} disabled={busy}>
        {busy ? "Starting…" : "Investigate"}
      </button>
      <select value={replay} onChange={(e) => setReplay(e.target.value)} disabled={busy}
              aria-label="Run mode">
        {CASSETTES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
      </select>
      {error && <span className="error">{error}</span>}
    </div>
  );
}
