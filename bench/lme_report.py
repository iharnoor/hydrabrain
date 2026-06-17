"""Render LongMemEval results into a self-contained HTML report."""

from __future__ import annotations

import html
import json
from pathlib import Path

REPORT_PATH = Path(__file__).resolve().parent / "longmemeval_report.html"


def write_report(data: dict, path: Path = REPORT_PATH) -> Path:
    s = data["summary"]
    has_h = "hydra_qa_acc" in s
    hq = s.get("hydra_qa_acc", 0) * 100
    bq = s.get("base_qa_acc", 0) * 100

    type_rows = []
    for t, v in s["per_type"].items():
        h = v["hydra_qa"] * 100
        b = v["base_qa"] * 100
        cls = "win" if has_h and h > b else ("lose" if has_h and b > h else "")
        type_rows.append(
            f'<tr class="{cls}"><td class="l">{html.escape(t)}</td><td>{v["n"]}</td>'
            + (f'<td><b>{h:.0f}%</b></td>' if has_h else "")
            + f'<td>{b:.0f}%</td></tr>'
        )

    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>LongMemEval — HydraDB vs gbrain-stack</title>
<style>
 body{{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#1a1a2e}}
 h1{{font-size:25px;margin-bottom:2px}} .sub{{color:#666;margin-top:0}}
 .cards{{display:flex;gap:16px;margin:22px 0;flex-wrap:wrap}}
 .card{{flex:1;min-width:190px;background:#f7f7fb;border:1px solid #e6e6f0;border-radius:12px;padding:18px}}
 .card h3{{margin:0 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:#888}}
 .big{{font-size:30px;font-weight:700}} .hydra{{color:#7c3aed}} .base{{color:#ea580c}}
 table{{border-collapse:collapse;width:100%;margin-top:20px;font-size:14px}}
 th,td{{border-bottom:1px solid #eee;padding:8px 10px;text-align:center}} td.l{{text-align:left}}
 tr.win{{background:#f0fdf4}} tr.lose{{background:#fef2f2}}
 .note{{color:#666;font-size:13px;background:#f7f7fb;border-left:3px solid #7c3aed;padding:12px 16px;border-radius:6px;margin-top:22px}}
</style></head><body>
<h1>LongMemEval — HydraDB <span style="color:#aaa">vs</span> gbrain-stack</h1>
<p class="sub">{s['data']} · {s['n']} questions · per-question isolated haystacks · LLM-as-judge QA accuracy</p>
<div class="cards">
"""
    if has_h:
        doc += f"""
 <div class="card"><h3>QA accuracy — HydraDB</h3><div class="big hydra">{hq:.1f}%</div></div>
 <div class="card"><h3>QA accuracy — gbrain-stack</h3><div class="big base">{bq:.1f}%</div></div>
 <div class="card"><h3>HydraDB advantage</h3><div class="big" style="color:#16a34a">{hq-bq:+.1f} pts</div></div>
 <div class="card"><h3>evidence recall@{s['top_k']}</h3><div class="big"><span class="hydra">{s['hydra_evidence_recall']*100:.0f}%</span> / <span class="base">{s['base_evidence_recall']*100:.0f}%</span></div></div>
"""
    else:
        doc += f'<div class="card"><h3>QA accuracy — gbrain-stack</h3><div class="big base">{bq:.1f}%</div></div>'

    head_h = "<th>HydraDB QA</th>" if has_h else ""
    doc += f"""</div>
<h3>QA accuracy by ability</h3>
<table><thead><tr><th class="l">question type</th><th>n</th>{head_h}<th>gbrain-stack QA</th></tr></thead>
<tbody>{''.join(type_rows)}</tbody></table>
<p class="note"><b>Why LongMemEval.</b> This is the standard academic benchmark (ICLR 2025) for long-term
chat memory. Each question carries its own multi-session history; the system must store it, retrieve the
right sessions, and answer. It is the regime HydraDB is designed for — multi-session and temporal
reasoning — and the realistic proxy for the goal: a second brain over everything you consume. Both systems
ingest one memory per session into isolated namespaces (HydraDB sub-tenant per question; a fresh local
dense+BM25+RRF index per question for the baseline).</p>
</body></html>"""
    path.write_text(doc)
    return path


if __name__ == "__main__":
    write_report(json.loads((Path(__file__).resolve().parent / "longmemeval_results.json").read_text()))
    print(REPORT_PATH)
