"use client";

import { useEffect, useState } from "react";
import { api, type RunEvent } from "@/lib/api";

/**
 * The killer demo (plan section 8): a timeline on the left, hypotheses and
 * evidence on the right. Subscribes to the SSE stream and appends events.
 */
export function LiveRunView({ runId, initialEvents }: { runId: string; initialEvents: RunEvent[] }) {
  const [events, setEvents] = useState<RunEvent[]>(initialEvents);
  const [selected, setSelected] = useState<RunEvent | null>(null);

  useEffect(() => {
    const es = new EventSource(api.streamUrl(runId));
    es.addEventListener("event", (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as RunEvent;
      setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [...prev, ev]));
    });
    return () => es.close();
  }, [runId]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <div className="card">
        <strong>Timeline</strong>
        <ul style={{ listStyle: "none", padding: 0, margin: "12px 0 0" }}>
          {events.length === 0 && <li className="muted">Waiting for events…</li>}
          {events.map((ev) => (
            <li key={ev.seq} style={{ padding: "6px 0", cursor: "pointer" }} onClick={() => setSelected(ev)}>
              <span className="muted">[{ev.type}]</span> {String(ev.payload.label ?? ev.payload.node ?? "")}
            </li>
          ))}
        </ul>
      </div>
      <div className="card">
        <strong>Evidence</strong>
        <pre style={{ whiteSpace: "pre-wrap", marginTop: 12 }}>
          {selected ? JSON.stringify(selected.payload, null, 2) : "Click a step to see its evidence."}
        </pre>
      </div>
    </div>
  );
}
