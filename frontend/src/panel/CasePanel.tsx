import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { DEMO_UI } from "../lib/config";
import { countdown, effectiveNow } from "../lib/live";
import { useCopilot } from "../copilot/context";
import { openEvidencePack } from "../cards/DraftsCard";
import { useT } from "../i18n";
import { fmtTime } from "../cards/UploadCard";

/** F2/§13.3: evidence count with an expander listing every item's type, time and full SHA-256. */
function EvidenceHashes({ caseId, count }: { caseId: string; count: number }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    api.get<{ evidence: any[] }>(`/api/cases/${caseId}/evidence`).then((r) => setItems(r.evidence)).catch((e) => setErr(e.message));
  }, [open, caseId, count]);
  if (!count) return null;
  return (
    <div className="hashes">
      <button className="link small" aria-expanded={open} onClick={() => setOpen(!open)}>
        🔐 {open ? t("hideHashes") : t("hashes")} {open ? "▲" : "▼"}
      </button>
      {open && (
        <ul className="hash-list">
          {err && <li className="error">{err}</li>}
          {!items && !err && <li className="muted">…</li>}
          {items?.map((e) => (
            <li key={e.id}>
              <div className="small"><b>{t(`evType.${e.type}`)}</b>{e.fileName ? ` · ${e.fileName}` : ""} · {fmtTime(e.uploadedAt)}</div>
              <code className="sha">{e.sha256}</code>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function amountDisplay(ex: any): string | null {
  if (!ex || ex.amount == null) return null;
  const n = Number(ex.amount);
  if (ex.currency === "INR") return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  if (ex.currency === "MYR") return "RM " + n.toLocaleString("en-MY", { maximumFractionDigits: 2 });
  return `${ex.currency || ""} ${n.toLocaleString()}`;
}

export function CasePanel() {
  const { caseDoc: c, caseId, apply } = useCopilot();
  const t = useT();
  const nav = useNavigate();
  const [, tick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => tick((x) => x + 1), 30000);
    return () => window.clearInterval(id);
  }, []);
  if (!c) return <aside className="panel"><p className="muted">…</p></aside>;
  const ex = c.extraction;
  const now = effectiveNow(c);
  const steps = c.plan?.steps || [];
  const pendingClocks = (c.clocks || []).filter((k) => k.status !== "done").sort((a, b) => a.dueAt.localeCompare(b.dueAt));
  const next = pendingClocks[0];
  const overdueEsc = (c.clocks || []).find((k) => k.status === "overdue" && k.escalationTemplate);
  const travel = async (body: any) => apply(await api.post<any>(`/api/cases/${caseId}/clock`, body));
  const del = async () => {
    if (!confirm(t("confirmDelete"))) return;
    await api.del(`/api/cases/${caseId}`);
    localStorage.removeItem("recoverai.lastCase");
    nav("/");
  };
  return (
    <aside className="panel">
      <div className="panel-head">
        <span className={`pill status-${c.status}`}>{t(`status.${c.status}`)}</span>
        <span className={`pill bank-${c.bankStatus}`}>🏦 {t(`bank.${c.bankStatus}`)}</span>
      </div>
      {ex && (
        <section>
          <h4>{t("keyFacts")}</h4>
          <dl className="kv">
            <dt>{t("amount")}</dt><dd>{amountDisplay(ex) || "—"}</dd>
            <dt>{t("ref")}</dt><dd>{ex.reference_id || "—"}</dd>
            <dt>{t("time")}</dt><dd>{c.incidentAt && ex.occurred_at ? new Date(c.incidentAt).toLocaleString("en-GB", { timeZone: c.country === "IN" ? "Asia/Kolkata" : "Asia/Kuala_Lumpur", dateStyle: "medium", timeStyle: "short" }) : "—"}</dd>
            <dt>{t("beneficiary")}</dt><dd>{ex.beneficiary?.account_or_vpa || "—"}</dd>
          </dl>
        </section>
      )}
      {next && (
        <section className={`next ${next.status}`}>
          <h4>{t("nextDeadline")}</h4>
          <div>{next.labelLocal || next.label}</div>
          <div className="row wrap"><span className="chip deadline">⏰ {next.dueDisplay}</span><span className="chip">{countdown(next.dueAt, now, t("overdue"))}</span></div>
          {(next.noteLocal || next.note) && <div className="note">ℹ️ {next.noteLocal || next.note}</div>}
        </section>
      )}
      {overdueEsc && (
        <a className="escalation-row" href="#escalation">⚠️ {t("escalateRow")}: {overdueEsc.dueDisplay}</a>
      )}
      {steps.length > 0 && (
        <section>
          <h4>{t("steps")}</h4>
          <ul className="panel-steps">
            {steps.map((s) => (
              <li key={s.id} className={s.status}>
                {s.status === "done" ? "✅" : "⬜"} {s.titleLocal || s.title}
                {s.user_reference && <span className="muted"> · ref {s.user_reference}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h4>{t("evidence")}</h4>
        <div className="row wrap">
          <span className="chip">{c.evidenceCount || 0} 📎</span>
          {c.evidencePackPath && <button className="btn small" onClick={() => openEvidencePack(caseId)}>📄 {t("evidencePack")}</button>}
        </div>
        <EvidenceHashes caseId={caseId} count={c.evidenceCount || 0} />
      </section>
      {DEMO_UI && c.demoMode && (
        <section className="demo">
          <h4>🕒 {t("demo")} {c.clockOffsetDays ? `(+${Number(c.clockOffsetDays).toFixed(1)}d)` : ""}</h4>
          <div className="row wrap">
            <button className="btn small" onClick={() => travel({ addDays: 1 })}>{t("plus1")}</button>
            <button className="btn small" onClick={() => travel({ addDays: 5 })}>{t("plus5")}</button>
            <button className="btn small" onClick={() => travel({ jumpToDay: 31 })}>{t("day31")}</button>
            <button className="btn small" onClick={() => travel({ reset: true })}>{t("resetClock")}</button>
          </div>
        </section>
      )}
      <button className="link danger" onClick={del}>{t("deleteCase")}</button>
    </aside>
  );
}
