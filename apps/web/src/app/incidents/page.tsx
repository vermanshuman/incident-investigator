import Link from "next/link";
import { api } from "@/lib/api";
import { NewIncidentForm } from "@/components/NewIncidentForm";

export const dynamic = "force-dynamic";

export default async function IncidentsPage() {
  const incidents = await api.incidents().catch(() => []);
  return (
    <>
      <h1>Incidents</h1>
      <NewIncidentForm />
      <div className="card">
        {incidents.length === 0 ? (
          <p className="muted">
            No incidents yet. Break the target app with <code>python fault.py apply s01_null_check</code>,
            then report it above.
          </p>
        ) : (
          <table>
            <thead>
              <tr><th>Title</th><th>Severity</th><th>Status</th><th>Created</th><th /></tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr key={i.id}>
                  <td><Link href={`/incidents/${i.id}`}>{i.title}</Link></td>
                  <td>{i.severity}</td>
                  <td><span className={`pill pill-${i.status}`}>{i.status.replace("_", " ")}</span></td>
                  <td className="muted">{new Date(i.created_at).toLocaleString()}</td>
                  <td>{i.latest_run_id && <Link href={`/runs/${i.latest_run_id}`}>latest run</Link>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
