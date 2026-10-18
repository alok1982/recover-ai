import { useT } from "../i18n";
import type { CardProps } from ".";

/** CR-03 C: the urgent national hotline step, shown before the profile card when the loss is recent. */
export function HotlineCard({ data }: CardProps) {
  const t = useT();
  return (
    <div className="card hotline-card emergency" data-testid="hotline-card">
      <b className="emergency-title">🚨 {data.title}</b>
      <div className="emergency-row">
        <a className="hotline" href={`tel:${data.number}`}>📞 {data.country === "MY" ? t("hotlineMY") : t("hotlineIN").split(" · ")[0]}</a>
        {data.web && <a className="small hotline-web" href={data.web} target="_blank" rel="noreferrer">{data.web.replace(/^https?:\/\//, "")}</a>}
      </div>
      <p className="small">{data.body}</p>
    </div>
  );
}
