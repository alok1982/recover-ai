import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtMoney } from "./CaseDetail";

type Intel = {
  source: string;
  by_scam_type: { scam_type: string; cases: number }[];
  repeat_beneficiaries: { beneficiary_hash: string; cases: number; countries: string; first_seen: string; last_seen: string }[];
  by_country_day: { country: string; day: string; cases: number; amount: number; currency: string }[];
};

/** F14 [SHOULD] Scam intelligence — three BigQuery queries over anonymised case_events. */
export function ScamIntelligence() {
  const [data, setData] = useState<Intel | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    api.bankGet<Intel>("/api/bank/analytics").then(setData).catch((e) => setMsg(e.message));
  }, []);
  const maxType = Math.max(1, ...(data?.by_scam_type || []).map((r) => r.cases));
  const days = Array.from(new Set((data?.by_country_day || []).map((r) => r.day))).sort();
  const maxDay = Math.max(1, ...(data?.by_country_day || []).map((r) => r.cases));
  return (
    <main className="bank-main intel">
      <h2>Scam intelligence <span className="chip src-chip">{data?.source === "bigquery" ? "BigQuery" : data ? "offline mock" : "…"}</span></h2>
      <p className="muted small">Anonymised case events only: no names or phone numbers; beneficiary accounts appear as SHA-256 hashes.</p>
      {msg && <p className="error">{msg}</p>}
      {data && (
        <div className="grid2">
          <section className="card">
            <h3>Cases by scam type (last 30 days)</h3>
            <ul className="bars">
              {data.by_scam_type.map((r) => (
                <li key={r.scam_type}>
                  <span className="bar-label">{r.scam_type.replace(/_/g, " ")}</span>
                  <span className="bar" style={{ width: `${(r.cases / maxType) * 100}%` }} />
                  <span className="bar-val">{r.cases}</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="card">
            <h3>Repeat beneficiary accounts (≥ 2 cases)</h3>
            <table className="inbox">
              <thead><tr><th>Beneficiary hash</th><th>Cases</th><th>Countries</th><th>Last seen</th></tr></thead>
              <tbody>
                {data.repeat_beneficiaries.map((r) => (
                  <tr key={r.beneficiary_hash}>
                    <td><code title={r.beneficiary_hash}>{r.beneficiary_hash.slice(0, 12)}…</code></td>
                    <td><b>{r.cases}</b></td>
                    <td>{r.countries}</td>
                    <td>{new Date(r.last_seen).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="card wide">
            <h3>Cases and amounts by country per day (last 30 days)</h3>
            <div className="daygrid">
              {days.map((day, i) => (
                <div key={day} className="daycol" title={day}>
                  {["IN", "MY"].map((c) => {
                    const r = data.by_country_day.find((x) => x.day === day && x.country === c);
                    return r ? (
                      <span key={c} className={`daybar c-${c}`} style={{ height: `${(r.cases / maxDay) * 80 + 4}px` }}
                        title={`${c} ${day}: ${r.cases} cases, ${fmtMoney(r.amount, r.currency)}`} />
                    ) : null;
                  })}
                  <span className="daylabel">{i % 4 === 0 || i === days.length - 1 ? day.slice(5) : "\u00a0"}</span>
                </div>
              ))}
            </div>
            <p className="small"><span className="legend c-IN" /> India <span className="legend c-MY" /> Malaysia</p>
            <table className="inbox compact">
              <thead><tr><th>Country</th><th>Cases (30 d)</th><th>Amount (30 d)</th></tr></thead>
              <tbody>
                {["IN", "MY"].map((c) => {
                  const rows = data.by_country_day.filter((r) => r.country === c);
                  return (
                    <tr key={c}>
                      <td>{c}</td>
                      <td>{rows.reduce((s, r) => s + r.cases, 0)}</td>
                      <td>{fmtMoney(rows.reduce((s, r) => s + Number(r.amount || 0), 0), c === "MY" ? "MYR" : "INR")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </main>
  );
}
