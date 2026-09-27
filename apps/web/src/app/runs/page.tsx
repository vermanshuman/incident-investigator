import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RunsPage() {
  const runs = await api.runs().catch(() => []);
  return (
    <>
      <h1>Agent Runs</h1>
      <div className="card">
        {runs.length === 0 ? (
          <p className="muted">No runs yet.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Run</th><th>Status</th><th>Steps</th><th>Calls</th><th>Cost</th><th>Started</th></tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td><Link href={`/runs/${r.id}`}>{r.id.slice(0, 8)}</Link></td>
                  <td>
                    <span className={`pill pill-${r.status}`}>{r.status.replace("_", " ")}</span>
                    {r.replayed && <span className="pill">replay</span>}
                  </td>
                  <td>{r.step_count}</td>
                  <td>{r.llm_calls}</td>
                  <td>{r.cost_usd > 0 ? `$${r.cost_usd.toFixed(4)}` : "$0.00"}</td>
                  <td className="muted">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
