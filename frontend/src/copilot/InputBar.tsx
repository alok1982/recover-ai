import { useRef, useState } from "react";
import { uploadFile, uploadVoice } from "../lib/api";
import { useHealth } from "../lib/health";
import { inAppBrowser, isIos, micErrorKey, startRecording, type Recording } from "./recorder";
import { useT } from "../i18n";
import { useCopilot } from "./context";

export function InputBar() {
  const { send, busy, caseId, sendVoice, trigger, apply, hint, setHint } = useCopilot();
  const health = useHealth();
  const voiceOn = health?.voiceEnabled !== false;
  const [transcribing, setTranscribing] = useState(false);
  const t = useT();
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const rec = useRef<Recording | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = async () => {
    const v = text.trim();
    if (!v || busy) return;
    setText("");
    setHint(null);
    await send(v);
  };

  const toggleRecord = async () => {
    if (recording) {
      rec.current?.stop();
      return;
    }
    setHint(null);
    try {
      rec.current = await startRecording(async (blob) => {
        rec.current = null;
        setRecording(false);
        if (!blob) {
          setHint(t("voiceTooShort"));
          return;
        }
        setTranscribing(true);
        try {
          const r = await uploadVoice(caseId, blob);
          setTranscribing(false);
          await sendVoice(r.audioPath, r.transcript);
        } catch (err) {
          console.warn("[voice] upload/transcribe failed", err);
          setHint(t("voiceUnclear"));
        } finally {
          setTranscribing(false);
        }
      });
      setRecording(true);
    } catch (err) {
      console.warn("[voice] microphone error", (err as any)?.name, err);
      const key = micErrorKey(err);
      const help = key !== "micBlocked" ? "" : isIos() ? t("micHelpIos") : /Android/i.test(navigator.userAgent) ? t("micHelpAndroid") : "";
      setHint(t(key) + (help ? " — " + help : ""));
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
    <>
    {(hint || transcribing || (voiceOn && inAppBrowser())) && (
      <div className="input-hint" role="status" data-testid="voice-hint">
        {transcribing ? t("transcribing") : hint || t("inAppBrowser")}
      </div>
    )}
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
      {voiceOn && (
        <button className={`icon-btn mic ${recording ? "rec" : ""}`} aria-label={recording ? t("stop") : t("record")} onClick={toggleRecord}
          disabled={(busy || transcribing) && !recording}>
          {recording ? "■" : "🎤"}
        </button>
      )}
      <button className="btn primary send" onClick={submit} disabled={busy || !text.trim()}>{t("send")}</button>
    </div>
    </>
  );
}
