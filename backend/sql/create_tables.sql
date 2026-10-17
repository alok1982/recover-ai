-- RecoverAI analytics dataset (PRD §7, F14). Run with: bq query --use_legacy_sql=false < backend/sql/create_tables.sql
-- The dataset itself is created by deploy/deploy.sh (bq mk --location=$REGION recoverai_analytics).
-- bank_accounts adds holder_name/account_type/currency/current_balance to the PRD columns: the dashboard's account
-- panel shows them and the hold limit is min(case amount, current_balance) (§10).

CREATE TABLE IF NOT EXISTS `recoverai_analytics.bank_accounts` (
  account_key STRING NOT NULL OPTIONS(description = "normalised VPA / account number (join key)"),
  country STRING, bank STRING, opened_at TIMESTAMP, declared_profile STRING,
  monthly_avg_credit NUMERIC, is_mule BOOL OPTIONS(description = "synthetic label (S2 training only)"),
  holder_name STRING, account_type STRING, currency STRING, current_balance NUMERIC
);

CREATE TABLE IF NOT EXISTS `recoverai_analytics.bank_txn` (
  txn_id STRING NOT NULL, account_key STRING NOT NULL, direction STRING OPTIONS(description = "CREDIT | DEBIT"),
  amount NUMERIC, currency STRING, counterparty_key STRING, txn_time TIMESTAMP
)
PARTITION BY DATE(txn_time)
CLUSTER BY account_key;

CREATE TABLE IF NOT EXISTS `recoverai_analytics.case_events` (
  event_id STRING NOT NULL, case_id STRING, event_type STRING OPTIONS(description = "case_confirmed | bank_decision"),
  country STRING, scam_type STRING, amount NUMERIC, currency STRING,
  beneficiary_hash STRING OPTIONS(description = "SHA-256 of the normalised beneficiary account; never the raw value"),
  risk_level STRING, decision STRING, event_time TIMESTAMP
)
PARTITION BY DATE(event_time);
