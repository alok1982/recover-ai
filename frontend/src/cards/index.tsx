import type { Card } from "../lib/types";
import { UploadCard } from "./UploadCard";
import { FactsCard } from "./FactsCard";
import { PlanCard } from "./PlanCard";
import { DraftsCard } from "./DraftsCard";
import { ConsentCard } from "./ConsentCard";
import { TimelineCard } from "./TimelineCard";
import { EscalationCard } from "./EscalationCard";
import { WarningCard } from "./WarningCard";
import { CountriesCard } from "./CountriesCard";
import { WithdrawCard } from "./WithdrawCard";
import { HotlineCard } from "./HotlineCard";
import { ProfileCard } from "./ProfileCard";

export function CardView({ card, messageId }: { card: Card; messageId: string }) {
  const p = { data: card.data, messageId };
  switch (card.kind) {
    case "upload": return <UploadCard {...p} />;
    case "facts": return <FactsCard {...p} />;
    case "plan": return <PlanCard {...p} />;
    case "drafts": return <DraftsCard {...p} />;
    case "consent": return <ConsentCard {...p} />;
    case "timeline": return <TimelineCard {...p} />;
    case "escalation": return <EscalationCard {...p} />;
    case "warning": return <WarningCard {...p} />;
    case "countries": return <CountriesCard {...p} />;
    case "withdraw": return <WithdrawCard {...p} />;
    case "hotline": return <HotlineCard {...p} />;
    case "profile": return <ProfileCard {...p} />;
    default: return null;
  }
}

export interface CardProps {
  data: any;
  messageId: string;
}

export function copyText(text: string) {
  navigator.clipboard?.writeText(text);
}

export function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
