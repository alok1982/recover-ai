/** CR-03 D: voice-note recording that works on Chrome (webm/opus), Safari/iOS (mp4) and Firefox (ogg/opus). */

export const MIME_PREFS = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"];
export const MIN_MS = 500;
export const MAX_MS = 120_000;

export function pickMime(): string | undefined {
  const MR = (window as any).MediaRecorder;
  if (!MR?.isTypeSupported) return undefined;
  return MIME_PREFS.find((m) => MR.isTypeSupported(m));
}

/** WhatsApp / Gmail / Facebook / Instagram in-app webviews often have no (or a broken) microphone. */
export function inAppBrowser(ua = navigator.userAgent): boolean {
  return /WhatsApp|GSA\/|Gmail|FBAN|FBAV|Instagram|Line\/|; wv\)/i.test(ua);
}

export function isIos(ua = navigator.userAgent): boolean {
  return /iPhone|iPad|iPod/i.test(ua);
}

/** Map getUserMedia / MediaRecorder failures to an i18n key. */
export function micErrorKey(err: unknown): string {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) return "micInsecure";
  const name = (err as any)?.name;
  if (name === "NotAllowedError" || name === "SecurityError") return "micBlocked";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "micNotFound";
  return "micUnsupported";
}

export interface Recording {
  stop: () => void;
}

/** Start recording (call only from a user tap). Resolves with a handle; `onDone` gets the blob (or null if too short). */
export async function startRecording(onDone: (blob: Blob | null, ms: number) => void): Promise<Recording> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw Object.assign(new Error("insecure"), { name: "InsecureContext" });
  }
  if (!(window as any).MediaRecorder) throw Object.assign(new Error("no MediaRecorder"), { name: "NotSupportedError" });
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = pickMime();
  let rec: MediaRecorder;
  try {
    rec = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  } catch (e) {
    stream.getTracks().forEach((tr) => tr.stop());
    throw e;
  }
  const chunks: Blob[] = [];
  const started = Date.now();
  let cap = 0;
  rec.ondataavailable = (e) => {
    if (e.data.size) chunks.push(e.data);
  };
  rec.onstop = () => {
    window.clearTimeout(cap);
    stream.getTracks().forEach((tr) => tr.stop());
    const ms = Date.now() - started;
    const blob = new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" });
    console.info("[voice] recorded", { type: blob.type, size: blob.size, ms });
    onDone(ms < MIN_MS || blob.size === 0 ? null : blob, ms);
  };
  rec.start(250);
  cap = window.setTimeout(() => rec.state === "recording" && rec.stop(), MAX_MS);
  return { stop: () => rec.state === "recording" && rec.stop() };
}
