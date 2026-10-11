import Link from "next/link";
import { api, isAuthError } from "@/lib/api";
import { RunLoader } from "@/components/RunLoader";

export const dynamic = "force-dynamic";

export default async function RunDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Rendered on the server when the session is visible there; the loader
  // fetches again in the browser, which is also the signed-out path.
  const run = await api.run(id).catch((e) => (isAuthError(e) ? null : null));
  const incident = run ? await api.incident(run.incident_id).catch(() => null) : null;

  return (
    <>
      <h1>{incident?.title ?? "Investigation"}</h1>
      <p className="muted">
        {run && <><Link href={`/incidents/${run.incident_id}`}>back to incident</Link> · </>}
        run {id.slice(0, 8)}
      </p>
      <RunLoader runId={id} />
    </>
  );
}
