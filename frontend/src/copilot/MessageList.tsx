import { useEffect, useRef } from "react";
import type { Message } from "../lib/types";
import { CardView } from "../cards";
import { useT } from "../i18n";
import { DEMO_UI } from "../lib/config";

/** F17 demo chip: which model wrote this reply. */
export function ModelChip({ m }: { m: Message }) {
  if (!DEMO_UI || m.role !== "assistant" || !m.text || !m.model) return null;
  const gemma = m.model.startsWith("gemma");
  const title = gemma
    ? `${m.model}${m.route?.firstTokenMs != null ? ` · first token ${m.route.firstTokenMs} ms` : ""}`
    : m.model === "gemini-fallback"
      ? `Gemini (Gemma fallback: ${m.route?.fallback ?? "?"})`
      : m.model;
  return <span className={`model-chip ${gemma ? "gemma" : "gemini"}`} title={title} data-model={m.model}>{gemma ? "Gemma" : "Gemini"}</span>;
}

export function MessageList({ messages, streaming, status }: { messages: Message[]; streaming: string | null; status: string | null }) {
  const end = useRef<HTMLDivElement>(null);
  const t = useT();
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, streaming, status]);
  return (
    <div className="messages" aria-live="polite">
      {messages
        .filter((m) => m.role !== "system_event")
        .map((m) => (
          <div key={m.id} className={`msg ${m.role}`}>
            {m.text && (
              <div className={`bubble ${m.role}`}>
                {m.audioPath && <span className="voice-tag">🎤 </span>}
                {m.text}
              </div>
            )}
            <ModelChip m={m} />
            {m.sources && m.sources.length > 0 && (
              <div className="sources">
                {t("source")}:{" "}
                {m.sources.map((s, i) => (
                  <a key={s.url} href={s.url} target="_blank" rel="noreferrer">
                    {i > 0 ? " · " : ""}↗ {s.title}
                  </a>
                ))}
              </div>
            )}
            {m.card && <CardView card={m.card} messageId={m.id} />}
          </div>
        ))}
      {streaming !== null && (
        <div className="msg assistant">
          <div className="bubble assistant streaming">{streaming || t("thinking")}</div>
        </div>
      )}
      {status && <div className="tool-status">⏳ {status}</div>}
      <div ref={end} />
    </div>
  );
}
