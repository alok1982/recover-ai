import { useState } from "react";
import { Route, Routes, Link } from "react-router-dom";
import { bankLogin, bankLogout, currentBankUser, type BankUser } from "../lib/auth";
import { MOCK } from "../lib/config";
import { Inbox } from "./Inbox";
import { CaseDetail } from "./CaseDetail";
import { ScamIntelligence } from "./ScamIntelligence";

function Login({ onDone }: { onDone: (u: BankUser) => void }) {
  const [name, setName] = useState("Rahul");
  const [email, setEmail] = useState("analyst@recoverai-demo.example");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <main className="bank-login">
      <h1>🏦 Bank fraud desk</h1>
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
  );
}

export function BankApp() {
  const [user, setUser] = useState<BankUser | null>(currentBankUser());
  if (!user) return <Login onDone={setUser} />;
  return (
    <div className="bank">
      <header className="top bank-top">
        <Link className="brand small" to="/bank">🏦 RecoverAI · Bank fraud desk</Link>
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
