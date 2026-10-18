export type Lang = "en" | "hi" | "ms";
export type Country = "IN" | "MY";

export interface Card {
  kind: "upload" | "facts" | "plan" | "drafts" | "consent" | "timeline" | "escalation" | "warning" | "countries";
  data: any;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system_event";
  text: string | null;
  card: Card | null;
  audioPath?: string | null;
  lang?: Lang;
  createdAt?: string;
  seq?: number;
  toolCalls?: { name: string; ok: boolean; latencyMs: number }[];
  pending?: boolean;
  sources?: { title: string; url: string; publisher?: string | null }[];
}

export interface Step {
  id: string;
  title: string;
  titleLocal?: string | null;
  channel: string;
  contact?: string | null;
  urgency: "now" | "today" | "within_days";
  why?: string;
  deadline?: string | null;
  deadlineDisplay?: string | null;
  template_id: string;
  status: "pending" | "done";
  user_reference?: string | null;
  doneAt?: string | null;
}

export interface Clock {
  id: string;
  label: string;
  labelLocal?: string | null;
  dueAt: string;
  dueDisplay: string;
  status: "pending" | "done" | "overdue" | "recommended";
  inForce: boolean;
  note?: string | null;
  noteLocal?: string | null;
  urgencyOnly?: boolean;
  escalationTemplate?: string | null;
  escalationNotifiedAt?: string | null;
  contact?: string | null;
  appliesToSteps?: string[];
}

export interface CaseDoc {
  id: string;
  ownerUid: string;
  country: Country;
  language: Lang;
  status: string;
  bankStatus: string;
  clocks: Clock[];
  createdAt: string;
  incidentAt?: string | null;
  clockOffsetDays?: number;
  extraction?: any;
  plan?: { steps: Step[]; playbook_version: string; last_verified?: string; sources?: string[] } | null;
  explanation?: { lang: Lang; text: string } | null;
  drafts?: Record<string, any>;
  evidencePackPath?: string | null;
  evidenceCount?: number;
  bankCaseId?: string | null;
  escalation?: any;
  flags?: { recovery_scam_detected: boolean };
  demoMode?: boolean;
}
