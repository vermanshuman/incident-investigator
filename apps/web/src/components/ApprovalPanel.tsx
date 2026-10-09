"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, type Report, type UserInfo } from "@/lib/api";

/**
 * The human gate. The agent has written a report and stopped; nothing is
 * filed until someone signs in and approves it, and the reviewer may correct
 * the report first - what they approve is what gets posted.
 */
export function ApprovalPanel({
  runId,
  report,
  user,
  onSignedIn,
  onDecided,
}: {
  runId: string;
  report: Report;
  user: UserInfo | null;
  onSignedIn: () => void;
  onDecided: () => void;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [rootCause, setRootCause] = useState(report.root_cause);
  const [fix, setFix] = useState(report.fix_proposal);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const edited = rootCause !== report.root_cause || fix !== report.fix_proposal;

  async function decide(approved: boolean) {
    setBusy(approved ? "approve" : "reject");
    setError(null);
    try {
      await api.decide(runId, {
        approved,
        ...(approved && edited ? { root_cause: rootCause, fix_summary: fix } : {}),
      });
      onDecided();
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "the decision could not be recorded");
      setBusy(null);
    }
  }

  if (!user) {
    return (
      <section className="card gate">
        <h2>Awaiting approval</h2>
        <p>
          The agent stopped before taking any action. Sign in to review and decide — approvals are
          recorded against your name.
        </p>
        <SignInForm onDone={onSignedIn} />
      </section>
    );
  }

  return (
    <section className="card gate" aria-label="Approval">
      <h2>Awaiting your approval</h2>
      <p className="muted">
        Approving opens a GitHub issue with this report. Nothing else is written, and the proposed
        fix is not applied.
      </p>

      {editing ? (
        <div className="form">
          <label>
            Root cause
            <textarea value={rootCause} onChange={(e) => setRootCause(e.target.value)} rows={3} />
          </label>
          <label>
            Proposed fix
            <textarea value={fix} onChange={(e) => setFix(e.target.value)} rows={2} />
          </label>
        </div>
      ) : (
        <>
          <p><strong>{rootCause}</strong></p>
          <p className="muted">Fix: {fix}</p>
        </>
      )}

      {edited && <p className="muted">Edited — your version is what will be filed.</p>}
      {error && <p className="error">{error}</p>}

      <div className="actions">
        <button className="btn" onClick={() => decide(true)} disabled={busy !== null}>
          {busy === "approve" ? "Filing…" : "Approve & open issue"}
        </button>
        <button className="btn btn-ghost" onClick={() => setEditing(!editing)} disabled={busy !== null}>
          {editing ? "Done editing" : "Edit"}
        </button>
        <button className="btn btn-ghost" onClick={() => decide(false)} disabled={busy !== null}>
          {busy === "reject" ? "Rejecting…" : "Reject"}
        </button>
        <span className="muted">signed in as {user.name}</span>
      </div>
    </section>
  );
}

export function SignInForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="actions"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await api.signin(name.trim());
          onDone();
        } finally {
          setBusy(false);
        }
      }}
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="your name"
        required
        style={{ maxWidth: 220 }}
      />
      <button className="btn" type="submit" disabled={busy || !name.trim()}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
