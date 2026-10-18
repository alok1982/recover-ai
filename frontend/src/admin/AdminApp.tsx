/** CR-04: admin console (/admin). Needs the `role: admin` custom claim (checked by the server on every call). */
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useDemo } from "../lib/health";
import { DEMO_BANK_ID } from "../lib/demobank";
import { DemoRibbon } from "../ui/AppHeader";
import { AuthError } from "../lib/auth";
import { savedLang } from "../lib/prefs";
import { translate } from "../i18n";
import { ADMIN_EMAIL, staffApi, StaffApiError, staffMe, staffSignIn, staffSignOut, type AccessRequest, type RequestStatus, type StaffMe } from "../lib/staff";
import { Logo } from "../ui/Logo";

interface AuditEntry { id: string; at: string; actorEmail: string | null; action: string; targetUid: string; reason?: string | null; bankId?: string }
const TABS: RequestStatus[] = ["PENDING", "APPROVED", "REJECTED", "REVOKED"];

function suggestBankId(r: AccessRequest): string {
  const b = (r.bankName === "Other" ? r.bankOther : r.bankName) || "other";
  return `${r.country.toLowerCase()}-${b.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40)}`;
}

function Row({ r, onDone, demo }: { r: AccessRequest; onDone: (msg: string) => void; demo: boolean }) {
  // DEMO_MODE: approved staff always belong to the fictional demo bank (the server enforces it too)
  const [bankId, setBankId] = useState(demo ? DEMO_BANK_ID : r.bankId || suggestBankId(r));
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
            <input aria-label="bankId" value={bankId} readOnly={demo} title={demo ? "Demo: fixed to the fictional demo bank" : undefined} onChange={(e) => setBankId(e.target.value)} size={16} />
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

const LOGIN = "/admin/login?next=/admin";

/** /admin/login: email + password only. Non-admins are told "Admin access required" and signed out. */
export function AdminLogin() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [denied, setDenied] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const next = params.get("next");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null); setDenied(null);
    if (!email.trim() || !pw) return setErr("Email or password is incorrect.");
    setBusy(true);
    try {
      await staffSignIn(email, pw);
      const me = await staffMe(true);
      if (me.role === "admin") {
        nav(next && next.startsWith("/admin") && !next.startsWith("/admin/login") ? next : "/admin", { replace: true });
        return;
      }
      await staffSignOut();
      setDenied(me.email || email);
    } catch (x) {
      setErr(x instanceof AuthError && x.code === "throttled" ? translate(savedLang(), "errTooMany")
        : x instanceof AuthError && x.code === "bad_credentials" ? "Email or password is incorrect."
        : x instanceof Error ? x.message : "Something went wrong — please try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <DemoRibbon />
      <main className="bank-login admin-login" data-testid="admin-login">
        <div className="login-brand"><Logo variant="mark" height={44} /><h1>RecoverAI Admin</h1></div>
        <p className="muted">Admin console sign-in. Requires the admin role.</p>
        <form className="form" onSubmit={submit} noValidate>
          <label>Email<input name="email" type="email" autoComplete="username" placeholder={ADMIN_EMAIL} value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label>Password<input name="password" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
          {err && <p className="error" role="alert" data-testid="auth-error">{err}</p>}
          {denied && <p className="error" role="alert" data-testid="admin-required"><b>Admin access required.</b> {denied} is not an admin and has been signed out.</p>}
          <button className="btn primary cta" type="submit" disabled={busy}>Sign in</button>
        </form>
      </main>
    </>
  );
}

export function AdminApp() {
  const nav = useNavigate();
  const demo = useDemo();
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
      if (e instanceof AuthError || (e instanceof StaffApiError && e.status === 401)) nav(LOGIN, { replace: true });
      else setDenied(true);
    });
  }, []);
  const logout = async () => { await staffSignOut(); nav(LOGIN); };
  if (denied) {
    return (
      <>
      <DemoRibbon />
      <main className="landing staff-page" data-testid="admin-denied">
        <h2>Admin access required</h2>
        <p>{me?.email} does not have the admin role.</p>
        <button className="btn" onClick={logout}>Sign in as an admin</button>
      </main>
      </>
    );
  }
  if (!me) return <div className="loading">…</div>;
  return (
    <div className="bank admin" data-testid="admin-console">
      <DemoRibbon />
      <header className="top bank-top">
        <span className="brand small"><Logo height={30} /><span className="brand-sep">·</span><span className="brand-text">Admin console</span></span>
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
            <tbody>{rows.map((r) => <Row key={r.uid + r.status} r={r} demo={demo} onDone={(m) => { setFlash(m); refresh(); }} />)}</tbody>
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
