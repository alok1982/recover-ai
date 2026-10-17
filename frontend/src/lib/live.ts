import { useCallback, useEffect, useRef, useState } from "react";
import { collection, doc, onSnapshot, orderBy, query, Timestamp } from "firebase/firestore";
import { api } from "./api";
import { MOCK } from "./config";
import { victimDb, ensureAnonymous } from "./firebase";
import type { CaseDoc, Message } from "./types";

/** Firestore Timestamps -> ISO strings (same shape as the REST API). */
export function plain<T>(v: any): T {
  if (v instanceof Timestamp) return v.toDate().toISOString() as any;
  if (Array.isArray(v)) return v.map((x) => plain(x)) as any;
  if (v && typeof v === "object") {
    const o: any = {};
    for (const [k, x] of Object.entries(v)) o[k] = plain(x);
    return o;
  }
  return v;
}

function merge(base: Message[], extra: Message[]): Message[] {
  const map = new Map<string, Message>();
  for (const m of [...base, ...extra]) map.set(m.id, { ...map.get(m.id), ...m });
  return [...map.values()].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
}

/** Live case + conversation: Firestore listeners in the cloud, polling in offline mock mode. */
export function useCaseLive(caseId: string | undefined) {
  const [caseDoc, setCase] = useState<CaseDoc | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const local = useRef<Message[]>([]);

  const refresh = useCallback(async () => {
    if (!caseId) return;
    try {
      const [c, m] = await Promise.all([
        api.get<{ case: CaseDoc }>(`/api/cases/${caseId}`),
        api.get<{ messages: Message[] }>(`/api/cases/${caseId}/messages`),
      ]);
      setCase(c.case);
      setMessages(merge(m.messages, local.current.filter((x) => !m.messages.some((y) => y.id === x.id))));
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  }, [caseId]);

  const addLocal = useCallback((msgs: Message[]) => {
    local.current = merge(local.current, msgs);
    setMessages((prev) => merge(prev, msgs));
  }, []);

  useEffect(() => {
    if (!caseId) return;
    let stop = () => {};
    refresh(); // also triggers lazy deadline evaluation on the server
    if (MOCK) {
      const id = window.setInterval(refresh, 2500);
      stop = () => window.clearInterval(id);
    } else {
      let unsubs: (() => void)[] = [];
      ensureAnonymous().then(() => {
        const db = victimDb();
        unsubs.push(
          onSnapshot(doc(db, "cases", caseId), (s) => s.exists() && setCase((prev) => ({ ...(prev || {}), ...plain<CaseDoc>(s.data()) }))),
          onSnapshot(query(collection(db, "cases", caseId, "messages"), orderBy("seq")), (qs) => {
            const ms = qs.docs.map((d) => plain<Message>(d.data()));
            setMessages(merge(ms, local.current.filter((x) => !ms.some((y) => y.id === x.id))));
          }, (e) => setError(e.message)),
        );
      });
      stop = () => unsubs.forEach((u) => u());
    }
    return () => stop();
  }, [caseId, refresh]);

  return { caseDoc, setCase, messages, addLocal, refresh, error };
}

export function effectiveNow(c: CaseDoc | null): number {
  return Date.now() + (c?.clockOffsetDays || 0) * 86400000;
}

export function countdown(dueIso: string, nowMs: number, overdue = "Overdue"): string {
  const ms = new Date(dueIso).getTime() - nowMs;
  const abs = Math.abs(ms);
  const d = Math.floor(abs / 86400000);
  const h = Math.floor((abs % 86400000) / 3600000);
  const m = Math.floor((abs % 3600000) / 60000);
  const s = d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
  return ms >= 0 ? s : `${overdue} ${s}`;
}
