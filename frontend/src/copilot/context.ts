import { createContext, useContext } from "react";
import type { CaseDoc, Message } from "../lib/types";

export interface CopilotCtx {
  caseId: string;
  caseDoc: CaseDoc | null;
  busy: boolean;
  /** Send a free-text chat turn (streams the co-pilot reply). */
  send: (text: string) => Promise<void>;
  /** Directed turn after a card action: evidence_added | facts_confirmed | generate_all. */
  trigger: (name: string, extra?: Record<string, unknown>) => Promise<void>;
  sendVoice: (audioPath: string) => Promise<void>;
  /** Merge a REST response ({case?, messages?}) into the live view. */
  apply: (resp: { case?: CaseDoc; messages?: Message[] }) => void;
  latestCardId: (kind: string) => string | undefined;
}

export const CopilotContext = createContext<CopilotCtx | null>(null);

export function useCopilot(): CopilotCtx {
  const c = useContext(CopilotContext);
  if (!c) throw new Error("CopilotContext missing");
  return c;
}
