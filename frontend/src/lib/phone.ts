/** CR-03 B: phone + password accounts use Firebase Email/Password with a synthetic email that is never shown. */
export const PHONE_DOMAIN = "phone.recoverai.app";
export const DIAL: Record<"IN" | "MY", string> = { IN: "+91", MY: "+60" };

/** QA BUG-06: per-country mobile rules (the same rules as backend/app/profile.py `normalize_phone`).
 *  India: 10 digits starting 6–9. Malaysia: 9–10 digits after 60, starting 1. The seed numbers
 *  (+91 90000 0000x, +60 10000 000x) satisfy these rules. */
const RULE: Record<"IN" | "MY", RegExp> = { IN: /^[6-9]\d{9}$/, MY: /^1\d{8,9}$/ };

/** '+91 90000 00001', '090000-00001', '9000000001', '91 9000000001' (IN) → '+919000000001'; null when the number is
 *  not a valid mobile for that country. An explicit +91 / +60 picks that country's rules; any other country code is
 *  rejected. */
export function toE164(country: "IN" | "MY", raw: string): string | null {
  let s = (raw || "").trim().replace(/[\s\-.()\u00a0]/g, "");
  if (s.startsWith("00")) s = "+" + s.slice(2);
  let cc: "IN" | "MY" = country;
  if (s.startsWith("+")) {
    if (s.startsWith("+91")) cc = "IN";
    else if (s.startsWith("+60")) cc = "MY";
    else return null;
    s = s.slice(3);
  } else if (!/^\d+$/.test(s)) {
    return null;
  } else if (country === "IN" && s.length === 12 && s.startsWith("91")) {
    s = s.slice(2);
  } else if (country === "MY" && s.startsWith("60") && (s.length === 11 || s.length === 12)) {
    s = s.slice(2);
  }
  if (!/^\d+$/.test(s)) return null;
  s = s.replace(/^0/, "");
  return RULE[cc].test(s) ? `${DIAL[cc]}${s}` : null;
}

export function phoneEmail(e164: string): string {
  return `${e164.replace(/^\+/, "")}@${PHONE_DOMAIN}`;
}

export function passwordOk(pw: string): boolean {
  return pw.length >= 8 && /[A-Za-z]/.test(pw) && /\d/.test(pw);
}
