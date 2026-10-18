import { Link } from "react-router-dom";
import { Logo } from "../ui/Logo";

/** CR-03 B: Terms & Privacy notice linked from signup (purpose limitation under India's DPDP Act 2023 / Malaysia's PDPA). */
export function Privacy() {
  return (
    <main className="landing privacy">
      <Link className="brand small" to="/" aria-label="RecoverAI home"><Logo height={34} /></Link>
      <h2>Terms &amp; Privacy</h2>
      <p><b>Purpose.</b> RecoverAI uses your phone number, name, location and bank only to help you report and recover from
        fraud: preparing complaints, bank letters and evidence packs, and — only when you tap to consent — sharing your case
        with your bank. (Digital Personal Data Protection Act 2023, India; Personal Data Protection Act 2010, Malaysia.)</p>
      <p><b>What we never do.</b> We never ask for money, OTPs or passwords, never sell your data, and never use your
        profile for analytics. Your profile is not sent to any third party except your bank, when you consent.</p>
      <p><b>Your choices.</b> You can edit your profile at any time, withdraw consent from a case, and delete your
        account and cases from the Profile page.</p>
      <p><b>Demo.</b> This deployment is a demonstration using synthetic data in sandbox mode; nothing is sent to real
        banks or police.</p>
      <p className="small">RecoverAI is not legal advice and does not handle money. Official agencies and your bank make all decisions.</p>
    </main>
  );
}
