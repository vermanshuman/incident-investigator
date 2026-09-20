import { api } from "@/lib/api";
import { LiveRunView } from "@/components/LiveRunView";

export default async function RunDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await api.run(id);
  const events = await api.runEvents(id);
  return (
    <>
      <h1>Run {run.id.slice(0, 8)}</h1>
      <p className="muted">
        {run.status} · {run.step_count} steps · {run.token_count} tokens · ${run.cost_usd.toFixed(3)}
      </p>
      <LiveRunView runId={run.id} initialEvents={events} />
    </>
  );
}
