"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, type Severity } from "@/lib/api";

/** Presets match the three fault scenarios the injector can produce. */
const PRESETS = [
  {
    label: "500s on checkout",
    title: "POST /checkout returning 500s",
    description: "Error rate on POST /checkout jumped to about 30% of requests a few minutes ago.",
  },
  {
    label: "Checkout slow / timing out",
    title: "Checkout is slow and some requests time out",
    description: "p95 latency on /checkout climbed sharply and some requests now time out.",
  },
  {
    label: "Payments failing",
    title: "Payments failing",
    description:
      "Every payment attempt fails with a gateway timeout. Checkout page loads fine. " +
      "Nothing was deployed today as far as we know.",
  },
];

export function NewIncidentForm() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState<Severity>("high");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createIncident({ title, description, severity });
      setOpen(false);
      setTitle("");
      setDescription("");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not create the incident");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="actions">
        <button className="btn" onClick={() => setOpen(true)}>Report incident</button>
      </div>
    );
  }

  return (
    <form className="card form" onSubmit={submit}>
      <div className="actions">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setTitle(p.title);
              setDescription(p.description);
            }}
          >
            {p.label}
          </button>
        ))}
      </div>
      <label>
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} />
      </label>
      <label>
        What are you seeing?
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} required rows={3} />
      </label>
      <label>
        Severity
        <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
          {["low", "medium", "high", "critical"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="btn" type="submit" disabled={busy}>{busy ? "Saving…" : "Create"}</button>
        <button className="btn btn-ghost" type="button" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  );
}
