import type { Lang } from "./types";

const KEY = "recoverai.lang";

export function savedLang(): Lang {
  const v = localStorage.getItem(KEY);
  return v === "hi" || v === "ms" || v === "en" ? v : "en";
}

export function saveLang(l: Lang): void {
  localStorage.setItem(KEY, l);
}
