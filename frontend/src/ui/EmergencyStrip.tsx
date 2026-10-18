import type { Country } from "../lib/types";
import { useT } from "../i18n";

/** CR-03 A: the national hotline is never behind a login. Tap-to-call. */
export function EmergencyStrip({ countries = ["IN", "MY"] as Country[] }: { countries?: Country[] }) {
  const t = useT();
  return (
    <section className="emergency" aria-label={t("emergencyTitle")} data-testid="emergency-strip">
      <b className="emergency-title">🚨 {t("emergencyTitle")}</b>
      <div className="emergency-row">
        {countries.includes("IN") && (
          <span className="hotline-group">
            <a className="hotline" href="tel:1930" data-testid="hotline-IN">
              <span className="flag">🇮🇳</span> <span>{t("hotlineIN").split(" · ")[0]}</span>
            </a>
            <a className="small hotline-web" href="https://cybercrime.gov.in" target="_blank" rel="noreferrer">cybercrime.gov.in</a>
          </span>
        )}
        {countries.includes("MY") && (
          <a className="hotline" href="tel:997" data-testid="hotline-MY">
            <span className="flag">🇲🇾</span> <span>{t("hotlineMY")}</span>
          </a>
        )}
      </div>
      <p className="small muted">{t("hotlineNote")}</p>
    </section>
  );
}
