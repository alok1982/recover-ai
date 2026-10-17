import { useEffect, useState } from "react";
import { useCopilot } from "../copilot/context";
import { countdown, effectiveNow } from "../lib/live";
import { useT } from "../i18n";
import type { Clock } from "../lib/types";
import type { CardProps } from ".";

export function ClockList({ clocks }: { clocks: Clock[] }) {
  const { caseDoc } = useCopilot();
  const t = useT();
  const [, tick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => tick((x) => x + 1), 30000);
    return () => window.clearInterval(id);
  }, []);
  const now = effectiveNow(caseDoc);
  return (
    <ul className="clock-list">
      {clocks.map((c) => (
        <li key={c.id} className={`clock ${c.status}`}>
          <div>{c.labelLocal || c.label}</div>
          <div className="row wrap">
            <span className="chip deadline">⏰ {c.dueDisplay}</span>
            {c.status !== "done" && <span className="chip">{countdown(c.dueAt, now, t("overdue"))}</span>}
            <span className={`chip st-${c.status}`}>{t(c.status)}</span>
          </div>
          {(c.noteLocal || c.note) && <div className="note">ℹ️ {c.noteLocal || c.note}</div>}
        </li>
      ))}
    </ul>
  );
}

export function TimelineCard({ data }: CardProps) {
  const { caseDoc } = useCopilot();
  const t = useT();
  const clocks: Clock[] = caseDoc?.clocks || data.clocks || [];
  const bank = caseDoc?.bankStatus || data.bankStatus;
  return (
    <div className="card timeline-card">
      <h3>⏱ {t("timelineTitle")}</h3>
      <ClockList clocks={clocks} />
      <p><b>{t("bankStatus")}:</b> <span className={`pill bank-${bank}`}>{t(`bank.${bank}`)}</span></p>
    </div>
  );
}
