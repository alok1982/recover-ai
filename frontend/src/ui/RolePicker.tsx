import { useT } from "../i18n";

export type Role = "victim" | "bank";

/** CR-04: "I've been scammed" (default) or "I work at a bank (fraud team)". */
export function RolePicker({ role, setRole }: { role: Role; setRole: (r: Role) => void }) {
  const t = useT();
  return (
    <div className="role-picker" role="radiogroup" aria-label={t("roleTitle")} data-testid="role-picker">
      <button type="button" role="radio" aria-checked={role === "victim"} className={role === "victim" ? "on" : ""}
        onClick={() => setRole("victim")} data-testid="role-victim">🆘 {t("roleVictim")}</button>
      <button type="button" role="radio" aria-checked={role === "bank"} className={role === "bank" ? "on" : ""}
        onClick={() => setRole("bank")} data-testid="role-bank">🏦 {t("roleBank")}</button>
    </div>
  );
}
