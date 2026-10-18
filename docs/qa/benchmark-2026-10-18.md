# RecoverAI — Prototype performance / benchmarking (measured 18 Oct 2026)

Every number below comes from runs made on 18 Oct 2026, 21:15–21:40 IST. Nothing is estimated or carried over.

- **Build:** live Cloud Run `recoverai-api-00018-t5d` (100 % traffic, `main` @ `c590f3a`), asia-south1, min instances 1 (warm). Every bank share recorded destination **SANDBOX** (20/20).
- **How the app was called:** directly on the Cloud Run URL `https://recoverai-api-xgw63iesqa-el.a.run.app`, the same way the app calls chat (`VITE_CHAT_BASE`). Firebase Hosting was not used, because it buffers streamed responses.
- **Vantage point:** the benchmark box egresses through Fastly in **Ashburn, Virginia (US)** to asia-south1 (Mumbai). Health-check round trip p50 0.34 s / p95 0.62 s. Each client figure includes that trans-Pacific overhead for every request in the step, so a user in India would see less. Server-side figures from Cloud Logging are given next to them.
- **Accounts:** one throw-away victim (+91 90000 01121, complete synthetic profile). It and its 29 cases (20 trials, 6 fixtures, 3 guard checks) were deleted afterwards with `DELETE /api/me`, and so were the 20 sandbox bank copies. Seed accounts and the user's own account were not touched.

## Results

| Metric | Target | Measured | Pass? |
|---|---|---|---|
| Fact extraction (3 evidence files) | ≤ 20 s (p95) | p95 15.6 s · p50 12.7 s · max 19.2 s (n=20) | ✅ |
| All drafts generated | ≤ 30 s | p95 8.1 s · p50 4.7 s · max 14.9 s (n=20) | ✅ |
| Evidence-pack PDF | ≤ 5 s | p95 3.3 s · p50 2.6 s · max 3.9 s (n=20, 10 Hindi) | ✅ |
| Victim → bank case visible | ≤ 3 s | p95 2.2 s · p50 1.6 s · max 2.4 s (n=20; 10 s undo excluded) | ✅ |
| Key fields correct on test fixtures | 100 % (6 fixtures) | 97.2 % (35/36); eval P/R 99.81 / 99.68 % | ❌ 1 field |
| Recovery-scam guard on test message | Flagged | Flagged 3/3 (EN/HI/MS), warning before reply; eval P/R 100 / 100 (175) | ✅ |
| Gemini tokens per case | ≈ 22k | 14.6k avg (n=3); 17.3k with 1 extra question | ✅ under |

PNG for the submission: `docs/qa/benchmark-table.png`.

### p50 / p95 / max (seconds)

| Metric | Client, from the box (p50 / p95 / max) | Server-side, Cloud Logging (p50 / p95 / max) |
|---|---|---|
| Fact extraction, first upload → facts card | 12.69 / 15.59 / 19.2 | — |
| … of which the 3 uploads (9 requests) | 5.14–7.13 s | — |
| … of which extraction only (evidence_added → facts card) | 6.58 / 9.76 / 13.55 | 6.28 / 9.48 / 13.26 (whole chat request) |
| All drafts, generate_all → drafts card | 4.71 / 8.11 / 14.92 | 4.38 / 7.76 / 14.56 (whole turn) |
| Evidence-pack PDF, rebuild → PDF downloaded | 2.62 / 3.33 / 3.87 | 1.13 / 1.77 / 1.83 (build + sign) |
| Evidence-pack PDF, Hindi cases only | 2.62 / 3.61 / 3.87 | — |
| Evidence-pack PDF, already built (what the app opens after drafts) | 0.45 / 0.75 / 0.78 | — |
| Bank case visible, send → bank-desk Firestore listener | 1.56 / 2.17 / 2.43 | 1.26 / 1.86 / 2.13 (send request received → bank_cases doc created) |
| Bank case visible, send → bank API GET 200 (100 ms poll) | 2.02 / 2.57 / 2.92 | — |

## Method

**Trials 1–4.** 20 sequential India cases, alternating English and Hindi, one throw-away account (`scripts/qa/benchmark_live.py`).

