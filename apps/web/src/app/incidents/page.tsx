import Link from "next/link";
import { api } from "@/lib/api";

export default async function IncidentsPage() {
  const incidents = await api.incidents().catch(() => []);
  return (
    <>
      <h1>Incidents</h1>
      <div className="card">
        {incidents.length === 0 ? (
          <p className="muted">No incidents yet. Inject a fault on the target app to create one.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Title</th><th>Severity</th><th>Status</th><th>Created</th></tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr key={i.id}>
                  <td><Link href={`/incidents/${i.id}`}>{i.title}</Link></td>
                  <td>{i.severity}</td>
                  <td>{i.status}</td>
                  <td className="muted">{new Date(i.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
