import { useState } from "react";
import { Route, Routes, Link } from "react-router-dom";
import { bankLogin, bankLogout, currentBankUser, type BankUser } from "../lib/auth";
import { MOCK } from "../lib/config";
import { useDemo } from "../lib/health";
import { DEMO_BANK_NAME } from "../lib/demobank";
import { DemoRibbon } from "../ui/AppHeader";

/** DEMO_MODE: the desk belongs to the fictional demo bank, never a real bank. */
export function useDeskName(): string {
  return useDemo() ? `${DEMO_BANK_NAME} · Fraud desk` : "Bank fraud desk";
}
import { Inbox } from "./Inbox";
import { CaseDetail } from "./CaseDetail";
import { ScamIntelligence } from "./ScamIntelligence";
import { Logo } from "../ui/Logo";

function Login({ onDone }: { onDone: (u: BankUser) => void }) {
  const desk = useDeskName();
  const [name, setName] = useState("Rahul");
  const [email, setEmail] = useState("analyst@recoverai-demo.example");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <>
    <DemoRibbon />
    <main className="bank-login">
      <div className="login-brand"><Logo variant="mark" height={44} /><h1 data-testid="desk-title">{desk}</h1></div>
      <p className="muted">Demo analyst login {MOCK ? "(offline mock: any name)" : "(Firebase email/password, role=bank)"}</p>
      <label>Name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
      {!MOCK && (
        <>
          <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        </>
      )}
      <button className="btn primary big" onClick={async () => {
        try { onDone(await bankLogin(name, email, password)); } catch (e: any) { setErr(e.message); }
      }}>Sign in</button>
      {err && <p className="error">{err}</p>}
    </main>
    </>
  );
}

export function BankApp() {
  const [user, setUser] = useState<BankUser | null>(currentBankUser());
  const desk = useDeskName();
  if (!user) return <Login onDone={setUser} />;
  return (
    <div className="bank">
      <DemoRibbon />
      <header className="top bank-top">
        <Link className="brand small" to="/bank"><Logo variant="mark" height={30} /><span data-testid="desk-title">{desk}</span></Link>
        <nav className="row">
          <Link to="/bank">Inbox</Link>
          <Link to="/bank/intel">Scam intelligence</Link>
          <span className="muted">{user.name}</span>
          <button className="link" onClick={async () => { await bankLogout(); setUser(null); }}>Sign out</button>
        </nav>
      </header>
      <Routes>
        <Route index element={<Inbox />} />
        <Route path="case/:id" element={<CaseDetail analyst={user.name} />} />
        <Route path="intel" element={<ScamIntelligence />} />
      </Routes>
    </div>
  );
}
