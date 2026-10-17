-- F14 [SHOULD] Scam intelligence panels. Parameter: @now TIMESTAMP. Sections are split on "-- name:" markers.

-- name: by_scam_type
SELECT scam_type, COUNT(DISTINCT case_id) AS cases
FROM `recoverai_analytics.case_events`
WHERE event_time BETWEEN TIMESTAMP_SUB(@now, INTERVAL 30 DAY) AND @now
GROUP BY scam_type
ORDER BY cases DESC, scam_type;

-- name: repeat_beneficiaries
SELECT beneficiary_hash, COUNT(DISTINCT case_id) AS cases, STRING_AGG(DISTINCT country, ',' ORDER BY country) AS countries,
       MIN(event_time) AS first_seen, MAX(event_time) AS last_seen
FROM `recoverai_analytics.case_events`
WHERE beneficiary_hash IS NOT NULL
GROUP BY beneficiary_hash
HAVING COUNT(DISTINCT case_id) >= 2
ORDER BY cases DESC, last_seen DESC
LIMIT 20;

-- name: by_country_day
SELECT country, DATE(event_time) AS day, COUNT(DISTINCT case_id) AS cases, SUM(amount) AS amount, ANY_VALUE(currency) AS currency
FROM `recoverai_analytics.case_events`
WHERE event_type = 'case_confirmed' AND event_time BETWEEN TIMESTAMP_SUB(@now, INTERVAL 30 DAY) AND @now
GROUP BY country, day
ORDER BY day, country;
