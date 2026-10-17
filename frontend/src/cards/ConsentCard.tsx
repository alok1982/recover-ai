import { useState } from "react";
import { api } from "../lib/api";
import { useCopilot } from "../copilot/context";
import { useT } from "../i18n";
import type { CardProps } from ".";

export function ConsentCard({ data, messageId }: CardProps) {
  const { caseId, apply, caseDoc, latestCardId } = useCopilot();
  const t = useT();
  const [working, setWorking] = useState(false);
  const shared = !!caseDoc?.bankCaseId;
  const active = latestCardId("consent") === messageId && !shared;
  const decide = async (consent: boolean) => {
    setWorking(true);
    try {
      apply(await api.post<any>(`/api/cases/${caseId}/send-to-bank`, { consent, consentVersion: data.version }));
    } finally {
      setWorking(false);
    }
  };
  return (
    <div className="card consent-card">
      <h3>🏦 {t("consentTitle")}</h3>
      <p>{data.text}</p>
      <b>{t("willShare")}:</b>
      <ul>{data.items.map((i: string) => <li key={i}>{i}</li>)}</ul>
      <p className="muted small">Purpose: {data.purpose}. Consent version {data.version} (DPDP Act 2023 / PDPA).</p>
      {active ? (
        <div className="row wrap">
          <button className="btn primary big" disabled={working} onClick={() => decide(true)}>✓ {t("share")}</button>
          <button className="btn" disabled={working} onClick={() => decide(false)}>{t("notNow")}</button>
        </div>
      ) : shared ? <p className="ok">✓ {t("bank.SENT")}</p> : null}
    </div>
  );
}
