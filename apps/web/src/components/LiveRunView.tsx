"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  asReportView,
  STATUS_COLOR,
  type Hypothesis,
  type ReportView,
  type Report,
  type RunDetail,
  type RunEvent,
  type UserInfo,
} from "@/lib/api";
import { ApprovalPanel } from "./ApprovalPanel";
import { EvidencePanel } from "./EvidencePanel";
import { HypothesesPanel } from "./HypothesesPanel";

const NODE_LABEL: Record<string, string> = {
  intake: "Parsed incident",
  triage: "Triaged",
  generate_hypotheses: "Formed hypotheses",
  decide: "Reasoned",
  run_tool: "Gathered evidence",
  write_report: "Wrote report",
  create_github_issue: "GitHub issue",
  finished: "Finished",
};

/**
 * The live investigation: a timeline on the left that fills in as the agent
 * works, evidence on the right. Subscribes to the run's SSE stream and asks
 * only for events it has not seen, so a refresh mid-run loses nothing.
 */
export function LiveRunView({ initial }: { initial: RunDetail }) {
  const [events, setEvents] = useState<RunEvent[]>(initial.events);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>(initial.hypotheses);
  const [usage, setUsage] = useState(
    { calls: initial.llm_calls, tokens: initial.token_count, cost: initial.cost_usd },
  );
  const [status, setStatus] = useState(initial.status);
  const [report, setReport] = useState<ReportView | null>(asReportView(initial.report));
  const [selected, setSelected] = useState<number | null>(null);
  const [live, setLive] = useState(false);
  const [stored, setStored] = useState<Report | null>(initial.report);
  const [issueUrl, setIssueUrl] = useState<string | null>(initial.report?.github_issue_url ?? null);
  // The session cookie lives in the browser, so the reviewer is resolved here
  // rather than during server rendering.
  const [user, setUser] = useState<UserInfo | null>(null);
  const timelineEnd = useRef<HTMLDivElement>(null);

  const lastSeq = useMemo(
    () => events.reduce((max, e) => Math.max(max, e.seq), 0),
    [events],
  );
  // The stream is opened once per run; lastSeq is read at that moment only.
  const seqRef = useRef(lastSeq);
  seqRef.current = lastSeq;

  const refreshUser = useCallback(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  const refreshRun = useCallback(() => {
    api.run(initial.id).then((fresh) => {
      setStatus(fresh.status);
      setStored(fresh.report);
      setReport(asReportView(fresh.report));
      setIssueUrl(fresh.report?.github_issue_url ?? null);
      setEvents(fresh.events);
    }).catch(() => undefined);
  }, [initial.id]);

  useEffect(refreshUser, [refreshUser]);

  useEffect(() => {
    const source = new EventSource(api.streamUrl(initial.id, seqRef.current));
    source.onopen = () => setLive(true);

    source.addEventListener("run", (message) => {
      const event = JSON.parse((message as MessageEvent).data) as RunEvent;
      setEvents((prev) => (prev.some((e) => e.seq === event.seq) ? prev : [...prev, event]));
      if (event.hypotheses) setHypotheses(event.hypotheses);
      if (event.usage) {
        setUsage({
          calls: event.usage.calls,
          tokens: event.usage.input_tokens + event.usage.output_tokens,
          cost: event.usage.cost_usd,
        });
      }
      if (event.report) setReport(asReportView(event.report));
      if (event.github_issue_url) setIssueUrl(event.github_issue_url);
      if (event.status) setStatus(event.status);
    });

    source.addEventListener("end", () => {
      setLive(false);
      source.close();
      // Pull the stored report and final totals once the run stops.
      api.run(initial.id).then((fresh) => {
        setHypotheses(fresh.hypotheses);
        setStatus(fresh.status);
        setStored(fresh.report);
        setReport(asReportView(fresh.report));
        setIssueUrl(fresh.report?.github_issue_url ?? null);
        setUsage({ calls: fresh.llm_calls, tokens: fresh.token_count, cost: fresh.cost_usd });
      }).catch(() => undefined);
    });

    source.onerror = () => setLive(false);
    return () => source.close();
  }, [initial.id]);

  useEffect(() => {
    timelineEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [events.length]);

  const selectedEvent = events.find((e) => e.seq === selected) ?? null;
  const running = status === "running" || status === "queued";


  return (
    <>
      <div className="runbar">
        <span className={`pill pill-${status}`}>{status.replace("_", " ")}</span>
        {live && running && <span className="livedot" aria-label="streaming" />}
        {initial.replayed && <span className="pill">replay · no API calls</span>}
        <span className="muted">
          {usage.calls} model calls · {usage.tokens.toLocaleString()} tokens ·{" "}
          {usage.cost > 0 ? `$${usage.cost.toFixed(4)}` : "$0.00"}
        </span>
        {initial.stop_reason && <span className="muted">stopped: {initial.stop_reason}</span>}
      </div>

      {initial.error && <div className="card error">Run failed: {initial.error}</div>}

      {issueUrl && (
        <div className="card ok">
          Issue filed: <a href={issueUrl} target="_blank" rel="noreferrer">{issueUrl}</a>
        </div>
      )}

      {status === "awaiting_approval" && stored && (
        <ApprovalPanel
          runId={initial.id}
          report={stored}
          user={user}
          onSignedIn={refreshUser}
          onDecided={() => window.setTimeout(refreshRun, 1200)}
        />
      )}

      <div className="runlayout">
        <section className="card timeline" aria-label="Investigation timeline">
          <h2>Timeline</h2>
          <ol>
            {events.map((event) => {
              const isTool = Boolean(event.tool_call);
              return (
                <li key={event.seq}>
                  <button
                    type="button"
                    className={`step ${selected === event.seq ? "step-on" : ""}`}
                    onClick={() => setSelected(selected === event.seq ? null : event.seq)}
                    aria-expanded={selected === event.seq}
                  >
                    <span className="tick">{isTool ? "◆" : "✓"}</span>
                    <span className="steptext">
                      <strong>{NODE_LABEL[event.node] ?? event.node}</strong>
                      {event.note && event.note !== NODE_LABEL[event.node] && (
                        <span className="muted"> — {event.note}</span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
            {running && (
              <li className="thinking">
                <span className="tick">◌</span> investigating…
              </li>
            )}
          </ol>
          <div ref={timelineEnd} />
          {events.length === 0 && <p className="muted">Waiting for the first step…</p>}
        </section>

        <div className="side">
          <HypothesesPanel hypotheses={hypotheses} />
          <EvidencePanel event={selectedEvent} report={report} />
        </div>
      </div>
    </>
  );
}

export { STATUS_COLOR };
