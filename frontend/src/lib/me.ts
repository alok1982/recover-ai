import { api } from "./api";
import type { Country, Lang } from "./types";

export type ProfileField = "fullName" | "country" | "language" | "state" | "district" | "postalCode" | "primaryBank";
export const REQUIRED: ProfileField[] = ["fullName", "country", "language", "state", "district", "postalCode", "primaryBank"];

export interface Profile {
  fullName?: string;
  country?: Country;
  language?: Lang;
  state?: string;
  district?: string;
  postalCode?: string;
  primaryBank?: string;
  primaryBankOther?: string;
  email?: string;
  addressLine?: string;
  dob?: string;
  accountLast4?: string;
  altPhone?: string;
}

export interface ProfileStatus {
  complete: boolean;
  missing: ProfileField[];
}

export interface Me {
  uid: string;
  phoneMasked: string | null;
  phoneVerified: boolean;
  termsVersion: string | null;
  termsCurrent: string;
  profile: Profile;
  profileStatus: ProfileStatus;
  firstName: string | null;
  banks?: Record<string, string[]>;
}

export const TERMS_VERSION = "2026-10-cr03";

export const getMe = () => api.get<Me>("/api/me");
export const acceptTerms = (version = TERMS_VERSION) => api.post<Me>("/api/me/terms", { version });
export const saveProfile = (profile: Profile) => api.put<Me & { changed: string[] }>("/api/me/profile", { profile });
export const deleteMe = () => api.del<{ deleted: boolean }>("/api/me");

/** Client-side checks that mirror backend/app/profile.py (the backend stays the authority). */
export function fieldError(k: keyof Profile, p: Profile): string | null {
  const v = (p[k] || "").toString().trim();
  if (REQUIRED.includes(k as ProfileField) && !v) return "errRequired";
  if (k === "fullName" && (v.length < 2 || v.length > 80)) return "errName";
  if (k === "postalCode" && v) {
    if (p.country === "MY" ? !/^\d{5}$/.test(v) : !/^[1-9]\d{5}$/.test(v)) return p.country === "MY" ? "errPostalMY" : "errPostalIN";
  }
  if (k === "primaryBankOther" && p.primaryBank === "Other" && !v) return "errRequired";
  if (k === "accountLast4" && v && !/^\d{4}$/.test(v)) return "errInvalid";
  return null;
}
