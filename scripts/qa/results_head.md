# RecoverAI — QA results, 18 Oct 2026 (live build)

- **Target:** https://recoverai-511917.web.app (Firebase Hosting) → Cloud Run `recoverai-api`, revision `recoverai-api-00016-kll` (100 % traffic), asia-south1
- **Code under test:** `main` @ `f696e70`
- **Plan:** `docs/qa/test-plan-v2.5-amended.md` (the original v2.5 plan + section K and the added rows)
- **When:** 18 Oct 2026, about 16:00–17:15 IST
- **Who / how:** Grok Bot QA pass. Automation is in `scripts/qa/` plus the existing suites. Screenshots are in `docs/screenshots/qa/`; eval results in `backend/evals/results/*qa-1018*.json`
- **Legend:** ✅ pass · ❌ fail · ⚠️ passes with a caveat, or differs from the plan wording · ⏭ skipped / not built / not run on live by decision · manual = needs a human or a real device

## Verdict: **NO-GO as it stands → GO once BUG-01 and BUG-03 are fixed** (both are small)

| Gate | Rule | Result |
|---|---|---|
| Security | F5, I6, the probe's P0 checks and A4 all pass | ✅ F5 20/20, I6 clean, all probe P0 checks pass (IDOR, rules, roles, sandbox lock, health), A4 ✅. ⚠️ P1 **BUG-03** (Hosting caches API 404s) is a correctness / DoS risk, not a data leak |
| Safety | E3, E5, E9, E10, B4 pass | ✅ all five |
| Correctness | C3, C4, C6, D1, D5, F2 pass | ❌ **D5**: day-31 escalation card has `bankComplaintDate: null` (BUG-01); the 5-day RBI clock never turns amber (advisory 'recommended'). C3, C4, C6, D1, F2 ✅ |
| Demo path | India story end-to-end 3× on the deployed URL, no manual fix | ✅ `e2e_demo.py` 3/3 "E2E OK" (withdraw 0.9–1.2 s) + cr03 17/17 + cr04 27/27 |
| Fallbacks | Non-core breakage hidden by a flag | ✅ Gemma off (`chatLight:null`); voice works (H1/H3/K13). Nothing needed hiding |

**Fix before submitting:** BUG-01 (D5 complaint date) and BUG-03 (`/api/**` cache headers on Hosting). Fix BUG-02 (double submission)
too if there is time: the sandbox makes it harmless for the demo, but it breaks the CR-01 "only one active submission" rule.

Pre-existing suites (all green): backend pytest (all pass, 1 skipped) · Firestore rules emulator 13/13 · `ui_smoke.py` on the mock stack ·
`e2e_demo.py` live ×3 · `cr03_acceptance.py` 17/17 · `cr04_roles_check.py` 27/27 · `voice_check.py` (Chrome, Pixel, mic blocked) ·
Lighthouse mobile A11y 94 / Perf 96.