1. **Fact extraction (3 files).** The same 3 evidence files the app's upload card takes for the India story: `fixtures/in_upi_success.png` (UPI screenshot), `fixtures/in_whatsapp_scam.txt` (WhatsApp chat, pasted) and `fixtures/in_voice_note.mp3` (Hindi voice note). The demo story has only one screenshot, so the 3 evidence files are 1 image, 1 text and 1 audio, not 3 images. The clock starts at the first `upload-url` request. Uploads go to GCS through signed URLs. Then the chat trigger `evidence_added` runs with all three ids, and the clock stops when the facts card arrives on the SSE stream.
2. **All drafts.** Facts are confirmed and the plan card shown, then `generate_all` is sent. The clock runs from that request to the drafts card. The drafts are the 1930 hotline script, the NCRP complaint and the bank dispute letter, all with Gemini text; the consent card follows. One outlier (trial 7) took 14.9 s.
3. **Evidence-pack PDF.** `POST /evidence-pack?rebuild=true` forces a fresh build: Hindi/Latin fonts, evidence thumbnails, SHA-256 list. The clock stops when the PDF bytes have downloaded from the signed URL (`%PDF` checked, 142–144 KB). The cached figure is what the app shows, because `generate_all` already builds the pack.
4. **Victim → bank visible.** A Firestore listener on `bank_cases` with `caseId == <case>` is attached before sending; it is the same query type as the bank desk's `onSnapshot`. Then come `send-to-bank/preview` and `POST send-to-bank` (confirmed). The clock starts at that POST, which is the actual publish to Pub/Sub. **The app's 10 s undo countdown runs before this call and is excluded.** The clock stops when the listener first sees the doc. The bank API was also polled every 100 ms. Server-side, the bank_cases doc `create_time` came 1.26 s (p50) after Cloud Run received the send request.

**5. Key fields.** Each of 6 fixtures was extracted once on the live build: its own case, uploads, `evidence_added`, then the case's extraction read back. The fixtures are the two story fixtures from `fixtures/`, with ground truth in `fixtures/expected/*.json`. The other four are the first two Indian and first two Malaysian image fixtures from `backend/evals/data/extraction.jsonl`, each with its own `truth`. Matching uses the eval harness's `norm_field`: exact match after normalisation. Strict result: **35/36 = 97.2 %**. The one miss is the beneficiary bank on `fixtures/in_case`. The screenshot prints the abbreviation “Sample Co-op Bk”, and the model returned exactly that. The ground truth is the full name “Sample Co-operative Bank”. The demo script (README step 1, `e2e_demo.py`) has the victim correct this field on the facts card before confirming. The same field was the only miss in all 20 trial extractions (0/20; every other key field 20/20). Extra fields (currency, beneficiary name, payer bank, payment method): 24/24 on the 6 fixtures.

| Fixture | Amount | UTR / ref | Date-time | Beneficiary (VPA / acct) | Beneficiary bank | Scam type | Score |
|---|---|---|---|---|---|---|---|
| fixtures/in_case (UPI screenshot + WhatsApp) | ✅ | ✅ | ✅ | ✅ | ❌ got “Sample Co-op Bk”, truth “Sample Co-operative Bank” | ✅ | 5/6 |
| fixtures/my_case (bank-transfer screenshot + SMS) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 6/6 |
| backend/evals/data ex_000 (IN, hi) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 6/6 |
| backend/evals/data ex_004 (IN, hi) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 6/6 |
| backend/evals/data ex_002 (MY, ms) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 6/6 |
| backend/evals/data ex_006 (MY, ms) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 6/6 |
| **Per field** | 6/6 | 6/6 | 6/6 | 6/6 | 5/6 | 6/6 | **35/36** |

Extraction eval, run now (`evals.run --task extraction`, production cascade, 156 items): precision **99.81 %**, recall **99.68 %** (tp 1556, fp 3, fn 5, 0 call failures). File: `docs/qa/bench/extraction__gemini-3.1-flash-lite__cascade-bench-1018.json`.

**6. Recovery-scam guard.** The plan's G1 message was sent as a chat turn on live in English, Hindi and Malay (new case each). All three were **flagged**, and the warning card arrived before any reply text. Guard eval, run now (175 items): precision/recall **100 / 100** (`guard__gemini-3.5-flash-lite__bench-1018.json`).

