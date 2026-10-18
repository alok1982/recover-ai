import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useVictim, victimSignOut } from "../lib/auth";
import type { Lang } from "../lib/types";
import { LANG_LABEL, useT } from "../i18n";
import { useDemo } from "../lib/health";
import { Logo } from "./Logo";

/** Shared header for the victim pages: brand, EN/HI/MS switch, account menu (My cases · Profile · Log out). */
export function AppHeader({ lang, setLang, children }: { lang?: Lang; setLang?: (l: Lang) => void; children?: React.ReactNode }) {
  const t = useT();
  const nav = useNavigate();
  const me = useVictim();
  const [open, setOpen] = useState(false);
  return (
    <>
      <DemoRibbon />
      <header className="top site-head">
        <Link className="brand small" to="/" aria-label="RecoverAI home"><Logo height={34} /></Link>
        <div className="row">
          {children}
          {setLang && (
            <div className="seg lang-switch" role="group" aria-label={t("language")}>
              {(["en", "hi", "ms"] as Lang[]).map((l) => (
                <button key={l} className={`seg-btn ${lang === l ? "on" : ""}`} title={LANG_LABEL[l]} onClick={() => setLang(l)}>
                  {l.toUpperCase()}
                </button>
              ))}
            </div>
          )}
          {me ? (
            <div className="menu">
              <button className="btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} data-testid="account-menu">☰</button>
              {open && (
                <div className="menu-pop" role="menu">
                  <Link role="menuitem" to="/cases" onClick={() => setOpen(false)}>{t("myCases")}</Link>
                  <Link role="menuitem" to="/profile" onClick={() => setOpen(false)}>{t("profile")}</Link>
                  <button role="menuitem" className="link" data-testid="logout" onClick={async () => { setOpen(false); await victimSignOut(); nav("/"); }}>{t("logOut")}</button>
                </div>
              )}
            </div>
          ) : me === null ? (
            <Link className="btn" to="/login">{t("signIn")}</Link>
          ) : null}
        </div>
      </header>
    </>
  );
}

export function DemoRibbon() {
  const t = useT();
  return useDemo() ? <div className="demo-ribbon" data-testid="demo-ribbon">{t("demoRibbon")}</div> : null;
}
