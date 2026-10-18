"""Print one line per results file: task, model, config, n, headline metrics, avg tokens and $/item."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RES = Path(__file__).resolve().parent / "results"


def headline(d: dict) -> str:
    m = d["metrics"]
    t = d["task"]
    if t == "guard":
        x = m["production(model OR keyword net)"]
        return f"P={x['precision']:.4f} R={x['recall']:.4f} (tp {x['tp']} fp {x['fp']} fn {x['fn']})"
    if t == "extraction":
        return f"P={m['precision']:.4f} R={m['recall']:.4f} fails={m['schema_or_call_failures']}"
    if t == "transcribe":
        return f"pass={m['pass_rate']:.4f} meanWER={m['mean_wer']}"
    if t == "drafts":
        return (f"first={m['first_attempt_pass']:.4f} prod={m['pass_after_1_regen (production)']:.4f} "
                f"regen={m['regen_rate']:.4f} localLang={m['local_language_ok']:.4f}")
    if t == "plan_explain":
        return f"pass={m['pass_rate']:.4f} postcheck={m['post_check_ok']:.4f} lang={m['lang_ok']:.4f} words={m['mean_words']}"
    if t == "bank_reason":
        return (f"grounded={m['grounded_pass_rate']:.4f} signals={m['all_signals_named']:.4f} nums={m['no_ungrounded_numbers']:.4f} "
                f"fallbacks={m['template_fallbacks']}")
    if t == "copilot":
        return (f"all={m['all_checks_pass']:.4f} tool={m['tool_card_correct']:.4f} nonempty={m['non_empty_reply']:.4f} "
                f"post={m['post_check_clean_first_try']:.4f} lang={m['reply_language_ok']:.4f} inj={m['injection_resisted']}")
    if t == "fallback":
        return " ".join(f"{k}={v['pass_rate']:.4f}(n={v['n']})" for k, v in m.items())
    return json.dumps(m)[:200]


def main():
    pat = sys.argv[1] if len(sys.argv) > 1 else ""
    for p in sorted(RES.glob("*.json")):
        if pat not in p.name:
            continue
        d = json.loads(p.read_text())
        u = d["usage"]
        print(f"{p.stem:58} n={d['n']:4} {headline(d):80} in={u['avg_in']:5} out={u['avg_out']:4} think={u['avg_think']:5} "
              f"calls/item={u['calls_per_item']} ${u['usd_per_item']:.6f}")


if __name__ == "__main__":
    main()
