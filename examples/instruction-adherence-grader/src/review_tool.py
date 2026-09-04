"""Human review sheet: emit and ingest. (Lane C)

build_review_sheet produces a single self-contained HTML file.
The reviewer works through one row per (email, rule), confirms or overturns
each draft verdict, optionally enters an overturn reason, and clicks Export.
The export button writes a corrected labels_ground_truth.json without any
server round-trip: all state lives in JavaScript variables.

Key UX decisions that keep the ~300-row gate inside the two-hour budget:
  - Rows are grouped by email, so each email body is read once, not six times.
  - Keyboard navigation: J/K to move between rows, Y to confirm, N to overturn,
    E to focus the reason box, Tab to advance.
  - A fixed progress counter shows n confirmed / n total.
  - The current email body stays visible in a sticky panel while scrolling the
    rule rows below it.
  - Borderline / low-confidence rows are highlighted so the reviewer can slow
    down on exactly the cases that matter.

ingest_reviewed validates and writes labels_ground_truth.json.
"""

from __future__ import annotations

import json
import os

from src.schemas import SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# Public API (matches CONTRACTS.md section 2)
# --------------------------------------------------------------------------- #
def build_review_sheet(emails_path: str, labels_path: str, out_path: str) -> str:
    """Emit a self-contained HTML review sheet.

    Returns `out_path` so the caller can print or open it.
    """
    with open(emails_path, encoding="utf-8") as f:
        emails_data = json.load(f)
    with open(labels_path, encoding="utf-8") as f:
        labels_data = json.load(f)

    emails = {e["id"]: e for e in emails_data.get("emails", [])}
    labels = labels_data.get("labels", [])
    provenance = labels_data.get("provenance", {})

    html = _render_html(emails, labels, provenance)
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def ingest_reviewed(reviewed_path: str, out_path: str) -> dict:
    """Load a reviewer-exported JSON file and write labels_ground_truth.json.

    The reviewed file is the direct export from the HTML sheet. This function
    validates it and adds `"version"` and `"provenance"` if missing, then
    writes to out_path.
    """
    with open(reviewed_path, encoding="utf-8") as f:
        data = json.load(f)

    labels = data.get("labels", [])
    for lbl in labels:
        for key in ("email_id", "rule_id", "violated", "kind"):
            if key not in lbl:
                raise ValueError(f"label entry missing required key {key!r}: {lbl}")

    out = {
        "version": SCHEMA_VERSION,
        "provenance": data.get(
            "provenance",
            {"kind": "human_reviewed", "reviewed_at": "", "reviewer_note": ""},
        ),
        "labels": labels,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return out


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #
def _render_html(
    emails: dict,
    labels: list[dict],
    provenance: dict,
) -> str:
    # Group labels by email_id, preserving order.
    by_email: dict[str, list[dict]] = {}
    for lbl in labels:
        eid = lbl["email_id"]
        by_email.setdefault(eid, []).append(lbl)

    email_ids = list(by_email.keys())
    total_rows = len(labels)

    # Build the flat JS data array and the HTML row list together.
    rows_html: list[str] = []
    row_idx = 0
    for eid in email_ids:
        email = emails.get(eid, {})
        body_escaped = _js_str(email.get("body", "(body not found)"))
        iset = email.get("instruction_set_id", "")
        difficulty = email.get("difficulty", "")
        planted = email.get("planted_violations", [])
        planted_str = ", ".join(planted) if planted else "none"

        # Email header row
        rows_html.append(
            f'<tr class="email-header" data-eid="{_h(eid)}">'
            f'<td colspan="5" class="email-hdr-cell">'
            f'<span class="eid">{_h(eid)}</span> &nbsp;'
            f'<span class="iset">{_h(iset)}</span> &nbsp;'
            f'<span class="diff diff-{_h(difficulty)}">{_h(difficulty)}</span>'
            f'<span class="planted">planted: {_h(planted_str)}</span>'
            f'<button class="toggle-body" onclick="toggleBody(\'{_h(eid)}\')">'
            f'Show / Hide body</button>'
            f'</td></tr>'
            f'<tr class="body-row" id="body-{_h(eid)}" style="display:none">'
            f'<td colspan="5"><pre class="email-body" id="pre-{_h(eid)}"></pre></td>'
            f'</tr>'
        )

        for lbl in by_email[eid]:
            rule_id = lbl["rule_id"]
            violated = lbl.get("violated", False)
            reason = lbl.get("reason", "")
            kind = lbl.get("kind", "")
            confidence = lbl.get("confidence", "high")
            low = confidence == "low"
            verdict_cls = "verdict-violated" if violated else "verdict-ok"
            row_cls = "row-low" if low else ""
            verdict_label = "VIOLATED" if violated else "OK"

            rows_html.append(
                f'<tr class="rule-row {row_cls}" id="row-{row_idx}" data-idx="{row_idx}"'
                f' data-eid="{_h(eid)}" data-body="{body_escaped}">'
                f'<td class="td-num">{row_idx + 1}</td>'
                f'<td class="td-rule"><span class="rule-id">{_h(rule_id)}</span>'
                f'<br><span class="rule-kind">{_h(kind)}</span></td>'
                f'<td class="td-verdict"><span class="{verdict_cls}">{verdict_label}</span>'
                + ('<br><span class="low-conf">low confidence</span>' if low else '')
                + '</td>'
                f'<td class="td-reason">{_h(reason)}</td>'
                f'<td class="td-action">'
                f'<button class="btn-confirm" onclick="setVerdict({row_idx},false)">✔ Confirm</button>'
                f'<button class="btn-overturn" onclick="setVerdict({row_idx},true)">✘ Overturn</button>'
                f'<input type="text" class="reason-input" id="reason-{row_idx}"'
                f' placeholder="Overturn reason (required if overturning)" />'
                f'</td>'
                f'</tr>'
            )
            row_idx += 1

    rows_str = "\n".join(rows_html)

    # Embed the full label list as JSON for JS state.
    labels_json = json.dumps(labels, ensure_ascii=False)
    provenance_json = json.dumps(provenance, ensure_ascii=False)
    emails_json_for_js = json.dumps(
        {eid: emails.get(eid, {}).get("body", "") for eid in email_ids},
        ensure_ascii=False,
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Label Review Sheet</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,sans-serif;font-size:13px;background:#f5f5f5;color:#1a1a1a}}
#header{{position:sticky;top:0;background:#1a1a2e;color:#eee;padding:8px 16px;
  display:flex;align-items:center;gap:16px;z-index:100}}
