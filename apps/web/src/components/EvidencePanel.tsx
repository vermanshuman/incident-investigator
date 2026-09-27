"use client";

import type { ReportView, RunEvent } from "@/lib/api";

/** What is behind a timeline step: the exact tool call and what it returned. */
export function EvidencePanel({ event, report }: { event: RunEvent | null; report: ReportView | null }) {
  if (event?.tool_call) {
    const tc = event.tool_call;
    return (
      <section className="card" aria-label="Evidence">
        <h2>Evidence</h2>
        <p className="muted">
          <code>{tc.tool}</code>({JSON.stringify(tc.args)}) · {tc.latency_ms.toFixed(0)}ms
          {tc.tests_hypothesis && <> · tests {tc.tests_hypothesis}</>}
        </p>
        <p className="why">{tc.why}</p>
        {tc.error && <p className="error">{tc.error}</p>}
        <pre>{tc.summary}</pre>
        {tc.refs.length > 0 && (
          <p className="refs">citable: {tc.refs.map((r) => <code key={r}>{r}</code>)}</p>
        )}
      </section>
    );
  }

  if (event) {
    return (
      <section className="card" aria-label="Evidence">
        <h2>Step {event.seq}</h2>
        <p>{event.note}</p>
        <p className="muted">This step reasoned over evidence already gathered; it called no tool.</p>
      </section>
    );
  }

  if (report) {
    return (
      <section className="card" aria-label="Report">
        <h2>Root cause</h2>
        <p><strong>{report.root_cause}</strong></p>
        <p className="muted">
          confidence: {report.confidence}
          {report.is_external && <> · cause is external to our code</>}
        </p>
        <h3>Proposed fix</h3>
        <p>{report.fix || "—"}</p>
        {report.unchecked_areas.length > 0 && (
          <>
            <h3>Not checked</h3>
            <ul className="muted">
              {report.unchecked_areas.map((u) => <li key={u}>{u}</li>)}
            </ul>
          </>
        )}
      </section>
    );
  }

  return (
    <section className="card">
      <h2>Evidence</h2>
      <p className="muted">Click a step to see the tool call and the raw output behind it.</p>
    </section>
  );
}
