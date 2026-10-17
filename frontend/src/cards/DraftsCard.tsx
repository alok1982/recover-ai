import { useState } from "react";
import { api } from "../lib/api";
import { resolveUrl } from "../lib/config";
import { useCopilot } from "../copilot/context";
import { LANG_LABEL, useT } from "../i18n";
import { copyText, downloadText, type CardProps } from ".";

export async function openEvidencePack(caseId: string) {
  const r = await api.post<{ url: string }>(`/api/cases/${caseId}/evidence-pack`);
  window.open(resolveUrl(r.url), "_blank");
}

export function DraftsCard({ data }: CardProps) {
  const { caseId } = useCopilot();
  const t = useT();
  const drafts: any[] = data.drafts || [];
  const [tab, setTab] = useState(0);
  const [local, setLocal] = useState(true);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [copied, setCopied] = useState(false);
  const d = drafts[tab];
  if (!d) return null;
  const key = `${d.stepId}:${local ? "l" : "e"}`;
  const value = texts[key] ?? (local ? d.local : d.en);
  return (
    <div className="card drafts-card">
      <h3>{t("draftsTitle")}</h3>
      <div className="tabs" role="tablist">
        {drafts.map((x, i) => (
          <button key={x.stepId} role="tab" aria-selected={i === tab} className={`tab ${i === tab ? "on" : ""}`} onClick={() => setTab(i)}>
            {x.title}
          </button>
        ))}
      </div>
      <div className="row">
        <button className={`toggle ${!local ? "on" : ""}`} onClick={() => setLocal(false)}>English</button>
        <button className={`toggle ${local ? "on" : ""}`} onClick={() => setLocal(true)}>{LANG_LABEL[d.localLang as "en"] || t("local")}</button>
      </div>
      <textarea className="draft-text" value={value} rows={12} onChange={(e) => setTexts({ ...texts, [key]: e.target.value })} />
      <div className="row wrap">
        <button className="btn" onClick={() => { copyText(value); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
          📋 {copied ? t("copied") : t("copy")}
        </button>
        <button className="btn" onClick={() => downloadText(`${d.stepId}-${local ? d.localLang : "en"}.txt`, value)}>⬇️ {t("download")}</button>
        <button className="btn primary" onClick={() => openEvidencePack(caseId)}>📄 {t("evidencePack")}</button>
      </div>
      {d.insertedValues?.length > 0 && <p className="muted small">✔ Confirmed values inserted: {d.insertedValues.join(", ")}</p>}
    </div>
  );
}