#header h1{{font-size:15px;font-weight:600}}
#progress{{font-size:13px;opacity:.85}}
#export-btn{{margin-left:auto;background:#4caf50;color:#fff;border:none;
  padding:6px 14px;border-radius:4px;cursor:pointer;font-size:13px}}
#export-btn:hover{{background:#388e3c}}
#help{{font-size:11px;opacity:.7;white-space:nowrap}}
table{{width:100%;border-collapse:collapse;background:#fff}}
th{{background:#e8eaf6;padding:7px 8px;text-align:left;font-size:12px;
  position:sticky;top:41px;z-index:90}}
td{{padding:6px 8px;vertical-align:top;border-bottom:1px solid #e0e0e0}}
.email-hdr-cell{{background:#f0f4ff;font-weight:600;padding:10px 8px;
  border-top:3px solid #3f51b5}}
.eid{{color:#3f51b5;font-size:13px}}
.iset{{color:#555;font-size:12px}}
.diff{{padding:2px 6px;border-radius:10px;font-size:11px;font-weight:600}}
.diff-clean{{background:#e8f5e9;color:#2e7d32}}
.diff-single{{background:#fff8e1;color:#f57f17}}
.diff-multiple{{background:#fce4ec;color:#c62828}}
.diff-borderline{{background:#ede7f6;color:#4527a0}}
.planted{{margin-left:12px;font-size:11px;color:#666;font-weight:normal}}
.toggle-body{{margin-left:12px;font-size:11px;padding:2px 8px;cursor:pointer;
  background:#fff;border:1px solid #aaa;border-radius:3px}}
.body-row td{{padding:0}}
.email-body{{white-space:pre-wrap;font-size:12px;line-height:1.5;
  padding:10px 12px;background:#fafafa;border-left:4px solid #3f51b5;
  max-height:280px;overflow-y:auto}}
.rule-id{{font-family:monospace;font-size:11px;color:#333}}
.rule-kind{{font-size:10px;color:#888;margin-top:2px}}
.verdict-violated{{color:#c62828;font-weight:600}}
.verdict-ok{{color:#2e7d32;font-weight:600}}
.low-conf{{font-size:10px;color:#9c27b0}}
.td-num{{width:42px;color:#999;text-align:right}}
.td-rule{{width:220px}}
.td-verdict{{width:110px}}
.td-reason{{color:#555;font-size:12px}}
.td-action{{width:280px;white-space:nowrap}}
.btn-confirm{{background:#e8f5e9;border:1px solid #81c784;padding:3px 8px;
  border-radius:3px;cursor:pointer;font-size:12px;margin-right:4px}}
.btn-overturn{{background:#fce4ec;border:1px solid #ef9a9a;padding:3px 8px;
  border-radius:3px;cursor:pointer;font-size:12px;margin-right:4px}}
.reason-input{{width:100%;margin-top:4px;padding:3px 6px;font-size:12px;
  border:1px solid #ddd;border-radius:3px;display:none}}
.btn-confirm:hover{{background:#c8e6c9}}.btn-overturn:hover{{background:#ffcdd2}}
tr.confirmed td{{background:#f9fff9}}
tr.overturned td{{background:#fff5f5}}
tr.row-current td{{outline:2px solid #3f51b5;outline-offset:-1px}}
tr.row-low td{{background:#f3e5f5}}
</style>
</head>
<body>
<div id="header">
  <h1>Label Review Sheet</h1>
  <span id="progress">0 / {total_rows} reviewed</span>
  <span id="help">J/K move · Y confirm · N overturn · E reason</span>
  <button id="export-btn" onclick="exportJSON()">Export labels_ground_truth.json</button>
</div>
<table>
<thead>
<tr>
  <th>#</th><th>Rule ID</th><th>Draft verdict</th>
  <th>Draft reason</th><th>Action</th>
</tr>
</thead>
<tbody id="tbody">
{rows_str}
</tbody>
</table>
<script>
// ---------- Data ----------
const LABELS = {labels_json};
const PROVENANCE = {provenance_json};
const BODIES = {emails_json_for_js};
const TOTAL = {total_rows};

// State: parallel arrays indexed by row (rule rows only, not email headers).
// verdict[i]=true means overturned; false means confirmed; null means untouched.
const overturned = new Array(TOTAL).fill(null);
const reasons = new Array(TOTAL).fill('');
let current = 0; // current rule-row index

// Inject email bodies into pre elements (avoids HTML-escaping issues).
Object.entries(BODIES).forEach(([eid, body]) => {{
  const el = document.getElementById('pre-' + eid);
  if (el) el.textContent = body;
}});

function rowEl(i) {{ return document.getElementById('row-' + i); }}

function setVerdict(i, isOverturned) {{
  overturned[i] = isOverturned;
  const r = rowEl(i);
  if (!r) return;
  r.classList.toggle('confirmed', !isOverturned);
  r.classList.toggle('overturned', isOverturned);
  const inp = document.getElementById('reason-' + i);
  if (inp) inp.style.display = isOverturned ? 'block' : 'none';
  updateProgress();
  if (!isOverturned) moveTo(i + 1);
}}

function updateProgress() {{
  const done = overturned.filter(v => v !== null).length;
  document.getElementById('progress').textContent = done + ' / ' + TOTAL + ' reviewed';
}}

function moveTo(i) {{
  if (i < 0 || i >= TOTAL) return;
  const prev = rowEl(current);
  if (prev) prev.classList.remove('row-current');
  current = i;
  const cur = rowEl(current);
  if (cur) {{
    cur.classList.add('row-current');
    cur.scrollIntoView({{ block: 'nearest' }});
  }}
}}

document.addEventListener('keydown', (e) => {{
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'j' || e.key === 'ArrowDown') {{ e.preventDefault(); moveTo(current + 1); }}
  else if (e.key === 'k' || e.key === 'ArrowUp') {{ e.preventDefault(); moveTo(current - 1); }}
  else if (e.key === 'y' || e.key === 'Y') {{ setVerdict(current, false); }}
  else if (e.key === 'n' || e.key === 'N') {{ setVerdict(current, true); }}
  else if (e.key === 'e' || e.key === 'E') {{
    const inp = document.getElementById('reason-' + current);
    if (inp) {{ inp.style.display = 'block'; inp.focus(); }}
  }}
}});

function toggleBody(eid) {{
  const row = document.getElementById('body-' + eid);
  if (row) row.style.display = (row.style.display === 'none') ? '' : 'none';
}}

function exportJSON() {{
  const out_labels = LABELS.map((lbl, i) => {{
    const r = document.getElementById('reason-' + i);
    const oReason = r ? r.value.trim() : '';
    return Object.assign({{}}, lbl, {{
      reviewed: overturned[i] !== null,
      overturned: overturned[i] === true,
      reason: overturned[i] === true && oReason ? oReason : lbl.reason,
    }});
  }});
  const payload = {{
    version: 1,
    provenance: Object.assign({{}}, PROVENANCE, {{
      kind: 'human_reviewed',
      reviewed_at: new Date().toISOString(),
    }}),
    labels: out_labels,
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'labels_ground_truth.json';
  a.click();
  URL.revokeObjectURL(a.href);
}}

// Start at row 0
moveTo(0);
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _h(s: str) -> str:
    """Minimal HTML escaping for attribute and text values."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _js_str(s: str) -> str:
    """Encode a string for use as an HTML attribute value (the JS reads it via dataset)."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
        .replace("\n", "&#10;")
        .replace("\r", "")
    )
