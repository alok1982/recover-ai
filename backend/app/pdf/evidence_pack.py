"""Evidence pack PDF via WeasyPrint (HTML -> PDF; HarfBuzz shapes Devanagari). Fonts: Noto Sans + Noto Sans Devanagari."""
from __future__ import annotations

import base64
import html
import logging

from ..rules.formatting import format_amount, format_dt
from ..timeutil import utcnow

log = logging.getLogger("recoverai.pdf")

DISCLAIMER = ("RecoverAI prepares drafts and reminders. It is not legal advice, does not handle money, and never charges "
              "victims. Official agencies and your bank make all decisions.")

FIELD_ROWS = [
    ("Reference / UTR", "reference_id"), ("Amount", "_amount"), ("Date & time", "_occurred"),
    ("Payment method", "payment_method"), ("Payer bank", "payer_bank"), ("Beneficiary name", "beneficiary.name"),
    ("Beneficiary account / VPA", "beneficiary.account_or_vpa"), ("Beneficiary bank", "beneficiary.bank"),
    ("IFSC / bank code", "beneficiary.ifsc_or_code"), ("Scammer contacts", "scammer_contacts"), ("URLs", "urls"),
    ("Scam type", "scam_type"),
]


def _e(v) -> str:
    if v is None or v == "" or v == []:
        return "<span class='muted'>—</span>"
    if isinstance(v, list):
        v = ", ".join(map(str, v))
    return html.escape(str(v)).replace("\n", "<br>")


def _get(d: dict, dotted: str):
    v = d
    for p in dotted.split("."):
        v = v.get(p) if isinstance(v, dict) else None
    return v


def _desk_line(case: dict) -> str:
    """DEMO_MODE: name the receiving bank desk as the fictional demo bank (the complainant's own bank stays below)."""
    from .. import demobank
    rb = demobank.receiving_bank(case.get("country"))
    if not rb:
        return ""
    return (f"<div><b>Receiving bank desk:</b> {_e(rb['name'])} — demo only; no real bank receives this pack "
            f"from RecoverAI</div>")


