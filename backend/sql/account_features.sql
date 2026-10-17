-- S2 feature view: the five F14 features for every account at @now, plus the synthetic label. Parameter: @now TIMESTAMP.
-- Same definitions as features.sql, computed for all accounts at once.
CREATE OR REPLACE TABLE `recoverai_analytics.account_features` AS
WITH c AS (
  SELECT * FROM `recoverai_analytics.bank_txn`
  WHERE direction = 'CREDIT' AND txn_time BETWEEN TIMESTAMP_SUB(@now, INTERVAL 24 HOUR) AND @now
),
d AS (
  SELECT * FROM `recoverai_analytics.bank_txn`
  WHERE direction = 'DEBIT' AND txn_time BETWEEN TIMESTAMP_SUB(@now, INTERVAL 24 HOUR) AND @now
),
d60 AS (
  SELECT d.account_key, d.txn_id, d.amount FROM d
  WHERE EXISTS (SELECT 1 FROM c WHERE c.account_key = d.account_key
                AND d.txn_time BETWEEN c.txn_time AND TIMESTAMP_ADD(c.txn_time, INTERVAL 60 MINUTE))
),
cs AS (SELECT account_key, COUNT(*) AS credits_24h, COUNT(DISTINCT counterparty_key) AS distinct_senders_24h,
              SUM(amount) AS credit_amount FROM c GROUP BY account_key),
ds AS (SELECT account_key, SUM(amount) AS out_amount FROM d60 GROUP BY account_key)
SELECT
  a.account_key,
  CAST(FLOOR(TIMESTAMP_DIFF(@now, a.opened_at, SECOND) / 86400) AS INT64) AS account_age_days,
  COALESCE(cs.credits_24h, 0) AS credits_24h,
  COALESCE(cs.distinct_senders_24h, 0) AS distinct_senders_24h,
  -- FLOAT64 (amounts are NUMERIC): ML.PREDICT will not coerce FLOAT64 query parameters to a NUMERIC training column.
  CAST(COALESCE(CASE WHEN SAFE_DIVIDE(ds.out_amount, cs.credit_amount) * 100 > 100 THEN 100
                ELSE SAFE_DIVIDE(ds.out_amount, cs.credit_amount) * 100 END, 0) AS FLOAT64) AS outflow_60m_pct,
  CAST(COALESCE(SAFE_DIVIDE(cs.credit_amount, a.monthly_avg_credit), 0) AS FLOAT64) AS credit_ratio_vs_avg,
  a.is_mule
FROM `recoverai_analytics.bank_accounts` a
LEFT JOIN cs USING (account_key)
LEFT JOIN ds USING (account_key)
