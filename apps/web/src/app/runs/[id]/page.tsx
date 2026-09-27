import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { LiveRunView } from "@/components/LiveRunView";

export const dynamic = "force-dynamic";

export default async function RunDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await api.run(id).catch(() => null);
  if (!run) notFound();
  const incident = await api.incident(run.incident_id).catch(() => null);

  return (
    <>
      <h1>{incident?.title ?? `Run ${run.id.slice(0, 8)}`}</h1>
      <p className="muted">
        <Link href={`/incidents/${run.incident_id}`}>back to incident</Link> · run {run.id.slice(0, 8)}
      </p>
      <LiveRunView initial={run} />
    </>
  );
}
