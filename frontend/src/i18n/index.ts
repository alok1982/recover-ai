import { createContext, useContext } from "react";
import en from "./en.json";
import hi from "./hi.json";
import ms from "./ms.json";
import type { Lang } from "../lib/types";

const TABLES: Record<Lang, Record<string, string>> = { en, hi, ms };

export function translate(lang: Lang, key: string): string {
  return TABLES[lang]?.[key] ?? (TABLES.en as Record<string, string>)[key] ?? key;
}

export const LangContext = createContext<Lang>("en");

export function useT() {
  const lang = useContext(LangContext);
  return (key: string) => translate(lang, key);
}

export const LANG_LABEL: Record<Lang, string> = { en: "English", hi: "हिन्दी", ms: "Bahasa Melayu" };
// English first: it is the default for new visitors; the local language stays one tap away.
export const DEFAULT_LANG: Lang = "en";
export const COUNTRY_LANGS: Record<string, Lang[]> = { IN: ["en", "hi"], MY: ["en", "ms"] };
export const COMING_SOON = [
  { code: "SG", name: "Singapore", text: "Police report + bank; Shared Responsibility Framework payouts for covered phishing scams (since 16 Dec 2024)." },
  { code: "ID", name: "Indonesia", text: "Report to Indonesia Anti-Scam Centre (iasc.ojk.go.id) or your bank; accounts can be blocked and funds returned." },
  { code: "PH", name: "Philippines", text: "Bank dispute triggers a temporary hold of disputed funds for up to 30 days under AFASA." },
  { code: "AU", name: "Australia", text: "Your bank + ReportCyber/Scamwatch; Scams Prevention Framework duties." },
  { code: "JP", name: "Japan", text: "Police and your bank; frozen account balances can be distributed to victims." },
  { code: "KR", name: "Korea", text: "Bank or FSS 1332 for payment suspension; refund without a lawsuit under the Refund Act." },
];
