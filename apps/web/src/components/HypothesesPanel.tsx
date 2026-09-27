"use client";

import { STATUS_COLOR, type Hypothesis } from "@/lib/api";

const ORDER = { confirmed: 0, open: 1, inconclusive: 2, refuted: 3 } as const;

/** Confidence per hypothesis, updating live as evidence arrives. */
export function HypothesesPanel({ hypotheses }: { hypotheses: Hypothesis[] }) {
  if (hypotheses.length === 0) {
    return (
      <section className="card">
        <h2>Hypotheses</h2>
        <p className="muted">None yet.</p>
      </section>
    );
  }
  const sorted = [...hypotheses].sort((a, b) => ORDER[a.status] - ORDER[b.status]);

  return (
    <section className="card" aria-label="Hypotheses">
      <h2>Hypotheses</h2>
      <ul className="hyps">
        {sorted.map((h) => (
          <li key={h.id + h.statement} className={h.status === "refuted" ? "struck" : ""}>
            <div className="hyphead">
              <span className="badge" style={{ borderColor: STATUS_COLOR[h.status], color: STATUS_COLOR[h.status] }}>
                {h.status}
              </span>
              <span className="muted">{h.category}</span>
              <span className="conf">{Math.round(h.confidence * 100)}%</span>
            </div>
            <p>{h.statement}</p>
            <div className="meter" aria-hidden>
              <span style={{ width: `${Math.round(h.confidence * 100)}%`, background: STATUS_COLOR[h.status] }} />
            </div>
            {h.evidence_for.length > 0 && (
              <p className="refs">
                for: {h.evidence_for.map((c) => <code key={c.source_ref}>{c.source_ref}</code>)}
              </p>
            )}
            {h.evidence_against.length > 0 && (
              <p className="refs">
                against: {h.evidence_against.map((c) => <code key={c.source_ref}>{c.source_ref}</code>)}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
