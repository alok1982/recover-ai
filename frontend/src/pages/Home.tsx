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
          <div className="role-choice" data-testid="home-role-picker">
            <p className="role-q">{t("roleTitle")}</p>
            <div className="role-cards">
              <div className="role-card victim">
                <b>🆘 {t("roleVictim")}</b>
                <div className="row cta-row">
                  <button className="btn primary cta" data-testid="get-help" onClick={() => nav(me ? "/cases" : "/signup?next=/cases")}>{t("getHelp")}</button>
                  {!me && <Link className="btn cta-secondary" to="/login?next=/cases">{t("signIn")}</Link>}
                </div>
              </div>
              <div className="role-card bank">
                <b>🏦 {t("roleBank")}</b>
                <span className="small muted">{t("roleBankHint")}</span>
                <div className="row">
                  <Link className="btn" data-testid="home-role-bank" to="/signup?role=bank">{t("roleBankApply")}</Link>
                  <Link className="link small" to="/login?role=bank">{t("signIn")}</Link>
                </div>
              </div>
            </div>
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
