# Gemini tiering evals

Picks the cheapest Gemini model per task that keeps quality at the bar (P/R ≥ 99%, pass rates ≥ 99%) and
measures tokens. **All data is synthetic** (fictional names, accounts, numbers, URLs). The 99% figures are measured on
this synthetic set only, not on real victims' evidence.

```
cd backend
../.venv/bin/python -m evals.gen_data                     # regenerate data/ (seeded; audio needs `pip install gTTS`)
../.venv/bin/python -m evals.run --task guard --models gemini-3.5-flash-lite,gemini-3.8-flash
../.venv/bin/python -m evals.run --task extraction --models gemini-3.1-flash-lite \
    --env GEMINI_MODEL_INTAKE_ESCALATE=gemini-3.8-flash --tag cascade
../.venv/bin/python -m evals.summarize                    # one line per results/*.json
```

Runs call Vertex AI (project `recoverai-511917`, location `global`) with ADC, in-memory stores, no Firestore / Pub/Sub /
BigQuery writes. Options: `--thinking low|medium|high|<budget>`, `--max-output N`, `--limit N`, `--concurrency N`,
`--env KEY=VALUE` (e.g. a cascade tier), `--tag`.

| task | data | n | metric |
|---|---|---|---|
| guard | `data/guard.jsonl`: recovery-scam offers vs. victims' own messages, en/hi/ms, incl. prompt-injection wrappers | 175 (95 positive) | precision / recall of the production verdict (model OR keyword net) |
| extraction | `data/extraction.jsonl`: 60 rendered receipt images + 60 bank SMS texts, each with a scam chat (8 scam types, IN/MY, en/hi/ms, 1 in 7 with an injected instruction), + 36 gTTS voice notes | 156 items, 1,561 field values | field-level P/R, exact match after normalisation (`metrics.norm_field`) |
| transcribe | the 36 voice notes (en/hi/ms, 6 with spoken injections) | 36 | pass = amount kept (words or same value in digits) and WER ≤ 0.15 on the rest |
| drafts | 4 staged cases × 10 fact variants × the plan's templates (+ RBI Ombudsman for IN) | 120 | F5: every required value (reference, amount, date, receiver, account) in both en and local, after ≤ 1 regeneration (production); local text in the right language |
| plan_explain | 4 staged cases × 25 fact variants | 100 | non-empty, post-check clean (no unverified number/date), case language, first step's contact present |
| bank_reason | 120 synthetic payload + transaction-feature sets through the real rules (`bank.rules.recommend`) | 120 | grounded: every fired signal named, no unfired signal code, no number absent from the input, action consistent |
| copilot | 12 turn types × IN-hi / IN-en / MY-ms / MY-en × 2, on cases staged with the offline agents (evidence → follow-up), incl. an injection turn | 96 | correct card(s) shown / not shown, non-empty reply, post-check clean on first try, case language, injection resisted |
| fallback | reply_fallback (empty-reply writer) and post_check_regen on staged cases | 48 + 48 | non-empty, case language, (regen) no unverified value left |

Token usage comes from a spy on `google.genai` `generate_content[_stream]` (prompt, candidates and thinking tokens per
raw call, ADK calls included); `$` uses Vertex AI global standard prices (Oct 2026), output including thinking.
`results/summary.md` has the chosen tiers and the numbers behind them.
