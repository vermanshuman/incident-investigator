"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type ApiKeyInfo,
  type Member,
  type OrgDetail,
  type Role,
  type UserInfo,
} from "@/lib/api";
import { SignInForm } from "./ApprovalPanel";

const ROLES: Role[] = ["owner", "admin", "approver", "viewer"];

export function SettingsView() {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [org, setOrg] = useState<OrgDetail | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    const me = await api.me().catch(() => null);
    setUser(me);
    if (!me) {
      setLoaded(true);
      return;
    }
    setOrg(await api.org().catch(() => null));
    setMembers(await api.members().catch(() => []));
    // Only admins and owners may list keys; a 403 here is expected, not an error.
    setKeys(await api.apiKeys().catch(() => []));
    setLoaded(true);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (!loaded) return <div className="card muted">Loading…</div>;

  if (!user) {
    return (
      <section className="card">
        <h2>Sign in</h2>
        <p className="muted">Sign in to see your organization. Leave the organization blank to join the demo org.</p>
        <SignInForm onDone={load} withOrg />
      </section>
    );
  }

  const canManage = user.role === "owner";
  const canAdmin = user.role === "owner" || user.role === "admin";

  return (
    <>
      {notice && <div className="card ok">{notice}</div>}

      <section className="card">
        <h2>Organization</h2>
        <p>
          <strong>{org?.name}</strong> <span className="muted">({org?.slug})</span> ·{" "}
          you are <span className="badge">{user.role}</span>
        </p>
        {user.orgs.length > 1 && (
          <div className="actions">
            <span className="muted">Switch:</span>
            {user.orgs.map((o) => (
              <button
                key={o.id}
                className="btn btn-ghost"
                disabled={o.id === user.org.id}
                onClick={async () => {
                  await api.switchOrg(o.id);
                  await load();
                }}
              >
                {o.name}
              </button>
            ))}
          </div>
        )}
      </section>

      {org && <UsageCard org={org} />}
      {org && <PlansCard org={org} canManage={canManage} onDone={async (m) => { setNotice(m); await load(); }} />}

      <MembersCard members={members} seatLimit={org?.seat_limit ?? 0} canManage={canManage}
                   onDone={load} />

      {canAdmin && <ApiKeysCard keys={keys} onDone={load} />}
    </>
  );
}

function UsageCard({ org }: { org: OrgDetail }) {
  const u = org.usage;
  const pct = Math.min(100, Math.round((u.runs / Math.max(1, u.run_limit)) * 100));
  const since = new Date(u.period_start).toLocaleDateString();
  return (
    <section className="card">
      <h2>Usage since {since}</h2>
      <p className="muted">
        {u.runs} of {u.run_limit} investigations · ${u.cost_usd.toFixed(4)} of $
        {u.cost_limit_usd.toFixed(2)} · {u.tokens.toLocaleString()} tokens
      </p>
      <div className="meter" aria-label={`${pct}% of the run limit used`}>
        <span style={{ width: `${pct}%`, background: u.over_run_limit ? "var(--err)" : undefined }} />
      </div>
      {(u.over_run_limit || u.over_cost_limit) && (
        <p className="error">
          Limit reached — new investigations are blocked until the next period or an upgrade.
          Replays still work, because they call no model.
        </p>
      )}
    </section>
  );
}

function PlansCard({
  org, canManage, onDone,
}: { org: OrgDetail; canManage: boolean; onDone: (message: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);

  async function change(plan: string) {
    setBusy(plan);
    try {
      const result = await api.changePlan(plan);
      if (result.checkout_url) {
        window.location.href = result.checkout_url;
        return;
      }
      onDone(result.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card">
      <h2>Plan</h2>
      <div className="plans">
        {org.plans.map((p) => (
          <div key={p.key} className={`plan ${p.current ? "plan-on" : ""}`}>
            <strong>{p.name}</strong>
            <span className="statvalue">
              {p.price_usd_month === 0 ? "Free" : `$${p.price_usd_month}`}
              {p.price_usd_month > 0 && <span className="muted"> /mo</span>}
            </span>
            <p className="muted">{p.blurb}</p>
            <p className="muted">
              {p.monthly_run_limit} runs · ${p.monthly_cost_limit_usd.toFixed(0)} spend · {p.seats} seats
            </p>
            {p.current ? (
              <span className="badge">current</span>
            ) : (
              <button className="btn" disabled={!canManage || busy !== null} onClick={() => change(p.key)}>
                {busy === p.key ? "Working…" : p.price_usd_month > 0 ? "Upgrade" : "Downgrade"}
              </button>
            )}
          </div>
        ))}
      </div>
      {!canManage && <p className="muted">Only an owner can change the plan.</p>}
    </section>
  );
}

function MembersCard({
  members, seatLimit, canManage, onDone,
}: { members: Member[]; seatLimit: number; canManage: boolean; onDone: () => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("approver");
  const [error, setError] = useState<string | null>(null);

  return (
    <section className="card">
      <h2>Members ({members.length} of {seatLimit} seats)</h2>
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th></tr></thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.user_id}>
              <td>{m.name}</td>
              <td className="muted">{m.email ?? "—"}</td>
              <td><span className="badge">{m.role}</span></td>
              <td className="muted">{new Date(m.joined).toLocaleDateString()}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {canManage && (
        <form
          className="actions"
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            try {
              await api.inviteMember(name.trim(), role);
              setName("");
              onDone();
            } catch (err) {
              setError(err instanceof Error ? err.message : "could not add the member");
            }
          }}
        >
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="name"
                 required style={{ maxWidth: 200 }} />
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button className="btn" type="submit">Add member</button>
          {error && <span className="error">{error}</span>}
        </form>
      )}
    </section>
  );
}

function ApiKeysCard({ keys, onDone }: { keys: ApiKeyInfo[]; onDone: () => void }) {
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(null);

  return (
    <section className="card">
      <h2>API keys</h2>
      <p className="muted">
        Let an alerting system open incidents without a browser. A key can start investigations but
        never approve one — that needs a person.
      </p>

      {secret && (
        <div className="card ok">
          <p>Copy this now; it is not shown again.</p>
          <pre>{secret}</pre>
          <pre>{`curl -X POST ${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/v1/incidents \\
  -H "Authorization: Bearer ${secret}" \\
  -H "content-type: application/json" \\
  -d '{"title":"Checkout 500s","description":"Error rate above 20% for 5 minutes"}'`}</pre>
        </div>
      )}

      {keys.length > 0 && (
        <table>
          <thead><tr><th>Name</th><th>Key</th><th>Last used</th><th /></tr></thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                <td><code>{k.prefix}…</code></td>
                <td className="muted">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
                <td>
                  {k.revoked ? <span className="muted">revoked</span> : (
                    <button className="btn btn-ghost" onClick={async () => { await api.revokeApiKey(k.id); onDone(); }}>
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <form
        className="actions"
        onSubmit={async (e) => {
          e.preventDefault();
          const created = await api.createApiKey(name.trim());
          setSecret(created.secret);
          setName("");
          onDone();
        }}
      >
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Grafana alerts"
               required style={{ maxWidth: 220 }} />
        <button className="btn" type="submit">Create key</button>
      </form>
    </section>
  );
}
