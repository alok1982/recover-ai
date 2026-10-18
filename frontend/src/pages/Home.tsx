import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Lang } from "../lib/types";
import { COMING_SOON, LangContext, translate } from "../i18n";
import { saveLang, savedLang } from "../lib/prefs";
import { useVictim } from "../lib/auth";
import { AppHeader } from "../ui/AppHeader";
import { EmergencyStrip } from "../ui/EmergencyStrip";
import { Disclaimer } from "./Disclaimer";

/** CR-03 A: public home page. The hotline strip needs no login. */
export function Home() {
  const nav = useNavigate();
  const me = useVictim();
  const [lang, setLangState] = useState<Lang>(savedLang());
  const setLang = (l: Lang) => { saveLang(l); setLangState(l); };
  const t = (k: string) => translate(lang, k);
  return (
    <LangContext.Provider value={lang}>
      <AppHeader lang={lang} setLang={setLang} />
      <main className="landing home">
        <section className="hero">
          <h1>{t("heroTitle")}</h1>
          <p className="promise">{t("heroSub")}</p>
          <div className="row cta-row">
            <button className="btn primary cta" data-testid="get-help" onClick={() => nav(me ? "/cases" : "/signup?next=/cases")}>{t("getHelp")}</button>
            {!me && <Link className="btn cta-secondary" to="/login?next=/cases">{t("signIn")}</Link>}
          </div>
        </section>
        <EmergencyStrip />
        <p className="safety-line">🔒 {t("safetyLine")}</p>
        <section className="how">
          <h3>{t("howTitle")}</h3>
          <ol>
            <li>{t("how1")}</li>
            <li>{t("how2")}</li>
            <li>{t("how3")}</li>
          </ol>
        </section>
        <section className="coming">
          <h4>{t("countriesTitle")}</h4>
          <ul>
            <li><b>🇮🇳 India</b> · <b>🇲🇾 Malaysia</b></li>
            {COMING_SOON.map((c) => <li key={c.code} className="muted">{c.name} — {t("comingSoon")}</li>)}
          </ul>
        </section>
        <a className="link small" href="/bank">Bank analyst dashboard →</a>
        <a className="link small" href="/privacy">{t("privacyLink")}</a>
        <Disclaimer />
      </main>
    </LangContext.Provider>
  );
}
