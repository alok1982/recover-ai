import { useT } from "../i18n";

export function Disclaimer() {
  const t = useT();
  return <footer className="disclaimer">{t("disclaimer")}</footer>;
}
