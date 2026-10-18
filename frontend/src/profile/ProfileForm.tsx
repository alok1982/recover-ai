import { useState } from "react";
import type { Country, Lang } from "../lib/types";
import { COUNTRY_LANGS, LANG_LABEL, useT } from "../i18n";
import { ApiError } from "../lib/api";
import { fieldError, saveProfile, type Me, type Profile } from "../lib/me";

type Field = keyof Profile;
const OPTIONAL: Field[] = ["email", "addressLine", "dob", "accountLast4", "altPhone"];
const LABEL: Partial<Record<Field, string>> = {
  fullName: "fullName", state: "state", district: "district", primaryBank: "primaryBank", email: "emailOpt",
  addressLine: "addressOpt", dob: "dobOpt", accountLast4: "last4Opt", altPhone: "altPhoneOpt", country: "country", language: "language",
};

const FALLBACK_BANKS: Record<string, string[]> = { IN: ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank"], MY: ["Maybank", "CIMB Bank", "Public Bank"] };

/** CR-03 C: profile editor. `fields` limits it to the missing ones (the co-pilot's profile card). Saving always goes
 *  through PUT /api/me/profile — the co-pilot never saves on the user's behalf. */
export function ProfileForm({ me, fields, prefill, onSaved, compact }: {
  me: Me; fields?: Field[]; prefill?: Profile; onSaved?: (me: Me) => void; compact?: boolean;
}) {
  const t = useT();
  const [p, setP] = useState<Profile>({ ...me.profile, ...(prefill || {}) });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const country: Country = (p.country as Country) || "IN";
  const banks = me.banks?.[country] || FALLBACK_BANKS[country];
  const show: Field[] = fields?.length ? [...fields, ...(fields.includes("primaryBank") ? ["primaryBankOther" as Field] : [])]
    : ["fullName", "country", "language", "state", "district", "postalCode", "primaryBank", "primaryBankOther", ...OPTIONAL];
  const set = (k: Field, v: string) => { setP((x) => ({ ...x, [k]: v })); setErrs((e) => ({ ...e, [k]: "" })); setDone(false); };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const local: Record<string, string> = {};
    for (const k of show) {
      if (k === "primaryBankOther" && p.primaryBank !== "Other") continue;
      const er = fieldError(k, p);
      if (er) local[k] = er;
    }
    if (Object.keys(local).length) return setErrs(local);
    setBusy(true);
    try {
      const patch: Profile = {};
      for (const k of show) (patch as any)[k] = (p as any)[k] ?? "";
      const r = await saveProfile(patch);
      setDone(true);
      onSaved?.(r);
    } catch (x) {
      const d = x instanceof ApiError ? x.detail : null;
      if (d?.errors) setErrs(Object.fromEntries(Object.keys(d.errors).map((k) => [k, k === "postalCode" ? (country === "MY" ? "errPostalMY" : "errPostalIN") : "errInvalid"])));
      else setErrs({ _: "errNetwork" });
    } finally {
      setBusy(false);
    }
  };

  const input = (k: Field) => {
    if (k === "country") {
      return (
        <select name="country" value={country} onChange={(e) => {
          const c = e.target.value as Country;
          setP((x) => ({ ...x, country: c, language: COUNTRY_LANGS[c].includes(x.language as Lang) ? x.language : "en", primaryBank: "" }));
        }}>
          <option value="IN">🇮🇳 India</option>
          <option value="MY">🇲🇾 Malaysia</option>
        </select>
      );
    }
    if (k === "language") {
      return (
        <select name="language" value={p.language || "en"} onChange={(e) => set("language", e.target.value)}>
          {COUNTRY_LANGS[country].map((l) => <option key={l} value={l}>{LANG_LABEL[l]}</option>)}
        </select>
      );
    }
    if (k === "primaryBank") {
      return (
        <select name="primaryBank" value={p.primaryBank || ""} onChange={(e) => set("primaryBank", e.target.value)}>
          <option value="">{t("chooseBank")}</option>
          {banks.map((b) => <option key={b} value={b}>{b}</option>)}
          <option value="Other">{t("bankOther")}</option>
        </select>
      );
    }
    const type = k === "dob" ? "date" : k === "email" ? "email" : k === "altPhone" ? "tel" : "text";
    const mode = k === "postalCode" || k === "accountLast4" ? "numeric" : undefined;
    return <input name={k} type={type} inputMode={mode} value={(p as any)[k] || ""} onChange={(e) => set(k, e.target.value)}
      maxLength={k === "postalCode" ? 6 : k === "accountLast4" ? 4 : 200} />;
  };

  return (
    <form className={`form profile-form ${compact ? "compact" : ""}`} onSubmit={submit} noValidate data-testid="profile-form">
      {show.map((k) => {
        if (k === "primaryBankOther" && p.primaryBank !== "Other") return null;
        const label = k === "postalCode" ? (country === "MY" ? "postalCodeMY" : "postalCodeIN") : k === "primaryBankOther" ? "bankOtherName" : LABEL[k] || k;
        return (
          <label key={k} className={errs[k] ? "has-error" : ""}>
            {t(label)}
            {input(k)}
            {errs[k] && <span className="field-error">{t(errs[k])}</span>}
          </label>
        );
      })}
      {errs._ && <p className="error">{t(errs._)}</p>}
      <button className="btn primary" type="submit" disabled={busy} data-testid="profile-save">{done ? `✓ ${t("saved")}` : t("save")}</button>
    </form>
  );
}
