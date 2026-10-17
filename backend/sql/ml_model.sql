-- S2 (stretch): BigQuery ML mule-risk model on synthetic data — advisory only; the §10 rules decide the action.
-- Run after account_features.sql. BigQuery ML standardises numeric inputs; TRANSFORM log-scales the skewed ones.
CREATE OR REPLACE MODEL `recoverai_analytics.mule_risk_model`
TRANSFORM(
  LN(1 + account_age_days) AS log_age_days,
  credits_24h,
  distinct_senders_24h,
  outflow_60m_pct,
  LN(1 + credit_ratio_vs_avg) AS log_credit_ratio,
  is_mule
)
OPTIONS(model_type = 'logistic_reg', input_label_cols = ['is_mule'], l2_reg = 0.1, data_split_method = 'NO_SPLIT') AS
SELECT account_age_days, credits_24h, distinct_senders_24h, outflow_60m_pct, credit_ratio_vs_avg, is_mule
FROM `recoverai_analytics.account_features`;
