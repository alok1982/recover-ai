import { useCallback, useMemo, useState } from "react";
import { streamChat, type SseEvent } from "../lib/api";
import type { CaseDoc, Message } from "../lib/types";
import { useT } from "../i18n";
import { CopilotContext, type CopilotCtx } from "./context";
import { InputBar } from "./InputBar";
import { MessageList } from "./MessageList";

interface Props {
  caseId: string;
  caseDoc: CaseDoc | null;
  messages: Message[];
  addLocal: (m: Message[]) => void;
  setCase: (c: CaseDoc) => void;
  refresh: () => Promise<void>;
  children?: React.ReactNode;
}

export function useCopilotController({ caseId, caseDoc, messages, addLocal, setCase, refresh }: Props) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const run = useCallback(
    async (body: Record<string, unknown>) => {
      setBusy(true);
      setStreaming("");
      let acc = "";
      try {
        await streamChat(caseId, body, (e: SseEvent) => {
          switch (e.type) {
            case "user_message":
            case "card":
            case "message":
              if (e.message) addLocal([e.message]);
              break;
            case "transcript":
              break;
            case "tool_status":
              setStatus(e.state === "running" ? e.label || `${e.name}…` : null);
              break;
            case "token":
              acc += e.text;
              setStreaming(acc);
              break;
            case "replace":
              acc = e.text;
              setStreaming(acc);
              break;
            case "done":
              if (e.message) addLocal([e.message]);
              acc = "";
              setStreaming("");
              break;
            case "error":
              addLocal([{ id: `err-${Date.now()}`, role: "assistant", text: t("retry"), card: null, seq: Date.now() * 1e6 }]);
              break;
          }
        });
      } catch (err: any) {
        addLocal([{ id: `err-${Date.now()}`, role: "assistant", text: err?.message || t("retry"), card: null, seq: Date.now() * 1e6 }]);
      } finally {
        setStreaming(null);
        setStatus(null);
        setBusy(false);
        refresh();
      }
    },
    [caseId, addLocal, refresh, t],
  );

  const ctx: CopilotCtx = useMemo(
    () => ({
      caseId,
      caseDoc,
      busy,
      send: (text: string) => run({ text }),
      trigger: (name: string, extra = {}) => run({ trigger: name, ...extra }),
      sendVoice: (audioPath: string) => run({ audioPath }),
      apply: (resp) => {
        if (resp.case) setCase(resp.case);
        if (resp.messages?.length) addLocal(resp.messages);
      },
      latestCardId: (kind: string) => [...messages].reverse().find((m) => m.card?.kind === kind)?.id,
    }),
    [caseId, caseDoc, busy, run, setCase, addLocal, messages],
  );
  return { ctx, streaming, status };
}

export function Chat(props: Props) {
  const { ctx, streaming, status } = useCopilotController(props);
  return (
    <CopilotContext.Provider value={ctx}>
      <section className="chat">
        <MessageList messages={props.messages} streaming={streaming} status={status} />
        <InputBar />
      </section>
      {props.children}
    </CopilotContext.Provider>
  );
}
