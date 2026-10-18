"""Render the benchmark table (rows from /tmp/bench_rows.json or argv[1]) to docs/qa/benchmark-table.png."""
import html, json, sys
from playwright.sync_api import sync_playwright
rows = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bench_rows.json"))
out = sys.argv[2] if len(sys.argv) > 2 else "docs/qa/benchmark-table.png"
tr = "".join(
    f"<tr><td class=m>{html.escape(a)}</td><td>{html.escape(b)}</td><td>{html.escape(c)}</td>"
    f"<td class='p {'ok' if e.startswith('✅') else 'no'}'>{html.escape(e)}</td></tr>" for a, b, c, e in rows)
page = f"""<html><head><meta charset=utf-8><style>
body{{margin:0;padding:0;background:#fff;font-family:'Noto Sans','Segoe UI',Arial,sans-serif}}
h2{{margin:0 0 4px;color:#0B6E8A;font-size:22px}} .sub{{color:#555;font-size:13px;margin-bottom:12px}}
table{{border-collapse:collapse;width:1180px;font-size:15px}}
th{{background:#0B6E8A;color:#fff;text-align:left;padding:11px 14px;font-weight:600}}
td{{padding:10px 14px;border-bottom:1px solid #d6e6ec;vertical-align:top}}
tr:nth-child(odd) td{{background:#f3f9fb}} tr:nth-child(even) td{{background:#fff}}
td.m{{font-weight:600;color:#123}} td.p{{white-space:nowrap;font-weight:600}} .ok{{color:#137a3d}} .no{{color:#b54708}}
.note{{color:#666;font-size:12px;margin-top:10px;width:1180px}}
</style></head><body><div id=w style="display:inline-block;padding:24px"><h2>RecoverAI — Prototype performance (measured 18 Oct 2026)</h2>
<div class=sub>Live Cloud Run build recoverai-api-00018-t5d (asia-south1), called from a client in Ashburn, VA (US). 20 India cases (EN/HI), sandbox only.</div>
<table><tr><th>Metric</th><th>Target</th><th>Measured</th><th>Pass?</th></tr>{tr}</table>
<div class=note>Bank-visible time is counted from the actual publish; the 10 s undo window is excluded. Key-field miss: beneficiary bank on the UPI screenshot fixture
(“Sample Co-op Bk” as printed vs “Sample Co-operative Bank”). Tokens: usage_metadata, same Vertex models and prompts, 3 full demo cases. Details: docs/qa/benchmark-2026-10-18.md</div></div>
</body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1240, "height": 600}, device_scale_factor=2)
    pg.set_content(page); pg.locator("#w").screenshot(path=out); b.close()
print(out)
