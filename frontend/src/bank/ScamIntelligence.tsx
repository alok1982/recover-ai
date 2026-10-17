import { useEffect, useState } from "react";
import { api } from "../lib/api";

/** Stretch S2 (BigQuery). The backend returns 501 until BIGQUERY_ENABLED=true. */
export function ScamIntelligence() {
  const [data, setData] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    api.bankGet<any>("/api/bank/analytics").then(setData).catch((e) => setMsg(e.message));
  }, []);
  return (
    <main className="bank-main">
      <h2>Scam intelligence</h2>
      {msg && <p className="muted">{msg}</p>}
      {data && <pre>{JSON.stringify(data, null, 2)}</pre>}
    </main>
  );
}
