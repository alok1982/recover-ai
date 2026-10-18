import { useEffect, useState } from "react";
import { API_BASE } from "./config";

/** CR-01: server flags the UI needs (live submission allowed? sandbox default?). Fetched once, unauthenticated. */
export interface Health {
  allowLiveSubmission?: boolean;
  sandboxDefault?: boolean;
  chatLight?: string | null;
  voiceEnabled?: boolean;
  demo?: boolean;
}

let cached: Promise<Health> | null = null;

export function loadHealth(): Promise<Health> {
  if (!cached) {
    cached = fetch(`${API_BASE}/api/health`).then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  }
  return cached;
}

export function useHealth(): Health | null {
  const [h, setH] = useState<Health | null>(null);
  useEffect(() => {
    let live = true;
    loadHealth().then((x) => live && setH(x));
    return () => { live = false; };
  }, []);
  return h;
}