| Lang | Message | Flagged | Warning before reply | Cards |
|---|---|---|---|---|
| en | Pay ₹5,000 processing fee to recover your money — Cyber Recovery Cell | ✅ | ✅ | warning, upload |
| hi | अपना पैसा वापस पाने के लिए ₹5,000 प्रोसेसिंग फीस भरें — साइबर रिकवरी सेल | ✅ | ✅ | warning, upload |
| ms | Bayar yuran pemprosesan RM500 untuk dapatkan semula wang anda — Unit Pemulihan Siber | ✅ | ✅ | warning, upload |

**7. Gemini tokens per case.** The live service logs `usage_metadata` (`gemini_call` log) for every direct Gemini call, but **not** for the ADK co-pilot's calls. So the full per-case count was taken from a **local in-process run of the same backend code against the same Vertex AI models and prompts**. The production task-model env vars were copied from the 00018 revision (`backend/evals/token_bench.py`). A spy on the google-genai SDK records `usage_metadata` from every call, ADK streaming included. Three complete India demo cases were run, following the README story in Hindi:

1. the typed message “मैंने CBI वाले को 1,95,000 भेज दिए”
2. the UPI screenshot plus the pasted WhatsApp chat → facts
3. the bank-field fix plus confirm → plan
4. generate_all → drafts
5. the evidence pack
6. sharing with the bank (bank receiver reasoning)

Results:

- Core case average: **14,584 tokens** (prompt 12,112, output 2,472, thinking 0).
- With one extra co-pilot question: 17,307.
- The local run stored blobs in a local directory, so images reached Gemini as inline bytes instead of GCS URIs; the image token count is the same either way.

| Task | Model | Calls / case | Prompt | Output | Total |
|---|---|---|---|---|---|
| Intake / fact extraction | gemini-3.1-flash-lite | 1 | 2,731 | 555 | 3,286 |
| Recovery-scam guard | gemini-3.5-flash-lite | 3 | 1,800 | 98 | 1,898 |
| Co-pilot (ADK) | gemini-3.5-flash-lite | 3 | 4,257 | 77 | 4,334 |
| Plan explanation | gemini-3.5-flash-lite | 1 | 447 | 148 | 595 |
| Drafts (hotline script, NCRP, bank letter) | gemini-3.1-flash-lite | 3 | 2,211 | 1,485 | 3,696 |
| Bank case reasoning | gemini-3.5-flash-lite | 1 | 666 | 109 | 775 |
| **Total (core demo case)** | | 12 | 12,112 | 2,472 | **14,584** |

| Model | Calls / case | Prompt | Output | Total |
|---|---|---|---|---|
| gemini-3.5-flash-lite | 8 | 7,170 | 432 | 7,602 |
| gemini-3.1-flash-lite | 4 | 4,942 | 2,040 | 6,982 |

Per step (total tokens):

| Step | Case 1 | Case 2 | Case 3 | Avg |
|---|---|---|---|---|
| 1 typed message (guard + co-pilot) | 4,746 | 4,743 | 4,770 | 4,753 |
| 2 evidence → extraction (guard on pasted text + intake) | 4,771 | 4,759 | 4,764 | 4,765 |
| 3 facts confirmed → plan | 598 | 591 | 595 | 595 |
| 4 generate_all → drafts | 3,559 | 3,795 | 3,735 | 3,696 |
| 5 evidence pack PDF | 0 | 0 | 0 | 0 |
| 6 consent → share with bank (bank case receiver reasoning) | 780 | 771 | 775 | 775 |
| 7 extra co-pilot question (optional) | 2,758 | 2,694 | 2,717 | 2,723 |

**Cross-check against live logs.** On the 20 live benchmark cases, the `gemini_call` usage logs (the directly logged tasks, without the ADK co-pilot) averaged **10,629 tokens per case**. Those cases had no typed co-pilot message and included the voice note. The local run's non-co-pilot share is 10,250, which agrees.

| Logged step (live) | Calls / case | Prompt | Output |
|---|---|---|---|
| bank_reason | 1 | 667 | 126 |
| draft:bank_dispute_letter | 1 | 839 | 788 |
| draft:hotline_script | 1 | 691 | 296 |
| draft:ncrp_complaint | 1.15 | 813 | 543 |
| guard | 2 | 1,410 | 68 |
| intake | 1 | 3,242 | 557 |
| plan_explain | 1 | 436 | 153 |

Observation (not changed): the guard runs twice on pasted chat text, once when the text is added and once on `evidence_added`, about 700 tokens each time.

