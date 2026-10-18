/** CR-04: bank-staff signup (work email), staff login and the "Pending admin approval" page. Staff UI is English. */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthError } from "../lib/auth";
import { savedLang } from "../lib/prefs";
import { translate } from "../i18n";
import { passwordOk } from "../lib/phone";
import { useDemo } from "../lib/health";
import { DEMO_BANK_NAME } from "../lib/demobank";
import { DemoRibbon } from "../ui/AppHeader";
import { Logo } from "../ui/Logo";
import {
  requestBankAccess, routeStaff, staffDeleteAccount, staffMe, staffSignIn, staffSignOut, staffSignUp, StaffApiError,
  type StaffMe,
} from "../lib/staff";

const FALLBACK_BANKS: Record<string, string[]> = {
  IN: ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Punjab National Bank", "Bank of Baroda",
    "Kotak Mahindra Bank", "Canara Bank", "Union Bank of India", "IndusInd Bank", "Yes Bank", "IDFC FIRST Bank",
    "Paytm Payments Bank", "Airtel Payments Bank"],
  MY: ["Maybank", "CIMB Bank", "Public Bank", "RHB Bank", "Hong Leong Bank", "AmBank", "Bank Islam", "BSN",
    "Bank Rakyat", "Alliance Bank", "OCBC Bank (Malaysia)", "UOB Malaysia"],
};
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function staffMsg(e: unknown): string {
  if (e instanceof AuthError) {
    if (e.code === "throttled") return translate(savedLang(), "errTooMany");
    return e.code === "bad_credentials" ? "Email or password is incorrect." : e.code === "exists"
      ? "An account with this email already exists. Sign in instead." : e.code === "weak"
      ? "Use at least 8 characters with a letter and a number." : "Network problem — please try again.";
  }
  if (e instanceof StaffApiError) return e.message;
  return "Something went wrong — please try again.";
}

export function BankSignupForm({ next }: { next: string | null }) {
  const nav = useNavigate();
  const [f, setF] = useState({ email: "", password: "", password2: "", fullName: "", country: "IN" as "IN" | "MY",
    bankName: "", bankOther: "", employeeId: "", designation: "", note: "" });
  const [ack, setAck] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.value });
  const demo = useDemo();
  const banks = demo ? [DEMO_BANK_NAME] : FALLBACK_BANKS[f.country];
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const problem = !EMAIL_RE.test(f.email.trim()) ? "Enter your work email."
      : /@phone\.recoverai\.app$/i.test(f.email.trim()) ? "Use your work email."
      : !passwordOk(f.password) ? "Use at least 8 characters with a letter and a number."
      : f.password !== f.password2 ? "The passwords do not match."
      : f.fullName.trim().length < 2 ? "Enter your full name."
      : !f.bankName ? "Pick your bank." : f.bankName === "Other" && !f.bankOther.trim() ? "Enter the bank name."
      : !f.employeeId.trim() ? "Enter your employee ID." : f.designation.trim().length < 2 ? "Enter your designation."
      : !ack ? "Please confirm the statement below." : null;
    if (problem) return setErr(problem);
    setBusy(true);
    setErr(null);
    try {
      await staffSignUp(f.email, f.password);
      await requestBankAccess({ fullName: f.fullName.trim(), country: f.country, bankName: f.bankName,
        bankOther: f.bankName === "Other" ? f.bankOther.trim() : undefined, employeeId: f.employeeId.trim(),
        designation: f.designation.trim(), note: f.note.trim() || undefined });
      nav(await routeStaff(next));
    } catch (x) {
      console.warn("bank signup failed", x);
      setErr(staffMsg(x));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="form" onSubmit={submit} noValidate data-testid="bank-signup">
      <p className="small muted">Bank staff accounts give no access until an admin approves them. Victims never see this data.</p>
      {demo && <p className="small demo-note" data-testid="demo-bank-note">Demo: the only bank here is <b>{DEMO_BANK_NAME}</b>. No real bank is connected.</p>}
      <label>Work email<input name="email" type="email" autoComplete="email" value={f.email} onChange={set("email")} /></label>
      <label>Password<input name="password" type="password" autoComplete="new-password" value={f.password} onChange={set("password")} /></label>
      <label>Confirm password<input name="password2" type="password" autoComplete="new-password" value={f.password2} onChange={set("password2")} /></label>
      <label>Full name<input name="fullName" autoComplete="name" maxLength={80} value={f.fullName} onChange={set("fullName")} /></label>
      <label>Country
        <select name="country" value={f.country} onChange={(e) => setF({ ...f, country: e.target.value as "IN" | "MY", bankName: "" })}>
          <option value="IN">🇮🇳 India</option><option value="MY">🇲🇾 Malaysia</option>
        </select>
      </label>
      <label>Bank
        <select name="bankName" value={f.bankName} onChange={set("bankName")}>
          <option value="">Choose your bank</option>
          {banks.map((b) => <option key={b} value={b}>{b}</option>)}
          {demo ? <option value="Other" disabled>Other – not available in demo</option> : <option value="Other">Other</option>}
        </select>
      </label>
      {f.bankName === "Other" && <label>Bank name<input name="bankOther" maxLength={80} value={f.bankOther} onChange={set("bankOther")} /></label>}
      <label>Employee ID<input name="employeeId" maxLength={40} value={f.employeeId} onChange={set("employeeId")} /></label>
      <label>Designation<input name="designation" maxLength={60} placeholder="e.g. Fraud analyst" value={f.designation} onChange={set("designation")} /></label>
      <label>Note for the admin (optional)<textarea name="note" maxLength={500} rows={2} value={f.note} onChange={set("note")} /></label>
      <label className="check"><input type="checkbox" name="ack" checked={ack} onChange={(e) => setAck(e.target.checked)} />
        <span>I work on this bank's fraud team. I understand an admin will verify my request and all access is logged.</span></label>
      {err && <p className="error" role="alert" data-testid="auth-error">{err}</p>}
      <button className="btn primary cta" type="submit" disabled={busy}>Request bank access</button>
    </form>
  );
}

