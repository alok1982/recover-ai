import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useCopilot } from "../copilot/context";
import { useT } from "../i18n";

const UNDO_S = 10;

/** CR-01 / F8.2: confirmation sheet filled from /send-to-bank/preview. Nothing is published until the person ticks the
 *  box, taps Confirm and lets the 10-second undo run out; only then is POST /send-to-bank called with the token. */
export function ConfirmSheet({ onClose }: { onClose: () => void }) {
  const { caseId, apply } = useCopilot();
  const t = useT();
  const [pv, setPv] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [left, setLeft] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const load = () => {
    setPv(null);
    setErr(null);
    setChecked(false);
    api.post<any>(`/api/cases/${caseId}/send-to-bank/preview`).then(setPv).catch((e) => setErr(e.message));
  };
  useEffect(load, [caseId]);
  useEffect(() => () => window.clearInterval(timer.current), []);

  const send = async () => {
    setSending(true);
    try {
      apply(await api.post<any>(`/api/cases/${caseId}/send-to-bank`, { confirmationToken: pv.confirmationToken, confirmed: true }));
      onClose();
    } catch (e: any) {
      setErr(e.message);
      setLeft(null);
      setPv(null);
    } finally {
      setSending(false);
    }
  };
  const start = () => {
    setNote(null);
    setLeft(UNDO_S);
    let n = UNDO_S;
    timer.current = window.setInterval(() => {
      n -= 1;
      setLeft(n);
      if (n <= 0) {
        window.clearInterval(timer.current);
        send();
      }
    }, 1000);
  };
  const undo = () => {
    window.clearInterval(timer.current);
    setLeft(null);
    setNote(t("undone"));
  };

  const s = pv?.summary;
  const sandbox = s?.destination === "SANDBOX";
  return (
    <div className="sheet-backdrop" role="dialog" aria-modal="true" aria-label={t("confirmTitle")}>
      <div className={`sheet confirm-sheet ${sandbox ? "is-sandbox" : ""}`}>
        <h3>{t("confirmTitle")}</h3>
        {err && <p className="error sheet-msg">{err}</p>}
        {note && <p className="ok sheet-msg undone">{note}</p>}
        {!s && !err && <p className="muted">…</p>}
        {s && (
          <>
            <p className={`dest dest-${s.destination}`}>
              <b>{t("destination")}:</b> {sandbox ? t("sandboxNote") : t(`dest.${s.destination}`)}
            </p>
            <dl className="kv">
              <dt>{t("publicRef")}</dt><dd><code>{s.publicRef}</code></dd>
              <dt>{t("bankName")}</dt><dd>{s.bankName}</dd>
              <dt>{t("amount")}</dt><dd>{s.amount || "—"}</dd>
              <dt>{t("ref")}</dt><dd>{s.reference_id || "—"}</dd>
              <dt>{t("receiver")}</dt><dd>{[s.beneficiary?.name, s.beneficiary?.account, s.beneficiary?.bank].filter(Boolean).join(" · ") || "—"}</dd>
              {s.scammerContacts?.length > 0 && <><dt>{t("contacts")}</dt><dd>{s.scammerContacts.join(", ")}</dd></>}
              <dt>{t("evidenceItems")}</dt><dd>{s.evidence.length} 📎 (SHA-256)</dd>
            </dl>
            <label className="confirm-check">
              <input type="checkbox" checked={checked} disabled={left !== null} onChange={(e) => setChecked(e.target.checked)} />
              <span>{t("confirmCheck")}</span>
            </label>
          </>
        )}
        {left !== null ? (
          <div className="row wrap undo-row">
            <span className="countdown">⏳ {t("sendingIn").replace("{s}", String(Math.max(left, 0)))}</span>
            <button className="btn primary big" onClick={undo} disabled={sending || left <= 0}>{t("undo")}</button>
          </div>
        ) : (
          <div className="row wrap">
            {s && (
              <button className="btn primary big" disabled={!checked} onClick={start}>
                {sandbox ? t("confirmSandbox") : t("confirmBank").replace("{bank}", s.bankName)}
              </button>
            )}
            {!s && err && <button className="btn" onClick={load}>{t("reviewSend")}</button>}
            <button className="btn" onClick={onClose}>{t("cancel")}</button>
          </div>
        )}
      </div>
    </div>
  );
}
