const env = import.meta.env;

export const MOCK = env.VITE_MOCK === "true" || !env.VITE_FIREBASE_API_KEY;
export const API_BASE = (env.VITE_API_BASE || "").replace(/\/$/, "");
export const CHAT_BASE = (env.VITE_CHAT_BASE || API_BASE).replace(/\/$/, "");
export const DEMO_UI = env.VITE_DEMO_MODE !== "false";
export const FIREBASE_CONFIG = {
  apiKey: env.VITE_FIREBASE_API_KEY,
  authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: env.VITE_FIREBASE_PROJECT_ID,
  appId: env.VITE_FIREBASE_APP_ID,
};

/** Resolve a URL returned by the API (signed GCS URL, or a relative local-blob URL in mock mode). */
export function resolveUrl(url: string): string {
  return url.startsWith("/") ? `${API_BASE}${url}` : url;
}
