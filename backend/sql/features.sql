-- F14 beneficiary transaction features (PRD §10). Parameters: @acct STRING (normalised account key), @now TIMESTAMP (demo clock).
-- Outflow: debits that happen within 60 min after any credit in the window, each debit counted once (the PRD's
-- JOIN form counts a debit once per matching credit), capped at 100 %.
WITH a AS (
  SELECT * FROM `recoverai_analytics.bank_accounts` WHERE account_key = @acct
),
c AS (
  SELECT * FROM `recoverai_analytics.bank_txn`
  WHERE account_key = @acct AND direction = 'CREDIT'
    AND txn_time BETWEEN TIMESTAMP_SUB(@now, INTERVAL 24 HOUR) AND @now
),
d AS (
  SELECT * FROM `recoverai_analytics.bank_txn`
  WHERE account_key = @acct AND direction = 'DEBIT'
    AND txn_time BETWEEN TIMESTAMP_SUB(@now, INTERVAL 24 HOUR) AND @now
),
d60 AS (
  SELECT d.txn_id, d.amount FROM d
  WHERE EXISTS (SELECT 1 FROM c WHERE d.txn_time BETWEEN c.txn_time AND TIMESTAMP_ADD(c.txn_time, INTERVAL 60 MINUTE))
),
f AS (
  SELECT
    (SELECT COUNT(*) FROM a) AS account_found,
    CAST(FLOOR(TIMESTAMP_DIFF(@now, (SELECT opened_at FROM a), SECOND) / 86400) AS INT64) AS account_age_days,
    (SELECT COUNT(*) FROM c) AS credits_24h,
    (SELECT COUNT(DISTINCT counterparty_key) FROM c) AS distinct_senders_24h,
    SAFE_DIVIDE(COALESCE((SELECT SUM(amount) FROM d60), 0), (SELECT SUM(amount) FROM c)) * 100 AS outflow_raw,
    SAFE_DIVIDE((SELECT SUM(amount) FROM c), (SELECT monthly_avg_credit FROM a)) AS credit_ratio_vs_avg,
    (SELECT SUM(amount) FROM c) AS credit_amount_24h,
    (SELECT declared_profile FROM a) AS declared_profile,
    (SELECT current_balance FROM a) AS current_balance,
    (SELECT monthly_avg_credit FROM a) AS monthly_avg_credit,
    (SELECT bank FROM a) AS bank,
    (SELECT holder_name FROM a) AS holder_name,
    (SELECT account_type FROM a) AS account_type,
    (SELECT currency FROM a) AS currency
)
SELECT
  account_found, account_age_days, credits_24h, distinct_senders_24h,
  CASE WHEN outflow_raw IS NULL THEN NULL WHEN outflow_raw > 100 THEN 100 ELSE outflow_raw END AS outflow_60m_pct,
  credit_ratio_vs_avg, credit_amount_24h, declared_profile, current_balance, monthly_avg_credit,
  bank, holder_name, account_type, currency
FROM f
