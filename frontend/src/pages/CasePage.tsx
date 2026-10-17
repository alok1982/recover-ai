import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { useCaseLive } from "../lib/live";
import type { Country, Lang } from "../lib/types";
import { Chat } from "../copilot/Chat";
import { CasePanel } from "../panel/CasePanel";
import { CountriesList } from "../cards/CountriesCard";
import { COUNTRY_LANGS, LANG_LABEL, LangContext, translate } from "../i18n";
import { Disclaimer } from "./Disclaimer";

export function CasePage() {
  const { caseId } = useParams();
  const live = useCaseLive(caseId);
  const [tab, setTab] = useState<"chat" | "case">("chat");
  const [showSoon, setShowSoon] = useState(false);
  const lang: Lang = live.caseDoc?.language || "en";
  const t = (k: string) => translate(lang, k);
  if (!caseId) return null;
  if (caseId) localStorage.setItem("recoverai.lastCase", caseId);

  const change = async (patch: { country?: Country; language?: Lang }) => {
    const r = await api.patch<any>(`/api/cases/${caseId}`, patch);
    live.setCase(r.case);
    if (r.messages?.length) live.addLocal(r.messages);
  };
  const c = live.caseDoc;

  return (
    <LangContext.Provider value={lang}>
      <div className={`app tab-${tab}`}>
        <header className="top">
          <a className="brand small" href="/">✔ RecoverAI</a>
          {c && (
            <div className="row">
              <select aria-label={t("country")} value={c.country} onChange={(e) => {
                const country = e.target.value as Country;
                change({ country, language: COUNTRY_LANGS[country].includes(lang) ? lang : COUNTRY_LANGS[country][0] });
              }}>
                <option value="IN">🇮🇳 India</option>
                <option value="MY">🇲🇾 Malaysia</option>
              </select>
              <select aria-label={t("language")} value={lang} onChange={(e) => change({ language: e.target.value as Lang })}>
                {COUNTRY_LANGS[c.country].map((l) => <option key={l} value={l}>{LANG_LABEL[l]}</option>)}
              </select>
              <button className="link" onClick={() => setShowSoon(!showSoon)}>🌏 {t("comingSoon")}</button>
            </div>
          )}
        </header>
        {showSoon && <div className="soon-pop"><CountriesList /></div>}
        {live.error && <div className="banner error">{live.error}</div>}
        <nav className="mobile-tabs">
          <button className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>{t("chat")}</button>
          <button className={tab === "case" ? "on" : ""} onClick={() => setTab("case")}>{t("myCase")}</button>
        </nav>
        <div className="layout">
          <Chat caseId={caseId} caseDoc={c} messages={live.messages} addLocal={live.addLocal} setCase={live.setCase} refresh={live.refresh}>
            <CasePanel />
          </Chat>
        </div>
        <Disclaimer />
      </div>
    </LangContext.Provider>
  );
}
