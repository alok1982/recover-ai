-- S2: score one beneficiary. Parameters: the five features from features.sql.
SELECT p.prob AS mule_probability
FROM ML.PREDICT(MODEL `recoverai_analytics.mule_risk_model`, (
  SELECT CAST(@account_age_days AS INT64) AS account_age_days, CAST(@credits_24h AS INT64) AS credits_24h,
         CAST(@distinct_senders_24h AS INT64) AS distinct_senders_24h,
         CAST(@outflow_60m_pct AS FLOAT64) AS outflow_60m_pct, CAST(@credit_ratio_vs_avg AS FLOAT64) AS credit_ratio_vs_avg
)), UNNEST(predicted_is_mule_probs) AS p
WHERE p.label = TRUE
