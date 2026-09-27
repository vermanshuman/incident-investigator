import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat">
      <span className="statlabel">{label}</span>
      <strong className="statvalue">{value}</strong>
      {hint && <span className="muted">{hint}</span>}
    </div>
  );
}

export default async function Dashboard() {
  const stats = await api.dashboard().catch(() => null);
  if (!stats) {
    return (
      <>
        <h1>Dashboard</h1>
        <div className="card error">API unreachable. Start it with <code>python dev.py</code>.</div>
      </>
    );
  }

  const { usage } = stats;
  const runPct = Math.min(100, Math.round((usage.runs / Math.max(1, usage.run_limit)) * 100));

  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">{stats.org} · {stats.plan} plan</p>

      <div className="stats">
        <Stat label="Open incidents" value={String(stats.open_incidents)} />
        <Stat label="Awaiting approval" value={String(stats.runs_awaiting_approval)} />
        <Stat
          label="Avg time to root cause"
          value={stats.avg_seconds_to_root_cause ? `${stats.avg_seconds_to_root_cause}s` : "—"}
        />
        <Stat
          label="Avg cost per run"
          value={stats.avg_cost_usd ? `$${stats.avg_cost_usd.toFixed(4)}` : "$0.00"}
          hint="replays are free"
        />
      </div>

      <section className="card">
        <h2>Usage this period</h2>
        <p className="muted">
          {usage.runs} of {usage.run_limit} runs · ${usage.cost_usd.toFixed(4)} of $
          {usage.cost_limit_usd.toFixed(2)} · {usage.tokens.toLocaleString()} tokens
        </p>
        <div className="meter" aria-label={`${runPct}% of run limit used`}>
          <span style={{ width: `${runPct}%` }} />
        </div>
      </section>

      <section className="card">
        <h2>Next</h2>
        <p>
          Pick an <Link href="/incidents">incident</Link> and click Investigate, or watch a past{" "}
          <Link href="/runs">run</Link>.
        </p>
      </section>
    </>
  );
}