## Raw timings (client, seconds)

| # | Lang | Upload 3 files | Facts card (total) | Extraction only | Drafts card | Drafts turn end | PDF (rebuild) | PDF (cached) | Send call | Bank visible (Firestore) | Bank visible (API) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | en | 5.87 | 14.82 | 8.95 | 4.95 | 4.97 | 2.61 | 0.5 | 0.67 | 2.43 | 2.92 |
| 2 | hi | 5.55 | 10.88 | 5.33 | 4.49 | 4.5 | 3.87 | 0.45 | 0.67 | 1.87 | 2.03 |
| 3 | en | 5.51 | 11.18 | 5.67 | 5.24 | 5.26 | 2.63 | 0.46 | 0.65 | 1.69 | 1.87 |
| 4 | hi | 5.44 | 10.52 | 5.08 | 4.85 | 4.87 | 2.61 | 0.45 | 0.68 | 1.8 | 2.05 |
| 5 | en | 5.88 | 12.02 | 6.15 | 4.4 | 4.41 | 3.1 | 0.44 | 0.67 | 1.52 | 2.0 |
| 6 | hi | 5.14 | 13.42 | 8.28 | 4.84 | 4.85 | 2.6 | 0.47 | 0.68 | 1.65 | 2.05 |
| 7 | en | 5.72 | 13.54 | 7.82 | 14.92 | 14.93 | 2.71 | 0.44 | 1.19 | 2.16 | 2.55 |
| 8 | hi | 5.47 | 10.32 | 4.85 | 5.05 | 5.07 | 2.57 | 0.43 | 0.65 | 1.58 | 1.95 |
| 9 | en | 5.36 | 13.8 | 8.44 | 4.38 | 4.39 | 2.59 | 0.45 | 0.64 | 1.8 | 1.98 |
| 10 | hi | 5.57 | 11.45 | 5.89 | 4.77 | 4.79 | 3.3 | 0.44 | 0.68 | 1.49 | 2.05 |
| 11 | en | 5.92 | 12.11 | 6.2 | 4.39 | 4.4 | 2.6 | 0.44 | 0.64 | 1.43 | 1.86 |
| 12 | hi | 6.92 | 15.4 | 8.49 | 4.53 | 4.54 | 2.6 | 0.48 | 0.65 | 1.62 | 1.95 |
| 13 | en | 5.56 | 13.22 | 7.65 | 4.82 | 4.84 | 2.74 | 0.43 | 0.67 | 1.49 | 1.97 |
| 14 | hi | 6.36 | 12.16 | 5.79 | 4.66 | 4.67 | 2.38 | 0.78 | 0.71 | 1.52 | 2.03 |
| 15 | en | 7.13 | 14.09 | 6.96 | 4.51 | 4.52 | 3.23 | 0.51 | 0.65 | 1.52 | 2.05 |
| 16 | hi | 5.35 | 13.98 | 8.63 | 4.63 | 4.65 | 2.62 | 0.46 | 0.65 | 1.51 | 2.03 |
| 17 | en | 5.82 | 12.0 | 6.18 | 4.57 | 4.57 | 2.8 | 0.43 | 0.65 | 1.53 | 1.84 |
| 18 | hi | 5.21 | 10.95 | 5.73 | 5.53 | 5.54 | 2.62 | 0.75 | 0.65 | 1.44 | 2.01 |
| 19 | en | 5.46 | 15.02 | 9.56 | 4.52 | 4.53 | 2.59 | 0.47 | 0.66 | 1.55 | 1.96 |
| 20 | hi | 5.64 | 19.2 | 13.55 | 7.75 | 7.76 | 3.16 | 0.42 | 0.7 | 1.63 | 2.06 |

## Files
- `docs/qa/bench/live_20261018.json`: every trial, fixture comparison (truth vs got) and guard result
- `docs/qa/bench/live_server_side_20261018.json`: Cloud Run request latencies and the live `gemini_call` token logs per case
- `docs/qa/bench/tokens_20261018.json`: every Gemini call (task, model, in/out tokens) for the 3 local demo cases
- `docs/qa/bench/guard__…bench-1018.json`, `docs/qa/bench/extraction__…cascade-bench-1018.json`: eval runs
- Scripts: `scripts/qa/benchmark_live.py`, `backend/evals/token_bench.py`, `scripts/qa/render_benchmark_png.py`
