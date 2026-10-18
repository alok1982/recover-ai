/** CR-04: admin console (/admin). Needs the `role: admin` custom claim (checked by the server on every call). */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AuthError } from "../lib/auth";
import { staffApi, StaffApiError, staffMe, staffSignOut, type AccessRequest, type RequestStatus, type StaffMe } from "../lib/staff";

interface AuditEntry { id: string; at: string; actorEmail: string | null; action: string; targetUid: string; reason?: string | null; bankId?: string }
const TABS: RequestStatus[] = ["PENDING", "APPROVED", "REJECTED", "REVOKED"];

function suggestBankId(r: AccessRequest): string {
  const b = (r.bankName === "Other" ? r.bankOther : r.bankName) || "other";
  return `${r.country.toLowerCase()}-${b.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40)}`;
}

function Row({ r, onDone }: { r: AccessRequest; onDone: (msg: string) => void }) {
  const [bankId, setBankId] = useState(r.bankId || suggestBankId(r));
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const act = async (path: string, body: unknown, msg: string) => {
    setErr(null);
    try { await staffApi("POST", path, body); onDone(msg); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <tr data-testid={`req-${r.uid}`}>
      <td><b>{r.fullName}</b><br /><span className="small muted">{r.email}</span></td>
      <td>{r.bankName === "Other" ? `${r.bankOther} (Other)` : r.bankName}<br /><span className="small muted">{r.country}</span></td>
      <td>{r.employeeId}<br /><span className="small muted">{r.designation}</span></td>
      <td className="small">{r.note || "—"}</td>
      <td className="small">{r.createdAt ? new Date(r.createdAt).toLocaleString() : ""}{r.decidedBy && <><br />by {r.decidedBy}</>}
        {r.reason && <><br /><i>“{r.reason}”</i></>}{r.bankId && <><br /><code>{r.bankId}</code></>}</td>
      <td className="actions">
        {r.status !== "APPROVED" && (
          <div className="row">
            <input aria-label="bankId" value={bankId} onChange={(e) => setBankId(e.target.value)} size={16} />
            <button className="btn primary" data-testid="approve" onClick={() => act(`/api/admin/bank-requests/${r.uid}/approve`, { bankId }, `Approved ${r.email} (${bankId})`)}>Approve</button>
          </div>
        )}
        {(r.status === "PENDING" || r.status === "APPROVED") && (
          <div className="row">
            <input aria-label="reason" placeholder={r.status === "PENDING" ? "Reason (required)" : "Reason"} value={reason} onChange={(e) => setReason(e.target.value)} size={16} />
            {r.status === "PENDING" && <button className="btn" data-testid="reject" disabled={reason.trim().length < 3}
              onClick={() => act(`/api/admin/bank-requests/${r.uid}/reject`, { reason }, `Rejected ${r.email}`)}>Reject</button>}
            {r.status === "APPROVED" && <button className="btn danger" data-testid="revoke"
              onClick={() => act(`/api/admin/users/${r.uid}/revoke-bank`, { reason: reason || undefined }, `Revoked ${r.email}`)}>Revoke</button>}
          </div>
        )}
        {err && <p className="error small">{err}</p>}
      </td>
    </tr>
  );
}

export function AdminApp() {
  const nav = useNavigate();
  const [me, setMe] = useState<StaffMe | null>(null);
  const [denied, setDenied] = useState(false);
  const [tab, setTab] = useState<RequestStatus>("PENDING");
  const [rows, setRows] = useState<AccessRequest[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [flash, setFlash] = useState<string | null>(null);
  const refresh = async (s = tab) => {
    const [l, a] = await Promise.all([
      staffApi<{ requests: AccessRequest[]; counts: Record<string, number> }>("GET", `/api/admin/bank-requests?status=${s}`),
      staffApi<{ entries: AuditEntry[] }>("GET", "/api/admin/audit?limit=30"),
    ]);
    setRows(l.requests); setCounts(l.counts); setAudit(a.entries);
  };
  useEffect(() => {
    staffMe(true).then((m) => {
      setMe(m);
      if (m.role !== "admin") { setDenied(true); return; }
      refresh();
    }).catch((e) => {
      if (e instanceof AuthError || (e instanceof StaffApiError && e.status === 401)) nav("/login?role=bank&next=/admin", { replace: true });
      else setDenied(true);
    });
  }, []);
  const logout = async () => { await staffSignOut(); nav("/login?role=bank&next=/admin"); };
  if (denied) {
    return (
      <main className="landing staff-page" data-testid="admin-denied">
        <h2>Admin access required</h2>
        <p>{me?.email} does not have the admin role.</p>
        <button className="btn" onClick={logout}>Sign in as an admin</button>
      </main>
    );
  }
  if (!me) return <div className="loading">…</div>;
  return (
    <div className="bank admin" data-testid="admin-console">
      <header className="top bank-top">
        <span className="brand small">🛡️ RecoverAI · Admin console</span>
        <nav className="row"><span className="muted">{me.email}</span><button className="link" onClick={logout}>Sign out</button></nav>
      </header>
      <main className="admin-main">
        <h2>Bank access requests</h2>
        <div className="tabs row">
          {TABS.map((s) => (
            <button key={s} className={`tab ${tab === s ? "on" : ""}`} data-testid={`tab-${s}`} onClick={() => { setTab(s); refresh(s); }}>
              {s.charAt(0) + s.slice(1).toLowerCase()} <span className="badge">{counts[s] ?? 0}</span>
            </button>
          ))}
        </div>
        {flash && <p className="flash" data-testid="admin-flash">{flash}</p>}
        {rows.length === 0 ? <p className="muted">No {tab.toLowerCase()} requests.</p> : (
          <table className="table admin-table">
            <thead><tr><th>Applicant</th><th>Bank</th><th>Employee ID / designation</th><th>Note</th><th>Dates</th><th>Action</th></tr></thead>
            <tbody>{rows.map((r) => <Row key={r.uid + r.status} r={r} onDone={(m) => { setFlash(m); refresh(); }} />)}</tbody>
          </table>
        )}
        <h3>Audit log</h3>
        <table className="table audit-table" data-testid="audit-log">
          <thead><tr><th>When</th><th>Who</th><th>What</th><th>Target</th><th>Reason</th></tr></thead>
          <tbody>{audit.map((a) => (
            <tr key={a.id}><td className="small">{new Date(a.at).toLocaleString()}</td><td className="small">{a.actorEmail}</td>
              <td>{a.action}{a.bankId ? ` (${a.bankId})` : ""}</td><td className="small"><code>{a.targetUid.slice(0, 10)}</code></td><td className="small">{a.reason || ""}</td></tr>
          ))}</tbody>
        </table>
        <p className="small muted">Approving sets the custom claim <code>role: bank</code> and <code>bankId</code>; the applicant gets the bank desk at their next sign-in or “Check again”. Revoke removes the claim and ends their sessions at once.</p>
      </main>
    </div>
  );
}
