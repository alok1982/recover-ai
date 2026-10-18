import { useState } from "react";
import { api } from "../lib/api";
import { useCopilot } from "../copilot/context";
import { useT } from "../i18n";
import type { CaseDoc } from "../lib/types";
import type { CardProps } from ".";

/** Shared with a bank (or sandbox) right now — the only state in which consent can be withdrawn. */
export function isShared(c: CaseDoc | null | undefined): boolean {
  if (!c) return false;
  if (c.submission) return c.submission.status === "SENT";
  return !!c.bankCaseId && !["NONE", "WITHDRAWN", undefined, null].includes(c.bankStatus as any);
}

/** CR-01 / F8.4: two-step Withdraw consent (used by the withdraw card, the case panel and the Timeline card). */
export function WithdrawAction({ compact }: { compact?: boolean }) {
  const { caseId, caseDoc, apply } = useCopilot();
  const t = useT();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (caseDoc?.bankStatus === "WITHDRAWN") return <p className="ok withdraw-done">✓ {t("withdrawDone")}{caseDoc.publicRef ? ` · ${caseDoc.publicRef}` : ""}</p>;
  if (!isShared(caseDoc)) return null;
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      apply(await api.post<any>(`/api/cases/${caseId}/withdraw-consent`, { confirmed: true }));
      setOpen(false);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (!open) return <button className={`btn withdraw-btn ${compact ? "small" : ""}`} onClick={() => setOpen(true)}>↩ {t("withdrawTitle")}</button>;
  return (
    <div className="withdraw-confirm">
      <p className="small">{t("withdrawText")} {t("withdrawHold")}</p>
      {err && <p className="error">{err}</p>}
      <div className="row wrap">
        <button className="btn danger" disabled={busy} onClick={go}>{t("withdrawConfirm")}</button>
        <button className="btn" disabled={busy} onClick={() => setOpen(false)}>{t("cancel")}</button>
      </div>
    </div>
  );
}

export function WithdrawCard({ data }: CardProps) {
  const t = useT();
  return (
    <div className="card withdraw-card">
      <h3>↩ {t("withdrawTitle")}</h3>
      {data.publicRef && <p><b>{t("publicRef")}:</b> <code>{data.publicRef}</code>{data.sandbox ? <span className="pill sandbox-pill">{t("sandboxPill")}</span> : null}</p>}
      <p>{t("withdrawText")}</p>
      <p className="muted small">{t("withdrawHold")}</p>
      <WithdrawAction />
    </div>
  );
}
