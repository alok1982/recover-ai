import { useRef, useState } from "react";
import { api, uploadFile } from "../lib/api";
import { useCopilot } from "../copilot/context";
import { useT } from "../i18n";
import type { CardProps } from ".";

interface Item { id: string; label: string; type: string; at?: string; preview?: string; sha256?: string }

export function fmtTime(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function UploadCard({ data, messageId }: CardProps) {
  const { caseId, trigger, apply, busy, latestCardId } = useCopilot();
  const t = useT();
  const [items, setItems] = useState<Item[]>([]);
  const [paste, setPaste] = useState("");
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [recording, setRecording] = useState<MediaRecorder | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const camRef = useRef<HTMLInputElement>(null);
  const active = latestCardId("upload") === messageId;

  const add = async (files: FileList | null) => {
    if (!files) return;
    setWorking(true);
    setErr(null);
    try {
      for (const f of Array.from(files).slice(0, 5)) {
        const r = await uploadFile(caseId, f, "evidence", f.name);
        setItems((x) => [...x, { id: r.evidence.id, label: f.name, type: r.evidence.type, at: r.evidence.uploadedAt,
          preview: f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined, sha256: r.evidence.sha256 }]);
        if (r.messages?.length) apply({ messages: r.messages });
      }
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setWorking(false);
    }
  };

  const addText = async () => {
    if (!paste.trim()) return;
    setWorking(true);
    try {
      const r = await api.post<{ evidence: any; messages: any[] }>(`/api/cases/${caseId}/evidence`, { type: "text", textContent: paste });
      setItems((x) => [...x, { id: r.evidence.id, label: paste.slice(0, 60) + (paste.length > 60 ? "…" : ""), type: r.evidence.type,
        at: r.evidence.uploadedAt, sha256: r.evidence.sha256 }]);
      if (r.messages?.length) apply({ messages: r.messages });
      setPaste("");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setWorking(false);
    }
  };

  const recordNote = async () => {
    if (recording) {
      recording.stop();
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mr = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    mr.ondataavailable = (e) => chunks.push(e.data);
    mr.onstop = async () => {
      stream.getTracks().forEach((x) => x.stop());
      setRecording(null);
      const blob = new File(chunks, "voice-note.webm", { type: mr.mimeType || "audio/webm" });
      const dt = new DataTransfer();
      dt.items.add(blob);
      await add(dt.files);
    };
    mr.start();
    setRecording(mr);
    window.setTimeout(() => mr.state === "recording" && mr.stop(), 120000);
  };

  return (
    <div className="card upload-card">
      <h3>{t("uploadTitle")}</h3>
      <p className="muted">{data?.prompt || t("uploadHint")}</p>
      <div className="row wrap">
        <button className="btn" onClick={() => fileRef.current?.click()} disabled={working || !active}>🖼️ {t("chooseFiles")}</button>
        <button className="btn camera" onClick={() => camRef.current?.click()} disabled={working || !active}>📷 {t("camera")}</button>
        <button className={`btn ${recording ? "danger" : ""}`} onClick={recordNote} disabled={working || !active}>🎤 {recording ? t("stop") : t("recordNote")}</button>
        <input ref={fileRef} type="file" hidden multiple accept="image/png,image/jpeg,image/webp,audio/mpeg,audio/mp4,audio/x-m4a,audio/wav,audio/webm" onChange={(e) => add(e.target.files)} />
        <input ref={camRef} type="file" hidden accept="image/*" capture="environment" data-testid="camera-input" onChange={(e) => add(e.target.files)} />
      </div>
      <textarea className="paste" placeholder={t("pasteText")} value={paste} onChange={(e) => setPaste(e.target.value)} rows={3} disabled={!active} />
      <button className="btn" onClick={addText} disabled={!paste.trim() || working || !active}>{t("addText")}</button>
      {items.length > 0 && (
        <ul className="evidence-list">
          {items.map((i) => (
            <li key={i.id}>
              {i.preview ? <img src={i.preview} alt="" /> : <span className="doc-ic">📄</span>}
              <span className="ev-meta">
                <span className="ev-label">{i.label}</span>
                <span className="muted small ev-type-time">{t(`evType.${i.type}`)} · {fmtTime(i.at)}</span>
              </span>
              <code title={`SHA-256 ${i.sha256 || ""}`}>{i.sha256?.slice(0, 12)}…</code>
            </li>
          ))}
        </ul>
      )}
      {working && <p className="muted">{t("uploading")}</p>}
      {err && <p className="error">{err}</p>}
      {items.length > 0 && active && (
        <button className="btn primary big" disabled={busy || working} onClick={() => trigger("evidence_added", { evidenceIds: items.map((i) => i.id) })}>
          {t("readEvidence")}
        </button>
      )}
    </div>
  );
}
