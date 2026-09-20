import { api } from "@/lib/api";
import { InvestigateButton } from "@/components/InvestigateButton";

export default async function IncidentDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const incident = await api.incident(id);
  return (
    <>
      <h1>{incident.title}</h1>
      <div className="card">
        <p>{incident.description}</p>
        <p className="muted">
          {incident.severity} · {incident.status} · {incident.source}
        </p>
        <InvestigateButton incidentId={incident.id} />
      </div>
    </>
  );
}