def build_html(case: dict, pb: dict, evidence: list[dict], images: dict[str, bytes]) -> str:
    tz = pb["timezone"]
    ex = case.get("extraction") or {}
    cid = html.escape(case.get("publicRef") or case["id"])  # CR-01 / F8.5: readable reference, not the internal id
    from ..handoff import SANDBOX_WATERMARK, is_sandbox

    sandbox = is_sandbox(case)
    wm_css = (f"@bottom-left {{ content: \"{SANDBOX_WATERMARK}\"; font: bold 8pt 'Noto Sans'; color: #b45309; }}"
              if sandbox else "")
    wm_body = (f"<div class='sandbox-wm'>{SANDBOX_WATERMARK}</div><div class='sandbox-banner'>{SANDBOX_WATERMARK} — "
               "test case, never sent to a real bank</div>" if sandbox else "")
    gen = format_dt(utcnow(), tz)
    rows = []
    for label, key in FIELD_ROWS:
        if key == "_amount":
            v = format_amount(ex.get("amount"), ex.get("currency"))
        elif key == "_occurred":
            v = format_dt(case.get("incidentAt"), tz) if ex.get("occurred_at") else None
        else:
            v = _get(ex, key)
        src = "edited by victim" if key.lstrip("_") in (ex.get("edited_fields") or []) else ""
        rows.append(f"<tr><th>{label}</th><td>{_e(v)}</td><td class='muted'>{src}</td></tr>")
    # CR-03 C: complainant from the saved profile (name, address, bank — never the phone number)
    from .. import gate, profile as P
    prof = gate.owner_profile(case)
    if prof:
        rows[:0] = [f"<tr><th>Complainant</th><td>{_e(prof.get('fullName'))}</td><td class='muted'>profile</td></tr>",
                    f"<tr><th>Address</th><td>{_e(P.address_line(prof))}</td><td class='muted'>profile</td></tr>",
                    f"<tr><th>Complainant's bank</th><td>{_e(P.bank_name(prof))}</td><td class='muted'>profile</td></tr>"]
    timeline = []
    timeline.append(f"<tr><td>{_e(format_dt(case.get('incidentAt'), tz))}</td><td>Incident (payment)</td><td></td></tr>")
    timeline.append(f"<tr><td>{_e(format_dt(case.get('createdAt'), tz))}</td><td>Case opened in RecoverAI</td><td></td></tr>")
    for s in (case.get("plan") or {}).get("steps", []):
        when = format_dt(s.get("doneAt"), tz) if s.get("doneAt") else (f"due {s['deadlineDisplay']}" if s.get("deadlineDisplay") else "")
        status = "done" + (f" · ref {s['user_reference']}" if s.get("user_reference") else "") if s.get("status") == "done" else "pending"
        timeline.append(f"<tr><td>{_e(when)}</td><td>{_e(s['title'])}</td><td>{_e(status)}</td></tr>")
    for c in case.get("clocks") or []:
        timeline.append(f"<tr><td>{_e(c.get('dueDisplay'))}</td><td>{_e(c['label'])}"
                        f"{'<br><i>' + _e(c.get('note')) + '</i>' if c.get('note') else ''}</td><td>{_e(c['status'])}</td></tr>")
    ev_rows = []
    for e in evidence:
        thumb = ""
        if e["id"] in images:
            b64 = base64.b64encode(images[e["id"]]).decode()
            thumb = f"<img class='thumb' src='data:{e['mimeType']};base64,{b64}'>"
        elif e["type"] == "text":
            thumb = f"<div class='snip'>{_e((e.get('textContent') or '')[:260])}</div>"
        ev_rows.append(f"<tr><td>{thumb}</td><td>{_e(e['type'])}<br><span class='muted'>{_e(e.get('mimeType'))}</span><br>"
                       f"{_e(format_dt(e.get('uploadedAt'), tz))}</td><td class='hash'>{_e(e.get('sha256'))}</td></tr>")
    drafts_html = []
    for d in (case.get("drafts") or {}).values():
        drafts_html.append(
            f"<div class='draft'><h3>{_e(d.get('title'))}</h3><div class='cols'><div><h4>English</h4><pre>{_e(d.get('en'))}</pre></div>"
            f"<div><h4>{_e({'hi': 'हिन्दी', 'ms': 'Bahasa Melayu'}.get(d.get('localLang'), 'Local'))}</h4>"
            f"<pre>{_e(d.get('local'))}</pre></div></div></div>")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 16mm 13mm 18mm 13mm;
  @top-left {{ content: "RecoverAI evidence pack"; font: 8pt 'Noto Sans'; color: #0B6E8A; }}
  @top-right {{ content: "Case {cid} · page " counter(page) " of " counter(pages); font: 8pt 'Noto Sans'; color: #555; }}
  @bottom-center {{ content: "{DISCLAIMER}"; font: 6.5pt 'Noto Sans'; color: #666; }} {wm_css} }}
.sandbox-wm {{ position: fixed; top: 40%; left: 0; right: 0; text-align: center; transform: rotate(-30deg); font-size: 44pt;
  font-weight: bold; color: rgba(180, 83, 9, 0.13); z-index: -1; }}
.sandbox-banner {{ background: repeating-linear-gradient(45deg, #fff3cd, #fff3cd 8pt, #ffe08a 8pt, #ffe08a 16pt); color: #7a4b00;
  font-weight: bold; padding: 4pt 8pt; margin-bottom: 6pt; }}
body {{ font-family: 'Noto Sans', 'Noto Sans Devanagari', sans-serif; font-size: 8.6pt; color: #111; }}
h1 {{ color: #0B6E8A; font-size: 18pt; margin: 0 0 4pt; }} h2 {{ color: #0B6E8A; font-size: 11pt; margin: 10pt 0 4pt; border-bottom: 1px solid #cfe3ea; }}
h3 {{ font-size: 9.5pt; margin: 6pt 0 2pt; }} h4 {{ font-size: 8pt; margin: 0 0 2pt; color: #555; }}
table {{ width: 100%; border-collapse: collapse; }} th, td {{ text-align: left; vertical-align: top; padding: 2.5pt 4pt; border-bottom: 1px solid #eee; }}
th {{ width: 32%; color: #333; font-weight: 600; }} .muted {{ color: #888; }} .hash {{ font-family: monospace; font-size: 7pt; word-break: break-all; }}
.thumb {{ max-width: 70pt; max-height: 120pt; border: 1px solid #ddd; }} .snip {{ max-width: 150pt; font-size: 7pt; color: #444; }}
.cols {{ display: flex; gap: 8pt; }} .cols > div {{ flex: 1; }}
pre {{ white-space: pre-wrap; font-family: 'Noto Sans', 'Noto Sans Devanagari', sans-serif; font-size: 7.6pt; margin: 0; background: #f7fafb; padding: 4pt; }}
.cover {{ background: #eaf4f7; padding: 8pt 10pt; border-left: 4pt solid #0B6E8A; margin-bottom: 6pt; }}
.disc {{ margin-top: 10pt; font-size: 7.5pt; color: #444; border-top: 1px solid #ccc; padding-top: 4pt; }}
</style></head><body>
{wm_body}
<div class="cover"><h1>Evidence pack</h1>
<div><b>Case reference:</b> {cid} &nbsp; <b>Country:</b> {_e(pb['name'])} &nbsp; <b>Playbook:</b> {_e(pb['version'])}</div>
<div><b>Generated:</b> {_e(gen)} &nbsp; <b>Status:</b> {_e(case.get('status'))} &nbsp; <b>Bank status:</b> {_e(case.get('bankStatus'))}</div>{_desk_line(case)}</div>
<h2>Incident summary</h2><p>{_e(ex.get('narrative_en'))}</p>{'<p>' + _e(ex.get('narrative_local')) + '</p>' if ex.get('narrative_local') and ex.get('narrative_local') != ex.get('narrative_en') else ''}
<h2>Extracted and confirmed facts</h2><table>{''.join(rows)}</table>
<h2>Timeline</h2><table>{''.join(timeline)}</table>
<h2>Evidence (SHA-256)</h2><table>{''.join(ev_rows) or '<tr><td>No evidence uploaded</td></tr>'}</table>
<h2>Drafted filings</h2>{''.join(drafts_html) or '<p class="muted">Drafts not generated yet.</p>'}
<div class="disc">{DISCLAIMER}</div>
</body></html>"""


def render_pdf(case: dict, pb: dict, evidence: list[dict], images: dict[str, bytes]) -> bytes:
    from weasyprint import HTML

    return HTML(string=build_html(case, pb, evidence, images)).write_pdf()
