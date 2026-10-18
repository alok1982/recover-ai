import { useState } from "react";
import { api } from "../lib/api";
import { useCopilot } from "../copilot/context";
import { useT } from "../i18n";
import type { CardProps } from ".";

const LABELS: Record<string, string> = {
  amount: "Amount", currency: "Currency", reference_id: "Reference / UTR", occurred_at: "Date & time", payment_method: "Payment method",
  payer_bank: "Your bank", "beneficiary.name": "Receiver name", "beneficiary.account_or_vpa": "Receiver account / UPI ID",
  "beneficiary.bank": "Receiver bank", "beneficiary.ifsc_or_code": "IFSC / bank code", scammer_contacts: "Scammer contacts",
  urls: "Links", scam_type: "Scam type",
};

export function FactsCard({ data, messageId }: CardProps) {
  const { caseId, apply, trigger, busy, latestCardId, caseDoc } = useCopilot();
  const t = useT();
  const [facts, setFacts] = useState<any>(data);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const active = latestCardId("facts") === messageId;
  const confirmed = facts.confirmed || (caseDoc && !["draft", "extracted"].includes(caseDoc.status));

  const saveField = async (key: string) => {
    const r = await api.patch<any>(`/api/cases/${caseId}/extraction`, { fields: { [key]: draft }, confirm: false });
    setFacts(r.facts);
    apply({ case: r.case });
    setEdits({ ...edits, [key]: draft });
    setEditing(null);
  };

  const confirm = async () => {
    const r = await api.patch<any>(`/api/cases/${caseId}/extraction`, { fields: {}, confirm: true });
    setFacts(r.facts);
    apply({ case: r.case });
    await trigger("facts_confirmed");
  };

  return (
    <div className="card facts-card">
      <h3>{t("factsTitle")}</h3>
      {facts.narrative && <p className="narrative">{facts.narrative}</p>}
      <table className="facts">
        <tbody>
          {facts.fields
            .filter((f: any) => !(f.missing && ["urls", "currency"].includes(f.key)))
            .map((f: any) => (
              <tr key={f.key} className={`lvl-${f.level}`}>
                <th>
                  <span className={`dot ${f.level}`} aria-hidden /> {LABELS[f.key] || f.key}
                  {f.level === "red" && <span className="chip warn">{f.missing ? t("missingCheck") : t("checkThis")}</span>}
                </th>
                <td>
                  {editing === f.key ? (
                    <span className="row">
                      <input value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus />
                      <button className="btn small primary" onClick={() => saveField(f.key)}>{t("save")}</button>
                    </span>
                  ) : (
                    <span className="row">
                      <span className={f.missing ? "muted" : ""}>{f.missing ? "—" : String(f.display ?? f.value)}</span>
                      {f.source === "user" && <span className="chip">✎</span>}
                      {active && !confirmed && (
                        <button className="link" onClick={() => { setEditing(f.key); setDraft(f.value == null ? "" : Array.isArray(f.value) ? f.value.join(", ") : String(f.value)); }}>
                          {t("edit")}
                        </button>
                      )}
                    </span>
                  )}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
      {active && !confirmed && (
        <button className="btn primary big" onClick={confirm} disabled={busy}>✓ {t("looksRight")}</button>
      )}
      {confirmed && <p className="ok">✓ {t("looksRight")}</p>}
    </div>
  );
}
