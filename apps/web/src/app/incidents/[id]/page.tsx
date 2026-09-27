import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { InvestigateButton } from "@/components/InvestigateButton";

export const dynamic = "force-dynamic";

export default async function IncidentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const incident = await api.incident(id).catch(() => null);
  if (!incident) notFound();

  return (
    <>
      <h1>{incident.title}</h1>
      <p className="muted">
        {incident.severity} · <span className={`pill pill-${incident.status}`}>
          {incident.status.replace("_", " ")}
        </span> · reported {new Date(incident.created_at).toLocaleString()} · {incident.source}
      </p>
      <div className="card">
        <p className="pre">{incident.description}</p>
        <InvestigateButton incidentId={incident.id} />
        {incident.latest_run_id && (
          <p className="muted">
            Previous: <Link href={`/runs/${incident.latest_run_id}`}>latest run</Link>
          </p>
        )}
      </div>
    </>
  );
}
