import { useEffect, useState } from "react";
import { useCopilot } from "../copilot/context";
import { getMe, type Me } from "../lib/me";
import { useT } from "../i18n";
import { ProfileForm } from "../profile/ProfileForm";
import type { CardProps } from ".";

/** CR-03 C: only the missing profile fields, pre-filled from the chat. The victim taps Save (PUT /api/me/profile);
 *  the co-pilot then continues (usually with the evidence step). */
export function ProfileCard({ data, messageId }: CardProps) {
  const t = useT();
  const { trigger, latestCardId } = useCopilot();
  const [me, setMe] = useState<Me | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { getMe().then(setMe).catch(() => setMe(null)); }, []);
  const missing: string[] = me ? me.profileStatus.missing : data.missing || [];
  const superseded = latestCardId("profile") !== messageId && !messageId.startsWith("local-");
  if (saved || (me && me.profileStatus.complete)) {
    return <div className="card profile-card done" data-testid="profile-card">✓ {t("saved")}</div>;
  }
  return (
    <div className="card profile-card" data-testid="profile-card">
      <h3>{t("profileCardTitle")}</h3>
      <p className="small muted">{t("profileCardHint")}</p>
      {superseded ? <p className="small muted">↓</p> : me ? (
        <ProfileForm me={me} fields={missing as any} prefill={data.prefill} compact
          onSaved={(m) => { setMe(m); if (m.profileStatus.complete) { setSaved(true); trigger("profile_saved"); } }} />
      ) : <p className="small">…</p>}
    </div>
  );
}
