# Gemini tiering — results (18 Oct 2026, Vertex AI `global`, project recoverai-511917)

Synthetic data only (see ../README.md). The 99% bar is measured on this synthetic set, not on real cases.
Candidates found at `global`: gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-3.8-flash (old default),
gemini-3.5-flash, gemini-3.1-pro-preview. Pro was not needed: a Lite tier met the bar on every task.
Tokens = average per call/turn; output includes thinking. $ = Vertex AI global standard prices (Flash 3.8 $0.75/$3.75,
3.5 Flash-Lite $0.30/$2.50, 3.1 Flash-Lite $0.25/$1.50 per 1M in/out).

| task | old | new | quality (new) | n | tokens old → new (in / out+think) | $ per call old → new |
|---|---|---|---|---|---|---|
| guard | 3.5 Flash-Lite, full prompt | 3.5 Flash-Lite, trimmed prompt (no unused F17 route label), max_output 256; 429 → 3.1 Flash-Lite | P 100% / R 100% (2 runs; same as old) | 175 ×2 (95 positive) | 521/58 → 400/30 | 0.000301 → 0.000196 |
| intake (extraction) | 3.8 Flash | cascade 3.1 Flash-Lite → 3.8 Flash on schema/call failure or a missing / <0.7-confidence key field | field P 99.94% / R 99.87% (old Flash 100% / 99.23%, 1 failed call) | 156 items, 1,561 fields | 1,882/1,326 → 1,898/728 | 0.00639 → 0.00244 |
| transcribe | 3.8 Flash | 3.1 Flash-Lite | pass 100% (v4), 97.2% (v3: dropped a spoken injection sentence), 100% (v2) → 107/108 = 99.1% pooled; old Flash 94.4% | 36 per run (below 100) | 455/323 → 455/51 | 0.00156 → 0.00019 |
| plan_explain | 3.8 Flash | 3.5 Flash-Lite, max_output 1024 | pass 100% (post-check, language, first step) | 100 | 417/1,614 → 417/136 | 0.00636 → 0.00047 |
| drafts | 3.8 Flash | 3.1 Flash-Lite + prompt lists the required values, facts trimmed per template, max_output 4096 | F5 required values 100% after ≤1 regen (first try 98.3%); local language 99.2% (old Flash: 100% / 99.2%) | 120 | 738/2,295 → 708/652 | 0.00916 → 0.00158 |
| bank_reason | 3.8 Flash | 3.5 Flash-Lite, max_output 512 | grounded 100% (old Flash 99.2%) | 120 | 496/1,111 → 501/102 | 0.00454 → 0.00041 |
| copilot (ADK turn) | 3.8 Flash, 30-msg history | 3.5 Flash-Lite, 12-msg history (replies >400 chars truncated), max_output 1024 | 3 runs, 288 turns: tool/card 99.65%, non-empty 100%, language 100%, injection resisted 100%, post-check clean first try 99.65% (100% after the gate) | 96 ×3 | 2,902/635 → 2,913/66 per turn | 0.00456 → 0.00104 |
| reply_fallback, post_check_regen | 3.8 Flash | 3.5 Flash-Lite, max_output 512 | 100% / 100% | 48 + 48 | 480/630 → 480/33 | 0.00272 → 0.00023 |

Other runs (not chosen): guard on 3.8 Flash R 87.4%; guard 3.1 Flash-Lite trimmed P 98.96%; extraction 3.5 Flash-Lite
98.98/98.98 (cascade 98.85: its misses were scam_type / time, not escalation triggers); drafts 3.5 Flash-Lite local
language 92.5%; copilot 3.1 Flash-Lite tool 92.7%; copilot 3.8 Flash thinking=low 100% at $0.0024 (cheaper Flash option).
A post-check false positive was fixed on the way: the case publicRef (RAI-IN-20261018-1234) was not an allowed value, so
13% of old Flash turns paid for a regeneration call.

Per full demo case (5 guard, 1 intake, 1 voice note, 1 plan, 3 drafts, 1 bank reason, 9 co-pilot turns, regens):
**~52,800 → ~37,400 tokens (−29%), ~$0.092 → ~$0.019 (−80%)** at current prices (Flash 3.8 doubles on 1 Jan 2027,
so the saving grows). Input tokens barely change; the saving is mostly Flash thinking tokens.
Context caching: the static prompts are 300–1,500 tokens, under the explicit-cache minimum and too low-traffic for
storage to pay off; static text stays at the front of each prompt so Vertex implicit caching can apply.