export function StaffLoginForm({ next }: { next: string | null }) {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !pw) return setErr("Email or password is incorrect.");
    setBusy(true);
    setErr(null);
    try {
      await staffSignIn(email, pw);
      nav(await routeStaff(next));
    } catch (x) {
      setErr(staffMsg(x));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="form" onSubmit={submit} noValidate data-testid="staff-login">
      <label>Work email<input name="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Password<input name="password" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
      {err && <p className="error" role="alert" data-testid="auth-error">{err}</p>}
      <button className="btn primary cta" type="submit" disabled={busy}>Sign in</button>
      <p className="small muted">Bank staff and admins. You are taken to the bank desk, the admin console or your application status.</p>
    </form>
  );
}

/** "Pending admin approval": no bank data here — only the applicant's own request. */
export function PendingPage() {
  const nav = useNavigate();
  const [me, setMe] = useState<StaffMe | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const load = async (force: boolean) => {
    setChecking(true);
    try {
      const m = await staffMe(force);
      if (m.role === "bank" || m.role === "admin") return nav(await routeStaff(null), { replace: true });
      setMe(m);
      setErr(null);
    } catch (e) {
      if (e instanceof AuthError || (e instanceof StaffApiError && e.status === 401)) return nav("/login?role=bank&next=/pending", { replace: true });
      setErr(staffMsg(e));
    } finally {
      setChecking(false);
    }
  };
  useEffect(() => { load(false); }, []);
  const r = me?.request;
  const status = me?.requestStatus;
  return (
    <>
    <DemoRibbon />
    <main className="landing staff-page" data-testid="pending-page">
      <header className="row staff-top"><span className="brand small"><Logo height={30} /><span className="brand-sep">·</span><b className="brand-text">Bank staff</b></span>
        <button className="link" data-testid="staff-logout" onClick={async () => { await staffSignOut(); nav("/"); }}>Log out</button></header>
      {!me && !err && <p className="loading">…</p>}
      {err && <p className="error">{err}</p>}
      {me && (
        <section className="card pending-card">
          {status === "PENDING" && <><h2 data-testid="pending-title">⏳ Pending admin approval</h2>
            <p>Thanks{r ? `, ${r.fullName.split(" ")[0]}` : ""}. An admin will check your request. You will get the bank desk once it is approved. Until then this account cannot see any bank or victim data.</p></>}
          {status === "REJECTED" && <><h2 data-testid="pending-title">✖ Request not approved</h2>
            <p>Reason: <b>{r?.reason || "—"}</b></p></>}
          {status === "REVOKED" && <><h2 data-testid="pending-title">⛔ Bank access revoked</h2>
            <p>Your bank desk access was removed by an admin.{r?.reason ? <> Reason: <b>{r.reason}</b></> : null}</p></>}
          {!status && <><h2 data-testid="pending-title">No bank access request</h2><p>This account has no request on file.</p></>}
          {r && (
            <dl className="kv">
              <dt>Email</dt><dd>{r.email}</dd>
              <dt>Bank</dt><dd>{r.bankName === "Other" ? r.bankOther : r.bankName} ({r.country})</dd>
              <dt>Employee ID</dt><dd>{r.employeeId}</dd>
              <dt>Designation</dt><dd>{r.designation}</dd>
              <dt>Submitted</dt><dd>{r.createdAt ? new Date(r.createdAt).toLocaleString() : "—"}</dd>
            </dl>
          )}
          <div className="row">
            <button className="btn primary" disabled={checking} onClick={() => load(true)} data-testid="check-again">Check again</button>
            {r && (status === "REJECTED" || status === "REVOKED") && (
              <button className="btn" onClick={async () => {
                await requestBankAccess({ fullName: r.fullName, country: r.country, bankName: r.bankName, bankOther: r.bankOther || undefined,
                  employeeId: r.employeeId, designation: r.designation, note: r.note || undefined });
                load(false);
              }}>Apply again</button>
            )}
            <button className="link danger" data-testid="staff-delete" onClick={async () => {
              if (!confirm("Delete this staff account and its access request?")) return;
              await staffDeleteAccount();
              nav("/");
            }}>Delete my account</button>
          </div>
        </section>
      )}
      <Link className="link small" to="/">← RecoverAI home</Link>
    </main>
    </>
  );
}
