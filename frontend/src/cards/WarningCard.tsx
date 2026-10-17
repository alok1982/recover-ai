import { useState } from "react";
import { useT } from "../i18n";
import type { CardProps } from ".";

export function WarningCard({ data }: CardProps) {
  const t = useT();
  const [why, setWhy] = useState(false);
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;
  return (
    <div className="card warning-card" role="alert">
      <h3>🚫 {t("warningTitle")}</h3>
      <p className="warn-msg">{data.message}</p>
      {data.followUp && <p>{data.followUp}</p>}
      <button className="link light" onClick={() => setWhy(!why)}>{t("whyNoPay")}</button>
      {why && <p>{t("whyNoPayText")}</p>}
      <button className="btn small" onClick={() => setHidden(true)}>{t("dismiss")}</button>
    </div>
  );
}
