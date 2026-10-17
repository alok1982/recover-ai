import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { Country, Lang } from "../lib/types";
import { COMING_SOON, COUNTRY_LANGS, LANG_LABEL, LangContext, translate } from "../i18n";
import { Disclaimer } from "./Disclaimer";

export function Landing() {
  const nav = useNavigate();
  const [country, setCountry] = useState<Country>("IN");
  const [lang, setLang] = useState<Lang>("hi");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const last = localStorage.getItem("recoverai.lastCase");
  const t = (k: string) => translate(lang, k);

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<{ caseId: string }>("/api/cases", { country, language: lang });
      localStorage.setItem("recoverai.lastCase", r.caseId);
      nav(`/case/${r.caseId}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <LangContext.Provider value={lang}>
      <main className="landing">
        <div className="brand">✔ RecoverAI</div>
        <p className="promise">{t("promise")}</p>
        <div className="pickers">
          <label>{t("country")}
            <div className="seg">
              {(["IN", "MY"] as Country[]).map((c) => (
                <button key={c} className={`seg-btn ${country === c ? "on" : ""}`}
                  onClick={() => { setCountry(c); setLang(COUNTRY_LANGS[c][0]); }}>
                  {c === "IN" ? "🇮🇳 India" : "🇲🇾 Malaysia"}
                </button>
              ))}
              {COMING_SOON.map((c) => <button key={c.code} className="seg-btn disabled" disabled title={t("comingSoon")}>{c.name}</button>)}
            </div>
          </label>
          <label>{t("language")}
            <div className="seg">
              {COUNTRY_LANGS[country].map((l) => (
                <button key={l} className={`seg-btn ${lang === l ? "on" : ""}`} onClick={() => setLang(l)}>{LANG_LABEL[l]}</button>
              ))}
            </div>
          </label>
        </div>
        <button className="btn primary cta" onClick={start} disabled={busy}>{t("start")}</button>
        {last && <a className="link" href={`/case/${last}`}>{t("continue")} →</a>}
        {err && <p className="error">{err}</p>}
        <section className="coming">
          <h4>{t("comingSoon")}</h4>
          <ul>{COMING_SOON.map((c) => <li key={c.code}><b>{c.name}</b>: {c.text}</li>)}</ul>
        </section>
        <a className="link small" href="/bank">Bank analyst dashboard →</a>
        <Disclaimer />
      </main>
    </LangContext.Provider>
  );
}
