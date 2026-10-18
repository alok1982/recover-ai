import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { getMe, type Me } from "../lib/me";
import type { Country, Lang } from "../lib/types";
import { COUNTRY_LANGS, LANG_LABEL, LangContext, translate } from "../i18n";
import { saveLang, savedLang } from "../lib/prefs";
import { AppHeader } from "../ui/AppHeader";
import { EmergencyStrip } from "../ui/EmergencyStrip";
import { Disclaimer } from "./Disclaimer";

interface Row {
  id: string; publicRef: string | null; country: Country; status: string; createdAt: string; amount: string | null;
  sandbox: boolean; nextDeadline: { label: string; dueDisplay: string; status: string } | null;
}

/** CR-03 C: the signed-in home: greeting, profile banner, start a case, my cases, hotline. */
export function CasesPage() {
  const nav = useNavigate();
  const [me, setMe] = useState<Me | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [lang, setLangState] = useState<Lang>(savedLang());
  const setLang = (l: Lang) => { saveLang(l); setLangState(l); };
  const [country, setCountry] = useState<Country>("IN");
  const [clang, setClang] = useState<Lang>("en");
  const [busy, setBusy] = useState(false);
  const t = (k: string) => translate(lang, k);

  useEffect(() => {
    getMe().then((m) => {
      setMe(m);
      const c = (m.profile.country as Country) || "IN";
      setCountry(c);
      const l = (m.profile.language as Lang) || savedLang();
      setClang(COUNTRY_LANGS[c].includes(l) ? l : "en");
      if (m.profile.language) setLang(m.profile.language as Lang);
    }).catch((e) => setErr(e.message));
    api.get<{ cases: Row[] }>("/api/cases").then((r) => setRows(r.cases)).catch((e) => setErr(e.message));
  }, []);

  const start = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ caseId: string }>("/api/cases", { country, language: clang, sandbox: true });
      localStorage.setItem("recoverai.lastCase", r.caseId);
      nav(`/cases/${r.caseId}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const missing = me?.profileStatus.missing.length || 0;
  return (
    <LangContext.Provider value={lang}>
      <AppHeader lang={lang} setLang={setLang} />
      <main className="landing cases-home">
        <h2 data-testid="greeting">{me?.firstName ? t("hello").replace("{name}", me.firstName) : t("myCases")}</h2>
        {me && missing > 0 && (
          <Link className="banner warn profile-banner" to="/profile" data-testid="profile-banner">
            ⚠️ {t("detailsMissing").replace("{n}", String(missing))} →
          </Link>
        )}
        <section className="card new-case">
          <h3>{t("startNewCase")}</h3>
          <div className="pickers">
            <label>{t("country")}
              <div className="seg">
                {(["IN", "MY"] as Country[]).map((c) => (
                  <button key={c} className={`seg-btn ${country === c ? "on" : ""}`} onClick={() => { setCountry(c); if (!COUNTRY_LANGS[c].includes(clang)) setClang("en"); }}>
                    {c === "IN" ? "🇮🇳 India" : "🇲🇾 Malaysia"}
                  </button>
                ))}
              </div>
            </label>
            <label>{t("language")}
              <div className="seg">
                {COUNTRY_LANGS[country].map((l) => (
                  <button key={l} className={`seg-btn ${clang === l ? "on" : ""}`} onClick={() => setClang(l)}>{LANG_LABEL[l]}</button>
                ))}
              </div>
            </label>
          </div>
          <button className="btn primary cta" onClick={start} disabled={busy} data-testid="start-case">{t("startCase")}</button>
        </section>
        <section className="case-list">
          <h3>{t("myCases")}</h3>
          {rows && rows.length === 0 && <p className="muted">{t("noCases")}</p>}
          {rows && rows.length > 0 && (
            <ul className="cases" data-testid="case-list">
              {rows.map((r) => (
                <li key={r.id}>
                  <Link to={`/cases/${r.id}`}>
                    <code>{r.publicRef || r.id.slice(0, 10)}</code>
                    <span>{new Date(r.createdAt).toLocaleDateString()}</span>
                    <span>{r.amount || "—"}</span>
                    <span className={`pill status-${r.status}`}>{t(`status.${r.status}`)}</span>
                    {r.nextDeadline && <span className="small">{t("nextDeadline")}: {r.nextDeadline.label} · {r.nextDeadline.dueDisplay}</span>}
                    {r.sandbox !== false && <span className="pill sandbox-pill">{t("sandboxPill")}</span>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
        {err && <p className="error">{err}</p>}
        <EmergencyStrip countries={me?.profile.country ? [me.profile.country as Country] : undefined} />
        <Disclaimer />
      </main>
    </LangContext.Provider>
  );
}
