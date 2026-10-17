import { useRef, useState } from "react";
import { uploadFile } from "../lib/api";
import { useT } from "../i18n";
import { useCopilot } from "./context";

export function InputBar() {
  const { send, busy, caseId, sendVoice, trigger, apply } = useCopilot();
  const t = useT();
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = async () => {
    const v = text.trim();
    if (!v || busy) return;
    setText("");
    await send(v);
  };

  const toggleRecord = async () => {
    if (recording) {
      rec.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunks.current = [];
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((tr) => tr.stop());
        setRecording(false);
        const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
        const { path } = await uploadFile(caseId, blob, "voice");
        await sendVoice(path);
      };
      mr.start();
      rec.current = mr;
      setRecording(true);
      window.setTimeout(() => mr.state === "recording" && mr.stop(), 120000); // 2-minute cap
    } catch {
      alert("Microphone not available");
    }
  };

  const attach = async (files: FileList | null) => {
    if (!files?.length) return;
    const ids: string[] = [];
    for (const f of Array.from(files).slice(0, 5)) {
      const r = await uploadFile(caseId, f, "evidence", f.name);
      ids.push(r.evidence.id);
      if (r.messages?.length) apply({ messages: r.messages });
    }
    await trigger("evidence_added", { evidenceIds: ids });
  };

  return (
    <div className="inputbar">
      <button className="icon-btn" aria-label={t("attach")} onClick={() => fileRef.current?.click()} disabled={busy}>📎</button>
      <input ref={fileRef} type="file" hidden multiple accept="image/png,image/jpeg,image/webp,audio/*" onChange={(e) => attach(e.target.files)} />
      <textarea
        value={text}
        placeholder={t("typeMessage")}
        rows={1}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
      />
      <button className={`icon-btn mic ${recording ? "rec" : ""}`} aria-label={recording ? t("stop") : t("record")} onClick={toggleRecord} disabled={busy && !recording}>
        {recording ? "■" : "🎤"}
      </button>
      <button className="btn primary send" onClick={submit} disabled={busy || !text.trim()}>{t("send")}</button>
    </div>
  );
}
