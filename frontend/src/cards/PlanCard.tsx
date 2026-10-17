import { useState } from "react";
import { api } from "../lib/api";
import { useCopilot } from "../copilot/context";
import { useT } from "../i18n";
import type { Step } from "../lib/types";
import type { CardProps } from ".";

export function StepRow({ step, big }: { step: Step; big?: boolean }) {
  const { caseId, apply } = useCopilot();
  const t = useT();
  const [open, setOpen] = useState(false);
  const [ref, setRef] = useState("");
  const done = step.status === "done";
  const mark = async () => {
    const r = await api.patch<any>(`/api/cases/${caseId}/steps/${step.id}`, { status: "done", reference: ref || null });
    apply(r);
    setOpen(false);
  };
  const tel = step.channel === "call" && step.contact ? `tel:${step.contact}` : null;
  const url = step.contact?.startsWith("http") ? step.contact : null;
  return (
    <li className={`step ${big ? "urgent" : ""} ${done ? "done" : ""}`}>
      <div className="step-title">
        {done ? "✅" : step.urgency === "now" ? "🔴" : "🟠"} {step.titleLocal || step.title}
      </div>
      {step.titleLocal && <div className="muted small">{step.title}</div>}
      {step.why && big && <div className="why">{step.why}</div>}
      <div className="row wrap">
        {tel && !done && <a className="btn primary big call" href={tel}>📞 {t("callNow")} {step.contact}</a>}
        {url && <a className="btn" href={url} target="_blank" rel="noreferrer">↗ {url.replace("https://", "")}</a>}
        {step.deadlineDisplay && <span className="chip deadline">⏰ {t("deadline")}: {step.deadlineDisplay}</span>}
        {done && step.user_reference && <span className="chip">ref {step.user_reference}</span>}
        {!done && <button className="btn small" onClick={() => setOpen(!open)}>{t("markDone")}</button>}
      </div>
      {open && (
        <div className="row">
          <input placeholder={t("reference")} value={ref} onChange={(e) => setRef(e.target.value)} />
          <button className="btn small primary" onClick={mark}>{t("done")}</button>
        </div>
      )}
    </li>
  );
}

export function PlanCard({ data, messageId }: CardProps) {
  const { caseDoc, trigger, busy, latestCardId } = useCopilot();
  const t = useT();
  const steps: Step[] = (caseDoc?.plan?.steps as Step[]) || data.steps;
  const clocks = caseDoc?.clocks || data.clocks || [];
  const active = latestCardId("plan") === messageId;
  const [first, ...rest] = steps;
  return (
    <div className="card plan-card">
      <h3>{t("planTitle")}</h3>
      <ol className="steps">
        {first && <StepRow step={first} big />}
        {rest.map((s) => <StepRow key={s.id} step={s} />)}
      </ol>
      {clocks.length > 0 && (
        <div className="clocks">
          {clocks.map((c: any) => (
            <div key={c.id} className={`clock ${c.status}`}>
              <b>{c.labelLocal || c.label}</b>
              <div className="row wrap">
                <span className="chip deadline">⏰ {c.dueDisplay}</span>
                <span className={`chip st-${c.status}`}>{t(c.status === "recommended" ? "recommended" : c.status === "overdue" ? "overdue" : c.status === "done" ? "done" : "pending")}</span>
              </div>
              {(c.noteLocal || c.note) && <div className="note">ℹ️ {c.noteLocal || c.note}</div>}
            </div>
          ))}
        </div>
      )}
      <p className="muted small">Playbook {data.playbookVersion} · verified {data.lastVerified}</p>
      {active && Object.keys(caseDoc?.drafts || {}).length === 0 && (
        <button className="btn primary big" disabled={busy} onClick={() => trigger("generate_all")}>✍️ {t("generateAll")}</button>
      )}
    </div>
  );
}
