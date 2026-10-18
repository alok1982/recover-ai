import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import type { Country, Lang } from "../lib/types";
import { COUNTRY_LANGS, LANG_LABEL, LangContext, translate } from "../i18n";
import { saveLang, savedLang } from "../lib/prefs";
import { AuthError, victimSignIn, victimSignUp } from "../lib/auth";
import { DIAL, passwordOk, toE164 } from "../lib/phone";
import { acceptTerms, saveProfile, TERMS_VERSION } from "../lib/me";
import { AppHeader } from "../ui/AppHeader";
import { EmergencyStrip } from "../ui/EmergencyStrip";

function safeNext(n: string | null): string {
  return n && n.startsWith("/") && !n.startsWith("//") ? n : "/cases";
}

function PhoneInput({ country, setCountry, phone, setPhone, t }: {
  country: Country; setCountry: (c: Country) => void; phone: string; setPhone: (p: string) => void; t: (k: string) => string;
}) {
  return (
    <label>{t("mobile")}
      <div className="phone-input">
        <select aria-label={t("country")} value={country} onChange={(e) => setCountry(e.target.value as Country)} data-testid="cc">
          <option value="IN">🇮🇳 {DIAL.IN}</option>
          <option value="MY">🇲🇾 {DIAL.MY}</option>
        </select>
        <input type="tel" inputMode="tel" autoComplete="tel-national" value={phone} onChange={(e) => setPhone(e.target.value)}
          placeholder={country === "IN" ? "90000 00001" : "10000 0001"} name="phone" />
      </div>
    </label>
  );
}

function useLang(): [Lang, (l: Lang) => void, (k: string) => string] {
  const [lang, setL] = useState<Lang>(savedLang());
  return [lang, (l) => { saveLang(l); setL(l); }, (k) => translate(lang, k)];
}

function authMsg(e: unknown): string {
  const c = e instanceof AuthError ? e.code : "other";
  return c === "bad_credentials" ? "errBadLogin" : c === "exists" ? "errExists" : c === "weak" ? "errPassword" : c === "network" ? "errNetwork" : "errNetwork";
}

export function Signup() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [lang, setLang, t] = useLang();
  const [country, setCountry] = useState<Country>(lang === "ms" ? "MY" : "IN");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [show, setShow] = useState(false);
  const [plang, setPlang] = useState<Lang>(COUNTRY_LANGS[country].includes(lang) ? lang : "en");
  const [terms, setTerms] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const e164 = toE164(country, phone);
    const n = name.trim();
    const problem = !e164 ? "errPhone" : n.length < 2 || n.length > 80 ? "errName" : !passwordOk(pw) ? "errPassword"
      : pw !== pw2 ? "errMatch" : !terms ? "errTerms" : null;
    if (problem) return setErr(problem);
    setBusy(true);
    setErr(null);
    try {
      await victimSignUp(e164!, pw);
      await acceptTerms(TERMS_VERSION);
      await saveProfile({ fullName: n, country, language: plang });
      saveLang(plang);
      nav(safeNext(params.get("next")));
    } catch (x) {
      console.warn("signup failed", x);
      setErr(authMsg(x));
    } finally {
      setBusy(false);
    }
  };

  return (
    <LangContext.Provider value={lang}>
      <AppHeader lang={lang} setLang={setLang} />
      <main className="landing auth">
        <h2>{t("signUp")}</h2>
        <form className="form" onSubmit={submit} noValidate>
          <PhoneInput country={country} setCountry={(c) => { setCountry(c); if (!COUNTRY_LANGS[c].includes(plang)) setPlang("en"); }} phone={phone} setPhone={setPhone} t={t} />
          <label>{t("fullName")}<input name="fullName" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></label>
          <label>{t("password")}<input name="password" type={show ? "text" : "password"} autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
          <label>{t("confirmPassword")}<input name="password2" type={show ? "text" : "password"} autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} /></label>
          <label className="check"><input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} /> {t("showPassword")}</label>
          <p className="small muted">{t("passwordRule")}</p>
          <label>{t("preferredLanguage")}
            <select name="language" value={plang} onChange={(e) => setPlang(e.target.value as Lang)}>
              {COUNTRY_LANGS[country].map((l) => <option key={l} value={l}>{LANG_LABEL[l]}</option>)}
            </select>
          </label>
          <label className="check terms"><input type="checkbox" name="terms" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
            <span>{t("termsAgree")} <a href="/privacy" target="_blank">{t("privacyLink")}</a><br /><span className="small muted">{t("termsPurpose")}</span></span>
          </label>
          {err && <p className="error" role="alert" data-testid="auth-error">{t(err)}</p>}
          <button className="btn primary cta" type="submit" disabled={busy}>{t("signUp")}</button>
        </form>
        <Link className="link" to={`/login${params.get("next") ? `?next=${encodeURIComponent(params.get("next")!)}` : ""}`}>{t("haveAccount")}</Link>
        <EmergencyStrip countries={[country]} />
      </main>
    </LangContext.Provider>
  );
}

export function Login() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [lang, setLang, t] = useLang();
  const [country, setCountry] = useState<Country>(lang === "ms" ? "MY" : "IN");
  const [phone, setPhone] = useState("");
  const [pw, setPw] = useState("");
  const [show, setShow] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const e164 = toE164(country, phone);
    if (!e164 || !pw) return setErr("errBadLogin");
    setBusy(true);
    setErr(null);
    try {
      await victimSignIn(e164, pw);
      nav(safeNext(params.get("next")));
    } catch (x) {
      setErr(authMsg(x));
    } finally {
      setBusy(false);
    }
  };

  return (
    <LangContext.Provider value={lang}>
      <AppHeader lang={lang} setLang={setLang} />
      <main className="landing auth">
        <h2>{t("signIn")}</h2>
        <form className="form" onSubmit={submit} noValidate>
          <PhoneInput country={country} setCountry={setCountry} phone={phone} setPhone={setPhone} t={t} />
          <label>{t("password")}<input name="password" type={show ? "text" : "password"} autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
          <label className="check"><input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} /> {t("showPassword")}</label>
          {err && <p className="error" role="alert" data-testid="auth-error">{t(err)}</p>}
          <button className="btn primary cta" type="submit" disabled={busy}>{t("signIn")}</button>
        </form>
        <Link className="link" to={`/signup${params.get("next") ? `?next=${encodeURIComponent(params.get("next")!)}` : ""}`}>{t("noAccount")}</Link>
        <EmergencyStrip countries={[country]} />
      </main>
    </LangContext.Provider>
  );
}
