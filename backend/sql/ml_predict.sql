-- S2: score one beneficiary. Parameters: the five features from features.sql.
SELECT p.prob AS mule_probability
FROM ML.PREDICT(MODEL `recoverai_analytics.mule_risk_model`, (
  SELECT @account_age_days AS account_age_days, @credits_24h AS credits_24h, @distinct_senders_24h AS distinct_senders_24h,
         @outflow_60m_pct AS outflow_60m_pct, @credit_ratio_vs_avg AS credit_ratio_vs_avg
)), UNNEST(predicted_is_mule_probs) AS p
WHERE p.label = TRUE
