import { useState } from "react";
import { api } from "../lib/api";
import { useCopilot } from "../copilot/context";
import { useT } from "../i18n";
import { ConfirmSheet } from "./ConfirmSheet";
import { isShared } from "./WithdrawCard";
import type { CardProps } from ".";

export function ConsentCard({ data, messageId }: CardProps) {
  const { caseId, apply, caseDoc, latestCardId } = useCopilot();
  const t = useT();
  const [working, setWorking] = useState(false);
  const [sheet, setSheet] = useState(false);
  const shared = isShared(caseDoc);
  const active = latestCardId("consent") === messageId && !shared;
  const decline = async () => {
    setWorking(true);
    try {
      apply(await api.post<any>(`/api/cases/${caseId}/send-to-bank`, { consent: false, consentVersion: data.version }));
    } finally {
      setWorking(false);
    }
  };
  const dest = caseDoc?.sandbox === false && data.liveAllowed ? "LIVE" : data.destination || "SANDBOX";
  return (
    <div className="card consent-card">
      <h3>🏦 {t("consentTitle")}</h3>
      <p>{data.text}</p>
      <dl className="kv">
        <dt>{t("destination")}</dt><dd><span className={`pill dest-${dest}`}>{t(`dest.${dest}`)}</span></dd>
        {data.bankName && <><dt>{t("bankName")}</dt><dd>{data.bankName}</dd></>}
        {data.beneficiaryMasked && <><dt>{t("beneficiaryMasked")}</dt><dd>{data.beneficiaryMasked}</dd></>}
      </dl>
      <b>{t("willShare")}:</b>
      <ul>{data.items.map((i: string) => <li key={i}>{i}</li>)}</ul>
      <p className="muted small">Purpose: {data.purpose}. Consent version {data.version} (DPDP Act 2023 / PDPA).</p>
      {active ? (
        <div className="row wrap">
          <button className="btn primary big" disabled={working} onClick={() => setSheet(true)}>✓ {t("reviewSend")}</button>
          <button className="btn" disabled={working} onClick={decline}>{t("notNow")}</button>
        </div>
      ) : shared ? <p className="ok">✓ {t("bank.SENT")}{caseDoc?.publicRef ? ` · ${caseDoc.publicRef}` : ""}</p> : null}
      {sheet && <ConfirmSheet onClose={() => setSheet(false)} />}
    </div>
  );
}
