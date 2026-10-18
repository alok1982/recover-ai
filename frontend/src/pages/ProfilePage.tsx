import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteMe, getMe, REQUIRED, type Me } from "../lib/me";
import type { Lang } from "../lib/types";
import { LangContext, translate } from "../i18n";
import { saveLang, savedLang } from "../lib/prefs";
import { victimForget } from "../lib/auth";
import { AppHeader } from "../ui/AppHeader";
import { ProfileForm } from "../profile/ProfileForm";

export function ProfilePage() {
  const nav = useNavigate();
  const [me, setMe] = useState<Me | null>(null);
  const [lang, setLangState] = useState<Lang>(savedLang());
  const setLang = (l: Lang) => { saveLang(l); setLangState(l); };
  const t = (k: string) => translate(lang, k);
  useEffect(() => { getMe().then(setMe); }, []);
  const pct = me ? Math.round(((REQUIRED.length - me.profileStatus.missing.length) / REQUIRED.length) * 100) : 0;
  const del = async () => {
    if (!confirm(t("deleteAccountConfirm"))) return;
    await deleteMe();
    try {
      await victimForget(() => prompt(t("deleteReauth")));
    } catch {
      alert(t("deleteReauthFailed"));
      return;
    }
    nav("/");
  };
  return (
    <LangContext.Provider value={lang}>
      <AppHeader lang={lang} setLang={setLang} />
      <main className="landing profile-page">
        <h2>{t("profileTitle")}</h2>
        {me && (
          <>
            <div className="meter" data-testid="profile-meter" aria-label={t("profileComplete").replace("{pct}", String(pct))}>
              <div className="meter-bar" style={{ width: `${pct}%` }} />
              <span className="small">{t("profileComplete").replace("{pct}", String(pct))}</span>
            </div>
            <p className="small muted">{me.phoneMasked} {!me.phoneVerified && `· ${t("phoneNotVerified")}`}</p>
            <p className="small">{t("profileWhy")}</p>
            <ProfileForm me={me} onSaved={(m) => setMe({ ...me, ...m })} />
            <button className="btn danger" onClick={del} data-testid="delete-account">{t("deleteAccount")}</button>
          </>
        )}
      </main>
    </LangContext.Provider>
  );
}
