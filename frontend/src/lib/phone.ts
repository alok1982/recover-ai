import { parsePhoneNumberFromString } from "libphonenumber-js";

/** CR-03 B: phone + password accounts use Firebase Email/Password with a synthetic email that is never shown. */
export const PHONE_DOMAIN = "phone.recoverai.app";
export const DIAL: Record<"IN" | "MY", string> = { IN: "+91", MY: "+60" };

/** The CR's fictional seed numbers (+91 90000 0000x, +60 10000 000x) are not "valid" mobiles to libphonenumber. */
const DEMO = /^\+91900000000\d$|^\+60100000\d{3}$/;

export function toE164(country: "IN" | "MY", raw: string): string | null {
  const s = raw.trim();
  const p = parsePhoneNumberFromString(s.startsWith("+") ? s : `${DIAL[country]}${s.replace(/^0+/, "")}`, country);
  if (!p) return null;
  const e = p.number as string;
  if (DEMO.test(e)) return e;
  if (!p.isValid() || !["IN", "MY"].includes(p.country || "")) return null;
  return e;
}

export function phoneEmail(e164: string): string {
  return `${e164.replace(/^\+/, "")}@${PHONE_DOMAIN}`;
}

export function passwordOk(pw: string): boolean {
  return pw.length >= 8 && /[A-Za-z]/.test(pw) && /\d/.test(pw);
}
