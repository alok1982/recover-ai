import { COMING_SOON, useT } from "../i18n";
import type { CardProps } from ".";

export function CountriesList() {
  return (
    <ul className="countries">
      {COMING_SOON.map((c) => (
        <li key={c.code}><b>{c.name}</b> — {c.text}</li>
      ))}
    </ul>
  );
}

export function CountriesCard(_props: CardProps) {
  const t = useT();
  return (
    <div className="card countries-card">
      <h3>🌏 {t("countriesTitle")}</h3>
      <CountriesList />
    </div>
  );
}
