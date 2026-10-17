import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { collection, limit, onSnapshot, orderBy, query } from "firebase/firestore";
import { api } from "../lib/api";
import { MOCK } from "../lib/config";
import { bankDb } from "../lib/firebase";
import { plain } from "../lib/live";

export function riskBadge(level: string) {
  return <span className={`risk risk-${level}`}>{level}</span>;
}

export function Inbox() {
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (MOCK) {
      const load = () => api.bankGet<{ cases: any[] }>("/api/bank/cases").then((r) => setRows(r.cases)).catch((e) => setErr(e.message));
      load();
      const id = window.setInterval(load, 2000);
      return () => window.clearInterval(id);
    }
    // Live Firestore listener; rules allow bank_cases reads only with the role=bank custom claim.
    return onSnapshot(query(collection(bankDb(), "bank_cases"), orderBy("receivedAt", "desc"), limit(100)),
      (qs) => setRows(qs.docs.map((d) => plain<any>(d.data()))), (e) => setErr(e.message));
  }, []);
  const hours = (iso?: string) => (iso ? ((Date.now() - new Date(iso).getTime()) / 3600000).toFixed(1) + " h" : "—");
  return (
    <main className="bank-main">
      <h2>Incoming fraud cases</h2>
      {err && <p className="error">{err}</p>}
      <table className="inbox">
        <thead><tr><th>Received</th><th>Country</th><th>Amount</th><th>Scam type</th><th>Since txn</th><th>Risk</th><th>Recommended action</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td><Link to={`/bank/case/${r.id}`}>{new Date(r.receivedAt).toLocaleString()}</Link></td>
              <td>{r.country}</td>
              <td><b>{r.amountDisplay}</b></td>
              <td>{r.scam_type}</td>
              <td>{hours(r.occurredAt)}</td>
              <td>{riskBadge(r.riskLevel)} {r.riskScore}</td>
              <td>{r.recommendedActionLabel}{r.holdLimitDisplay ? ` — limited to ${r.holdLimitDisplay}` : ""}</td>
              <td><span className={`pill bstat-${r.status}`}>{r.status}</span></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={8} className="muted">No cases yet. Victim cases appear here within seconds of consent.</td></tr>}
        </tbody>
      </table>
    </main>
  );
}
