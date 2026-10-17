import { useState } from "react";
import { useT } from "../i18n";
import { copyText, downloadText, type CardProps } from ".";

export function EscalationCard({ data }: CardProps) {
  const t = useT();
  const [open, setOpen] = useState(true);
  const [local, setLocal] = useState(false);
  const draft = data.draft || {};
  const text = local ? draft.local : draft.en;
  return (
    <div className="card escalation-card" id="escalation">
      <h3>⚠️ {data.title || t("escalationTitle")}</h3>
      <p>{data.label}</p>
      <div className="row wrap">
        <span className="chip st-overdue">⏰ {data.dueDisplay}</span>
        {data.bankReference && <span className="chip">{t("bankRef")} {data.bankReference}</span>}
        {data.bankComplaintDate && <span className="chip">{t("bankComplaint")} {data.bankComplaintDate}</span>}
      </div>
      {data.contact && <a className="btn primary" href={data.contact} target="_blank" rel="noreferrer">↗ {data.contact.replace("https://", "")}</a>}
      <button className="link" onClick={() => setOpen(!open)}>{t("showDraft")} {open ? "▲" : "▼"}</button>
      {open && (
        <>
          <div className="row">
            <button className={`toggle ${!local ? "on" : ""}`} onClick={() => setLocal(false)}>English</button>
            <button className={`toggle ${local ? "on" : ""}`} onClick={() => setLocal(true)}>{t("local")}</button>
          </div>
          <pre className="draft-text">{text}</pre>
          <div className="row">
            <button className="btn" onClick={() => copyText(text)}>📋 {t("copy")}</button>
            <button className="btn" onClick={() => downloadText("ombudsman-complaint.txt", text)}>⬇️ {t("download")}</button>
          </div>
        </>
      )}
    </div>
  );
}
