import { useEffect, useRef } from "react";
import type { Message } from "../lib/types";
import { CardView } from "../cards";
import { useT } from "../i18n";

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
