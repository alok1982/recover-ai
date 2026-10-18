import { API_BASE, CHAT_BASE } from "./config";
import { bankToken, victimToken } from "./auth";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, bank = false): Promise<T> {
  const token = bank ? await bankToken() : await victimToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      msg = (await res.json()).detail || msg;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b: unknown = {}) => request<T>("POST", p, b),
  patch: <T>(p: string, b: unknown) => request<T>("PATCH", p, b),
  del: <T>(p: string) => request<T>("DELETE", p),
  bankGet: <T>(p: string) => request<T>("GET", p, undefined, true),
  bankPost: <T>(p: string, b: unknown) => request<T>("POST", p, b, true),
};

export interface SseEvent {
  type: "token" | "card" | "message" | "tool_status" | "done" | "error" | "transcript" | "user_message" | "replace" | "voice_error";
  [k: string]: any;
}

/** POST a chat turn and stream Server-Sent Events back (fetch + ReadableStream; EventSource cannot POST). */
export async function streamChat(caseId: string, body: Record<string, unknown>, onEvent: (e: SseEvent) => void): Promise<void> {
  const token = await victimToken();
  const res = await fetch(`${CHAT_BASE}/api/cases/${caseId}/chat`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    try {
      msg = (await res.json()).detail || msg;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of raw.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch {
            /* ignore malformed */
          }
        }
      }
    }
  }
}

/** Upload a file through a backend-issued signed URL, then register it as evidence. */
export async function uploadFile(caseId: string, file: Blob, purpose: "evidence" | "voice" = "evidence", fileName?: string) {
  const mimeType = file.type || "application/octet-stream";
  const u = await api.post<{ url: string; headers: Record<string, string>; path: string }>(
    `/api/cases/${caseId}/evidence/upload-url`,
    { mimeType, sizeBytes: file.size, purpose },
  );
  const put = await fetch(u.url.startsWith("/") ? `${API_BASE}${u.url}` : u.url, { method: "PUT", headers: u.headers, body: file });
  if (!put.ok) throw new ApiError(put.status, "Upload failed");
  if (purpose === "voice") return { path: u.path };
  const type = mimeType.startsWith("image/") ? "image" : "audio";
  const reg = await api.post<{ evidence: any; messages: any[] }>(`/api/cases/${caseId}/evidence`, {
    type,
    gcsPath: u.path,
    mimeType,
    fileName,
  });
  return { path: u.path, evidence: reg.evidence, messages: reg.messages };
}

/** CR-03 D: send a recorded voice note (multipart) → {audioPath, transcript}; status 422 = nothing intelligible. */
export async function uploadVoice(caseId: string, blob: Blob): Promise<{ audioPath: string; transcript: string }> {
  const token = await victimToken();
  const form = new FormData();
  const mimeType = blob.type || "audio/webm";
  const ext = mimeType.includes("mp4") ? "m4a" : mimeType.includes("ogg") ? "ogg" : "webm";
  form.append("file", blob, `voice.${ext}`);
  form.append("mimeType", mimeType);
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/voice`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form });
  if (!res.ok) {
    let code = res.statusText;
    try {
      const j = await res.json();
      code = j.code || j.detail || code;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(code));
  }
  return res.json();
}
