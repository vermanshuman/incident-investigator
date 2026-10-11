"use client";

import { useCallback, useEffect, useState } from "react";
import { api, isAuthError, type RunDetail } from "@/lib/api";
import { SignInForm } from "./ApprovalPanel";
import { LiveRunView } from "./LiveRunView";

/**
 * Loads the run in the browser.
 *
 * The page is server-rendered, but a visitor who is not signed in (or whose
 * session the server could not see) should be asked to sign in rather than
 * shown a 404.
 */
export function RunLoader({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.run(runId)
      .then((fresh) => {
        setRun(fresh);
        setNeedsAuth(false);
        setError(null);
      })
      .catch((e) => {
        if (isAuthError(e)) setNeedsAuth(true);
        else setError(e instanceof Error ? e.message : "could not load this run");
      });
  }, [runId]);

  useEffect(load, [load]);

  if (needsAuth) {
    return (
      <section className="card gate">
        <h2>Sign in to view this run</h2>
        <p className="muted">Runs belong to an organization, so they are not public.</p>
        <SignInForm onDone={load} />
      </section>
    );
  }
  if (error) return <div className="card error">{error}</div>;
  if (!run) return <div className="card muted">Loading run…</div>;
  return <LiveRunView initial={run} />;
}
