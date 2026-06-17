"""Render benchmark results.json into a self-contained HTML report."""

from __future__ import annotations

import html
import json
from pathlib import Path

REPORT_PATH = Path(__file__).resolve().parent / "report.html"


def _bar(pct: float, color: str) -> str:
    return (f'<div class="bar"><div class="fill" style="width:{pct:.0f}%;background:{color}">'
            f'</div><span>{pct:.1f}%</span></div>')


def write_report(data: dict, path: Path = REPORT_PATH) -> Path:
    s = data["summary"]
    rows = data["rows"]
    has_h = "hydra_recall_at5" in s
    has_judge = "base_judge_yes" in s

    h_r = s.get("hydra_recall_at5", 0) * 100
    b_r = s.get("base_recall_at5", 0) * 100
    delta = h_r - b_r

    tr = []
    for r in rows:
        cls = ""
        if has_h:
            cls = ("win" if r["hydra_recall"] > r["base_recall"]
                   else "lose" if r["base_recall"] > r["hydra_recall"] else "")
        cells = [
            f'<td class="q">{html.escape(r["name"])}<br><small>{html.escape(r["category"])}</small></td>',
            f'<td>{r["hydra_recall"]*100:.0f}%</td><td>{r["hydra_mrr"]:.2f}</td>' if has_h else "",
            f'<td>{r["base_recall"]*100:.0f}%</td><td>{r["base_mrr"]:.2f}</td>',
        ]
        if has_judge:
            hv = r.get("hydra_verdict", "—"); bv = r.get("base_verdict", "—")
            cells.append(f'<td class="v{hv}">{hv}</td>' if has_h else "")
            cells.append(f'<td class="v{bv}">{bv}</td>')
        tr.append(f'<tr class="{cls}">' + "".join(cells) + "</tr>")

    head_h = "<th>Hydra r@5</th><th>Hydra MRR</th>" if has_h else ""
    head_jh = "<th>Hydra judge</th>" if (has_judge and has_h) else ""
    head_jb = "<th>Base judge</th>" if has_judge else ""

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>HydraDB vs gbrain-stack</title>
<style>
  body{{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:980px;margin:40px auto;padding:0 20px;color:#1a1a2e}}
  h1{{font-size:26px;margin-bottom:4px}} .sub{{color:#666;margin-top:0}}
  .cards{{display:flex;gap:16px;margin:24px 0;flex-wrap:wrap}}
  .card{{flex:1;min-width:200px;background:#f7f7fb;border:1px solid #e6e6f0;border-radius:12px;padding:18px}}
  .card h3{{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:#888}}
  .big{{font-size:30px;font-weight:700}} .hydra{{color:#7c3aed}} .base{{color:#ea580c}}
  .delta{{color:#16a34a;font-weight:700}}
  .bar{{position:relative;background:#eee;border-radius:6px;height:22px;margin-top:6px}}
  .bar .fill{{height:100%;border-radius:6px}} .bar span{{position:absolute;right:8px;top:1px;font-size:12px;color:#222}}
  table{{border-collapse:collapse;width:100%;margin-top:24px;font-size:13px}}
  th,td{{border-bottom:1px solid #eee;padding:8px 10px;text-align:center}}
  td.q{{text-align:left}} td.q small{{color:#999}}
  tr.win{{background:#f0fdf4}} tr.lose{{background:#fef2f2}}
  .vYES{{color:#16a34a;font-weight:700}} .vNO{{color:#dc2626}}
  .note{{color:#666;font-size:13px;background:#f7f7fb;border-left:3px solid #7c3aed;padding:12px 16px;border-radius:6px;margin-top:24px}}
</style></head><body>
<h1>HydraDB <span style="color:#aaa">vs</span> gbrain-stack</h1>
<p class="sub">{s['corpus_pages']} pages · {s['queries']} gold queries · recall@{s['top_k']} (gbrain's own metric)</p>
<div class="cards">
"""
    if has_h:
        doc += f"""
  <div class="card"><h3>recall@5 — HydraDB</h3><div class="big hydra">{h_r:.1f}%</div>{_bar(h_r,'#7c3aed')}</div>
  <div class="card"><h3>recall@5 — gbrain-stack</h3><div class="big base">{b_r:.1f}%</div>{_bar(b_r,'#ea580c')}</div>
  <div class="card"><h3>HydraDB advantage</h3><div class="big delta">{delta:+.1f} pts</div>
    <small>graph-native lift over the graph-disabled hybrid stack</small></div>
  <div class="card"><h3>per-query</h3><div class="big">{s['hydra_wins']}–{s['base_wins']}–{s['ties']}</div>
    <small>HydraDB wins · base wins · ties</small></div>
"""
    else:
        doc += f'<div class="card"><h3>recall@5 — gbrain-stack</h3><div class="big base">{b_r:.1f}%</div></div>'

    if has_judge:
        hj = s.get("hydra_judge_yes")
        doc += '<div class="card"><h3>LLM-as-judge (YES)</h3><div class="big">'
        if hj is not None:
            doc += f'<span class="hydra">{hj}</span> / <span class="base">{s["base_judge_yes"]}</span>'
        else:
            doc += f'<span class="base">{s["base_judge_yes"]}</span>'
        doc += f'</div><small>out of {s["queries"]}</small></div>'

    doc += f"""</div>
<table><thead><tr><th>Query</th>{head_h}<th>Base r@5</th><th>Base MRR</th>{head_jh}{head_jb}</tr></thead>
<tbody>{''.join(tr)}</tbody></table>
<p class="note"><b>Why this is a fair fight.</b> Both systems see the identical corpus and queries.
The baseline reproduces gbrain's documented retrieval pipeline — pgvector-equivalent dense vectors
(Gemini text-embedding-004), BM25, and reciprocal-rank fusion — but <b>without a knowledge graph</b>.
HydraDB runs hybrid recall <b>with</b> its self-wired graph (<code>infer=True</code>). The gap is
exactly the lift gbrain attributes to its graph — except HydraDB builds it natively, no extraction
pipeline required.</p>
</body></html>"""
    path.write_text(doc)
    return path


if __name__ == "__main__":
    data = json.loads((Path(__file__).resolve().parent / "results.json").read_text())
    print(write_report(data))
