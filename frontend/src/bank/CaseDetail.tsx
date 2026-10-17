import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { resolveUrl } from "../lib/config";
import { riskBadge } from "./Inbox";

export function fmtMoney(v: number | null | undefined, currency?: string | null): string {
  if (v == null) return "—";
  return currency === "MYR"
    ? `RM ${Number(v).toLocaleString("en-MY", { maximumFractionDigits: 2 })}`
    : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function CaseDetail({ analyst }: { analyst: string }) {
  const { id } = useParams();
  const [d, setD] = useState<any>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api.bankGet<any>(`/api/bank/cases/${id}`).then(setD).catch((e) => setErr(e.message)), [id]);
  useEffect(() => {
    load();
  }, [load]);
  if (err) return <main className="bank-main"><p className="error">{err}</p></main>;
  if (!d) return <main className="bank-main">…</main>;
  const c = d.case;
  const a = d.account;
  const decide = async (decision: string) => {
    await api.bankPost(`/api/bank/cases/${id}/decision`, { decision, note: note || null });
    setNote("");
    load();
  };
  const b = c.beneficiary || {};
  return (
    <main className="bank-main detail">
      <h2>{c.amountDisplay} · {c.scam_type} · {c.country} {riskBadge(c.riskLevel)} <span className="muted">score {c.riskScore}</span></h2>
      <div className="grid2">
        <section className="card">
          <h3>Recommendation</h3>
          <p className="rec"><b>{c.recommendedActionLabel}</b>{c.holdLimitDisplay && <> — limited to <b>{c.holdLimitDisplay}</b></>}</p>
          <p className="muted small">{c.holdNote}</p>
          <h4>{c.reasonSource === "template" ? (c.reasonPending ? "Reason (rules summary · Gemini reason loading…)" : "Reason (rules summary)") : "Reason (Gemini)"}</h4>
          <p>{c.reason_en}</p>
          <h4>Signals that fired</h4>
          <ul className="signals">{c.signals.map((s: any) => <li key={s.code}><code>{s.code}</code> {s.label} <span className="chip">+{s.weight}</span></li>)}</ul>
          <textarea placeholder="Note / question for the victim (for Request more info)" value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
          <div className="row wrap">
            <button className="btn primary big" disabled={c.status !== "NEW" && c.status !== "INFO_REQUESTED"} onClick={() => decide("APPROVE_HOLD")}>Approve temporary hold</button>
            <button className="btn" onClick={() => decide("REQUEST_INFO")}>Request more info</button>
            <button className="btn danger" onClick={() => decide("REJECT")}>Reject</button>
          </div>
          <p>Status: <span className={`pill bstat-${c.status}`}>{c.status}</span> {c.decidedBy && <span className="muted">by {c.decidedBy}</span>}</p>
          <p className="muted small">Signed in as {analyst}. Every decision is written to the audit log.</p>
        </section>
        <section className="card">
          <h3>Case facts</h3>
          <dl className="kv">
            <dt>Reference</dt><dd>{c.reference_id}</dd>
            <dt>Occurred</dt><dd>{c.occurredAtDisplay || (c.occurredAt ? new Date(c.occurredAt).toLocaleString() : "—")}</dd>
            <dt>Method</dt><dd>{c.payment_method}</dd>
            <dt>Payer bank</dt><dd>{c.payer_bank}</dd>
            <dt>Beneficiary</dt><dd>{b.name} · {b.account_or_vpa} · {b.bank}</dd>
            <dt>Scammer contacts</dt><dd>{(c.scammer_contacts || []).join(", ")}</dd>
          </dl>
          <p>{c.narrative_en}</p>
          <h3>Beneficiary account <span className="chip src-chip">from transaction data</span></h3>
          {a ? (
            <>
              <dl className="kv">
                <dt>Holder</dt><dd>{a.holder_name} · {a.account_type} · {a.bank}</dd>
                <dt>Declared profile</dt><dd>{a.declared_profile}</dd>
                <dt>Account age</dt><dd>{a.account_age_days} days</dd>
                <dt>Credits in last 24 h</dt><dd>{a.credits_24h} from {a.distinct_senders_24h} distinct senders</dd>
                <dt>Moved out within 60 min</dt><dd>{a.outflow_60m_pct ?? "—"}% of credited amount</dd>
                <dt>24 h credits vs monthly avg</dt><dd>{a.credit_ratio_vs_avg != null ? `${a.credit_ratio_vs_avg}×` : "—"}</dd>
                <dt>Current balance</dt><dd>{fmtMoney(a.current_balance, a.currency)}</dd>
              </dl>
              <p className="muted small">
                Computed by one parameterised {c.txnSource === "bigquery" ? "BigQuery" : "offline (mock)"} query over synthetic
                bank_txn{c.txnQueryMs != null ? ` in ${c.txnQueryMs} ms` : ""}; feature time {c.featureTime ? new Date(c.featureTime).toLocaleString() : "—"}.
              </p>
            </>
          ) : <p className="warn-note">{c.txnNote || "Beneficiary not found in transaction data — case signals only."}</p>}
          {c.mlRiskScore != null && (
            <p className="ml-score">
              ML mule-risk: <b>{c.mlRiskScore.toFixed(2)}</b>{" "}
              <span className="muted small">(BigQuery ML model on synthetic data — advisory only; the rules decide the action)</span>
            </p>
          )}
          <h3>Evidence</h3>
          <ul className="evidence-list">
            {c.evidence.map((e: any) => (
              <li key={e.id}>
                {e.previewUrl ? <img src={resolveUrl(e.previewUrl)} alt="" /> : <span className="doc-ic">📄</span>}
                <span className="ev-label">{e.type}{e.textContent ? `: ${e.textContent.slice(0, 80)}…` : ""}</span>
                <code>{e.sha256?.slice(0, 16)}…</code>
              </li>
            ))}
          </ul>
          <h3>Audit trail</h3>
          <ul className="audit">{d.audit.map((x: any) => <li key={x.id}>{new Date(x.at).toLocaleString()} — <b>{x.action}</b> by {x.actor}{x.details?.note ? ` (${x.details.note})` : ""}</li>)}</ul>
          <p className="muted small">
            A2A envelope: {c.envelope?.intent} from {c.envelope?.from_agent} to {c.envelope?.to_agent}
            {c.delivery?.messageId ? ` · delivered by Pub/Sub push (message ${c.delivery.messageId})` : ""}
          </p>
        </section>
      </div>
    </main>
  );
}
