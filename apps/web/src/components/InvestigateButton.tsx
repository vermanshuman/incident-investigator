"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

export function InvestigateButton({ incidentId }: { incidentId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function start() {
    setBusy(true);
    try {
      const run = await api.investigate(incidentId);
      router.push(`/runs/${run.id}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="btn" onClick={start} disabled={busy}>
      {busy ? "Starting…" : "Investigate"}
    </button>
  );
}
