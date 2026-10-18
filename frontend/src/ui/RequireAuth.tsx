import { Navigate, useLocation } from "react-router-dom";
import { useVictim } from "../lib/auth";

/** CR-03 B: /cases, /cases/:id and /profile need a signed-in phone account → /login?next=… */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const me = useVictim();
  const loc = useLocation();
  if (me === undefined) return <div className="loading">…</div>;
  if (!me) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  return <>{children}</>;
}
