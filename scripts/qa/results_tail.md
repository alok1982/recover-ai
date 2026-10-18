## Bug reports (P0 / P1 first)

```
BUG-01  Escalation card has no bank complaint date (bankComplaintDate: null)
Test case: D5            Severity: P0 (plan Correctness gate)      Build: recoverai-api-00016-kll
Environment: API (scripts/qa/deadline_checks.py), throw-away IN-complete user
Steps: India story case → PATCH /steps/report_bank {status: done, reference: QA-BANK-CMP-42} → POST /clock addDays 5 → … day 31
Expected (PRD F7): day-31 escalation card + RBI Ombudsman draft citing the bank complaint date and a reference
Actual: the card and draft are created once (no duplicate on refresh ✅) and carry the user reference QA-BANK-CMP-42 ✅, but
        escalation.bankComplaintDate = null (actions.py:178 format_dt(bank_step.doneAt)). Also at +5 days the
        dual_report_5d clock stays "recommended" and never turns amber/red (by design it is advisory; the plan expects amber).
Evidence: /workspace/qa_logs/deadline.json; code: actions.py:160-182, agents/filing.py:308-316, rules/engine.py mark_step
Note: root cause not yet confirmed. mark_step does set doneAt. Check whether a re-plan or the time-travel path drops doneAt
      before the escalation fires. Decide whether the 5-day clock should show amber.
```

```
BUG-02  Parallel "Confirm & send" creates several bank cases for one victim case
Test case: E8 / E13      Severity: P1      Build: recoverai-api-00016-kll
Steps: preview → 3 parallel POST /send-to-bank with the same confirmationToken + 1 replay
Expected (CR-01 §2): exactly one bank case; the others get 409
Actual: HTTP [200, 200, 200, 409] → 3 bank cases (earlier runs: 2 and 2). Pub/Sub replay of one message is de-duplicated (F6 ✅);
        the race is before publish (the token / status check is not transactional).
Fix: claim the submission in a Firestore transaction (bankStatus NONE → SENDING) or create_bank_case_if_absent keyed by caseId only.
Evidence: probe.json E8; /workspace/qa_logs/probe_bank_cases.txt
```

```
BUG-03  Firebase Hosting caches /api error responses (max-age=600) → a user can get someone else's cached 404
Test case: I8 (new)      Severity: P1      Build: Hosting current + recoverai-api-00016-kll
Steps: user B GET /api/cases/{A's id}/messages via web.app (404) → user A GET of the same URL with A's token
Expected: A gets 200 (API responses never shared-cached)
Actual: A gets 404 with x-cache: HIT, cache-control: max-age=600 for up to 10 min. Unauthenticated GETs are also served from the cache.
        No data leaks (a 404 is cached, not a 200), but it is a cross-user denial of service and it explains the "case not found" flakes.
Fix: Cache-Control: private, no-store on every FastAPI response (middleware) and/or a firebase.json header rule for /api/**.
Evidence: probe.json K-CACHE; /workspace/qa_logs/cache_test.py
```

```
BUG-04  Upload accepts a disguised .exe and 0-byte files
Test case: C5 / C5a      Severity: P1
Actual: an MZ (.exe) payload declared image/png → 200; a 0-byte image → 200 (Gemini then rejects it and intake silently falls back).
Expected: magic-byte check (PNG/JPEG/WebP/PDF) and size > 0 at registration → 415 / 400.
Evidence: probe.json C5
```

```
BUG-05  Co-pilot eval below the 99 % gate on the deployed Flash-Lite tier
Test case: K18 (new)     Severity: P1
Actual: copilot eval (96 items, gemini-3.5-flash-lite) all_checks_pass 96.9 %. The 3 failures (cp_08_IN_hi_1, cp_08_MY_ms_0/1):
        "When is my deadline?" in Hindi / Malay is answered in text without calling show_timeline; once the model writes
        "[showed timeline card]" as text. Guard 100/100 and extraction 99.81/99.68 pass.
Fix: tighten the tool rule for deadline questions in hi/ms, or a deterministic intent → timeline card.
Evidence: backend/evals/results/copilot__gemini-3.5-flash-lite__qa-1018.json
```

```
BUG-06  Phone validation lets an invalid 9-digit number through under +91
Test case: A10           Severity: P2 (plan) — listed here because it creates bad accounts
Actual: a Malaysian 9-digit national number with +91 selected → account +91 100000001 created (deleted again by the suite).
Fix: toE164 must require isValidPhoneNumber() for the selected country, not just isPossible.
```

```
BUG-07  First token is slower than 2 s
Test case: C1   Severity: P1   Actual: 3.2–3.5 s to the first token (8 chunks, total ~3.5 s). The reply is complete, but it is not "fast".
```

```
BUG-08  Profile card does not pre-fill what the user just typed
Test case: B5   Severity: P1   Actual: after "my bank is SBI, PIN 411001" the profile card shows prefill {} (missing postalCode, primaryBank).
                Saving only on Save is correct.
```

Lower priority: **BUG-09** (I3, P2) X-Content-Type-Options and CSP missing on / and /api ·
**BUG-10** (A12, P2) Firebase TOO_MANY_ATTEMPTS is shown as "incorrect password" ·
**BUG-11** (C14, P2) the same card emitted twice in one turn (consent, warning). ⚠️ items: A2 (both hotlines on '/'),
B1 (meter shows a percent only), E4 (evidence count + SHA-256 instead of thumbnails).

## Not run / manual, and why
| ID | Why |
|---|---|
| H2 | Needs a real Android + iPhone (Pixel emulation passed) |
| H5 | Needs a real WhatsApp in-app browser (emulated user agent passed) |
| J3 | 15-minute idle cold start on live: not run under time pressure |
| J4 | Slow-3G by hand |
| D6, J5 | Need a tagged `--no-traffic` test revision, which pins service traffic. Not risked on submission day. D6 is covered by the unit test |
| A15, C13 | Not built / off by design (OTP sign-up; Gemma light model) |

## Cleanup (done)
- Throw-away accounts +91 90000 011xx: every Firebase login and Firestore user doc deleted. One user doc was left behind by A12
  (sign-in was throttled, so self-delete could not run); it was removed via the admin API. The A10 accident account is gone too.
- QA bank-case copies of deleted throw-away cases (19, created ≥ 16:06 IST) deleted. Bank copies that existed before this pass
  were left alone.
- Seed 00002 reset to its seeded incomplete profile (postalCode, primaryBank empty). The user's own account was not touched.
- DLQ (`dlq-inspect`) empty; no orphaned evidence prefixes in the bucket; no tagged / no-traffic revisions were created.
- Not cleaned (outside QA scope, flagged): 9 victim cases from before this pass whose owner user doc no longer exists
  (created 10:10–12:22 IST), the bank-case copies from before this pass, and the QA case_events rows in BigQuery (append-only, sandbox=TRUE, excluded from analytics).

## Test-tooling change
`backend/evals/common.py`: the eval harness now uses a profiled in-memory store, so mock eval users have a complete profile and are not stopped by the
CR-03 profile gate (412). Only eval tooling changed; production code is untouched.
