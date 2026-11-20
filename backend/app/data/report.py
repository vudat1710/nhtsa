"""A static, self-contained HTML walkthrough of the data, for showing someone how it flows through the system:

    NHTSA flat files (data/raw) -> ingest.py -> nhtsa.db -> intake -> evidence -> judge (AI) -> verify -> decide
    -> stored run (app.db) -> analyst suggestion

Uses only local files and the stored AI runs of the demo tickets (no model, no network). Run after ingest + reset:
    uv run python -m app.data.report            # -> docs/data_report.html
"""
import argparse
import json
import sqlite3
import time
import zipfile
from collections import defaultdict
from html import escape
from pathlib import Path

from app.ai.prompt import case_message
from app.api import deps
from app.api.workspace import related_for
from app.config import get_settings
from app.data.ingest import CMPL, COMPLAINTS_FROM, RAW, RCL, ROOT, fix_text
from app.models import Result
from app.pipeline.decide import baseline
from app.pipeline.intake import MASK
from app.workspace.suggest import suggest

OUT = ROOT / "docs" / "data_report.html"
DEMO = ROOT / "data" / "eval" / "demo.json"
CELL_MAX = 220


class H(str):
    """Already-rendered HTML: not escaped again."""


def h(x) -> str:
    if isinstance(x, H):
        return x
    if x is None:
        return '<span class="dim">null</span>'
    s = str(x)
    return escape(s if len(s) <= CELL_MAX else s[:CELL_MAX] + "…")


def table(headers: list[str], rows: list[list], cls: str = "") -> H:
    head = "".join(f"<th>{escape(x)}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{h(c)}</td>" for c in r) + "</tr>" for r in rows)
    return H(f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def kv(pairs: list[tuple[str, object]]) -> H:
    return H('<table class="kv">' + "".join(f"<tr><th>{escape(k)}</th><td>{h(v)}</td></tr>" for k, v in pairs)
             + "</table>")


def pre(text: str, title: str | None = None, open_: bool = False) -> H:
    block = f"<pre>{escape(text)}</pre>"
    if title is None:
        return H(block)
    return H(f"<details{' open' if open_ else ''}><summary>{escape(title)}</summary>{block}</details>")


def badge(text: str, kind: str = "") -> H:
    return H(f'<span class="badge {kind}">{escape(text)}</span>')


def mark(text: str, needles: list[str]) -> H:
    """Escape text and highlight the masked recall numbers and every verified quote found in it."""
    out = escape(text)
    for n in sorted({x for x in needles if x}, key=len, reverse=True):
        e = escape(n)
        if e in out:
            out = out.replace(e, f"<mark>{e}</mark>")
    return H(out)


def mb(path: Path) -> str:
    return f"{path.stat().st_size / 1e6:,.1f} MB"


# ---------------------------------------------------------------------------------------------------------- raw files

def scan(zip_name: str, key_col: int, keys: set[str], repair_example: bool = False) -> tuple[dict, dict | None]:
    """Raw rows (as published, split on tabs) whose key column is in keys; optionally the first complaint since
    COMPLAINTS_FROM whose text needed the UTF-8 repair."""
    found: dict[str, list[list[str]]] = defaultdict(list)
    repair = None
    needles = [k.encode() for k in keys]
    since = COMPLAINTS_FROM.replace("-", "")
    with zipfile.ZipFile(RAW / zip_name) as z, z.open(z.namelist()[0]) as fh:
        for line in fh:
            hit = any(n in line for n in needles)
            want_repair = repair_example and repair is None and b"\xe2\x80" in line  # UTF-8 punctuation bytes
            if not hit and not want_repair:
                continue
            parts = line.rstrip(b"\r\n").decode("latin-1").split("\t")
            if hit and len(parts) > key_col and parts[key_col] in keys:
                found[parts[key_col]].append(parts)
            if want_repair and len(parts) >= len(CMPL):
                row = dict(zip(CMPL, parts, strict=False))
                if row["LDATE"] >= since and fix_text(row["CDESCR"]) != row["CDESCR"]:
                    repair = row
    return found, repair


def repair_snippet(text: str, width: int = 70) -> tuple[str, str]:
    i = next((k for k, ch in enumerate(text) if ord(ch) > 127), 0)
    raw = text[max(0, i - width):i + width]
    return raw, fix_text(raw)


# -------------------------------------------------------------------------------------------------------- sections

def section_flow() -> H:
    steps = [("NHTSA flat files", "data/raw/*.zip", "raw"), ("ingest.py", "clean + split", "code"),
             ("nhtsa.db", "SQLite, read-only", "db"), ("intake", "mask + flags", "code"),
             ("evidence", "SQL, as of date", "code"), ("judge", "AI agent", "ai"), ("verify", "quotes, ids", "code"),
             ("decide", "rules", "code"), ("app.db", "stored run", "db"), ("suggestion", "analyst view", "ui")]
    boxes = '<span class="arrow">→</span>'.join(
        f'<div class="box {k}"><b>{escape(a)}</b><small>{escape(b)}</small></div>' for a, b, k in steps)
    return H(f"""<section><h2>The path, end to end</h2><div class="flow">{boxes}</div>
<p>One complaint flows left to right. Only <b>judge</b> calls a model; everything else is code, so every number and
every recall shown comes from the data, not from the AI. The AI proposes; <b>verify</b> checks every quote word for
word and <b>decide</b> sets the outcome by rules. If the answer fails verification twice, decide falls back to a
labelled rules-only answer.</p>
<p class="legend">{badge('code', 'code')} {badge('database', 'db')} {badge('AI', 'ai')} {badge('raw file', 'raw')}
{badge('UI', 'ui')}</p></section>""")


def section_raw(main: Result, cmpl_rows: dict, rcl_rows: dict, repair: dict | None) -> H:
    files = [("FLAT_CMPL.zip", "Consumer complaints since 1995 (one row per complaint × component)", "CMPL.txt"),
             ("FLAT_RCL_POST_2010.zip", "Recall campaigns since 2010 (one row per campaign × vehicle × component)",
              "RCL.txt"),
             ("FLAT_INV.zip", "Defect investigations (one row per investigation × vehicle)", "INV.txt")]
    ft = table(["File", "Size", "What it is", "Format"],
               [[f, mb(RAW / f), what, H(f"tab-delimited, no header, no quoting; columns in <code>{doc}</code>")]
                for f, what, doc in files if (RAW / f).exists()])
    c = main.complaint
    rows = cmpl_rows.get(str(c.odino), [])
    raw_c = ""
    if rows:
        named = [dict(zip(CMPL, r, strict=False)) for r in rows]
        raw_c = (f"<h3>One raw complaint: ODINO {c.odino}</h3><p>{len(rows)} raw row(s) for this complaint (one per "
                 f"component the owner picked). The first {len(CMPL)} columns are read; later ones are not used:</p>"
                 + table(["Column"] + [f"row {i + 1}" for i in range(len(rows))],
                         [[k] + [n[k] for n in named] for k in CMPL], "raw"))
    raw_r = ""
    if main.decision.campno and rcl_rows.get(main.decision.campno):
        rr = rcl_rows[main.decision.campno]
        raw_r = (f"<h3>One raw recall: CAMPNO {main.decision.campno}</h3><p>{len(rr)} raw rows (one per covered make × "
                 "model × year × component). Row 1:</p>" + kv(list(zip(RCL, rr[0], strict=False))))
    raw_e = ""
    if repair:
        before, after = repair_snippet(repair["CDESCR"])
        raw_e = (f"<h3>Encoding problem in the raw text (ODINO {repair['ODINO']})</h3><p>UTF-8 bytes published as "
                 "Latin-1. Quotes must match word for word later, so ingest repairs this:</p>"
                 + kv([("as published", before), ("after fix_text()", after)]))
    return H(f"<section><h2>1 · Raw NHTSA files</h2>{ft}{raw_c}{raw_r}{raw_e}</section>")


def section_ingest() -> H:
    rows = [
        ["Keep complaints received ≥ " + COMPLAINTS_FROM, "LDATE", "similar-complaint counts start here"],
        ["One complaint row + one row per component", "ODINO repeated per COMPDESC",
         "complaints + complaint_components"],
        ["Top-level component", "AIR BAGS:FRONTAL", "component = AIR BAGS:FRONTAL, comp = AIR BAGS"],
        ["Dates to ISO", "20240318", "2024-03-18 (compares correctly as text)"],
        ["Flags to integers", "CRASH = 'Y'", "crash = 1"],
        ["Hotline transcripts marked", "CDESCR starts with 'TL*'", "source = 'hotline' (else 'owner')"],
        ["Text repair only", "â€œInsufficientâ€", "“Insufficient”; nothing else in the text is edited"],
        ["One recall row + one row per covered vehicle", "CAMPNO repeated", "recalls + recall_vehicles"],
        ["Full-text index", "complaints.text", "complaints_fts (SQLite FTS5) for the AI's search tool"],
    ]
    return H("<section><h2>2 · Preprocessing (<code>python -m app.data.ingest</code>)</h2>"
             "<p>Built into a temporary file and swapped in at the end, so a failed build never leaves a half "
             "database. Text is otherwise kept exactly as published.</p>"
             + table(["Step", "Raw", "In nhtsa.db"], rows) + "</section>")


def section_db(con: sqlite3.Connection, main: Result) -> H:
    c = main.complaint
    counts = []
    for t in ["complaints", "complaint_components", "recalls", "recall_vehicles", "investigations",
              "investigation_vehicles"]:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        counts.append([t, f"{n:,}", ", ".join(cols)])
    span = con.execute("SELECT min(received), max(received) FROM complaints").fetchone()
    rspan = con.execute("SELECT min(filed), max(filed) FROM recalls").fetchone()

    def sample(sql: str, args: tuple) -> H:
        cur = con.execute(sql, args)
        return table([d[0] for d in cur.description], [list(r) for r in cur.fetchall()])

    camp = main.decision.campno
    parts = [
        f"<h3>complaints (ODINO {c.odino})</h3>", sample("SELECT * FROM complaints WHERE odino = ?", (c.odino,)),
        "<h3>complaint_components</h3>", sample("SELECT * FROM complaint_components WHERE odino = ?", (c.odino,)),
    ]
    if camp:
        parts += [f"<h3>recalls ({camp})</h3>", sample("SELECT * FROM recalls WHERE campno = ?", (camp,)),
                  f"<h3>recall_vehicles ({camp}, {c.make} {c.model} only)</h3>",
                  sample("SELECT * FROM recall_vehicles WHERE campno = ? AND make = ? AND model = ? ORDER BY year",
                         (camp, c.make, c.model))]
    parts += [f"<h3>investigations ({c.make} {c.model})</h3>",
              sample("""SELECT DISTINCT i.action, i.opened, i.closed, i.campno, i.subject FROM investigations i
                        JOIN investigation_vehicles v USING (action) WHERE v.make = ? AND v.model = ?
                        ORDER BY i.opened DESC LIMIT 3""", (c.make, c.model))]
    return H(f"""<section><h2>3 · The database (<code>data/nhtsa.db</code>, {mb(get_settings().db_path)})</h2>
<p>Complaints received {span[0]} to {span[1]}; recalls filed {rspan[0]} to {rspan[1]}. The app opens it read-only.
Analyst work and AI runs live in a separate file (<code>data/app.db</code>).</p>
{table(["Table", "Rows", "Columns"], counts)}
<p>The same records, now in the database, for the demo complaint below:</p>{"".join(parts)}</section>""")


def section_case(case: dict, r: Result) -> H:
    c, it, ev, j, d = r.complaint, r.intake, r.evidence, r.judgment, r.decision
    quotes = [ch.complaint_quote for ch in j.checks] if j else []
    s = suggest(r, deps.store().tickets, related_for(r))
    base = baseline(it, ev, [], "rules")

    complaint = kv([("odino", c.odino), ("vehicle", f"{c.year} {c.make} {c.model}"), ("received (as_of)", c.received),
                    ("crash / fire / injured", f"{c.crash} / {c.fire} / {c.injured}"),
                    ("components (as the owner chose)", ", ".join(c.components) or "—"),
                    ("comps (top level, used for matching)", ", ".join(c.comps) or "—")])
    intake = kv([("flags", H(" ".join(badge(f) for f in it.flags) or '<span class="dim">none</span>')),
                 ("recall numbers masked", it.masked),
                 ("text the AI sees", H(f'<div class="text">{mark(it.text, [MASK, *quotes])}</div>'))])

    recalls = table(
        ["campno", "filed", "comps", "same comp.", "replaced by", "complaints since", "covers years", "defect"],
        [[x.campno, x.filed, ", ".join(x.comps), "✔" if x.same_component else "", x.replaced_by or "",
          x.complaints_since if x.same_component else "", ", ".join(x.model_years), x.defect] for x in ev.recalls])
    st = ev.stats
    evidence = H(f"<p>{len(ev.recalls)} candidate recall(s) shown of {ev.recalls_total} covering this exact vehicle "
                 f"before {c.received} (same component first, then newest).</p>{recalls}"
                 + kv([("earlier complaints, same vehicle + component", st.total),
                       ("… with crash / fire / injury", f"{st.crash} / {st.fire} / {st.injury}"),
                       ("… in the last 12 months", st.last_12_months), ("first / last", f"{st.first} / {st.last}"),
                       ("investigations on this vehicle", len(ev.investigations))]))

    if j:
        searches = table(["tool", "query (the AI's own words)", "complaint ids returned", "ms"],
                         [[t.get("tool"), json.dumps(t.get("arguments"), ensure_ascii=False),
                           ", ".join(map(str, t.get("results") or [])), t.get("ms")] for t in r.tool_calls])
        checks = table(["recall", "verdict", "owner wrote", "recall says", "reason"],
                       [[ch.campno, H(badge(ch.verdict, ch.verdict)), ch.complaint_quote, ch.recall_quote, ch.reason]
                        for ch in j.checks])
        similar = table(["earlier complaint", "quote"], [[x.odino, x.quote] for x in j.similar]) if j.similar else ""
        judge = H(pre(case_message(c, it, ev), "Exactly what the AI received (built by code)")
                  + (f"<h4>Searches the agent chose to run</h4>{searches}" if r.tool_calls else "")
                  + f"<h4>Per-recall checks</h4>{checks}"
                  + (f"<h4>Earlier owners describing the same failure</h4>{similar}" if similar else "")
                  + kv([("proposed outcome", j.proposed), ("summary", j.summary),
                        ("questions for the owner", " · ".join(j.questions) or "—"), ("model", r.model)]))
    else:
        judge = H('<p class="dim">No AI judgment for this run (rules only).</p>')

    verify = table(["attempt", "error", "issues found by the verifier", "tokens in / out"],
                   [[a.n, a.error or "", "; ".join(f"{i.code}: {i.message}" for i in a.issues) or "none ✔",
                     f"{a.input_tokens:,} / {a.output_tokens:,}"] for a in r.attempts])

    decide = kv([("outcome", H(badge(d.outcome, d.outcome))), ("confidence", d.confidence),
                 ("matched recall", d.campno or "—"), ("escalate", "yes" if d.escalate else "no"),
                 ("source", d.source), ("flags", ", ".join(d.flags) or "—"),
                 ("reasons", H("<ul>" + "".join(f"<li>{escape(x)}</li>" for x in d.reasons) + "</ul>")),
                 ("for contrast: rules-only baseline",
                  f"{base.outcome}" + (f" ({base.campno})" if base.campno else "") + f" — {base.reasons[0]}")])

    stored = kv([("app.db results.id", r.id), ("created_at", r.created_at), ("steps that ran", " → ".join(r.steps)),
                 ("latency", f"{r.latency_ms:,} ms")])

    actions = "".join(f"<li>{'<b>' if a.primary else ''}{escape(a.label)}{'</b> (suggested)' if a.primary else ''}"
                      "</li>" for a in s.actions)
    why = "".join(f"<li>{escape(w.text)}</li>" for w in s.why)
    suggestion = H(f'<div class="card"><div class="headline">{escape(s.headline)}</div>'
                   f"<p>{escape(s.summary)}</p><b>Why</b><ul>{why}</ul><b>Actions</b><ul>{actions}</ul></div>")

    steps = [("a", "Complaint", "nhtsa.db → Complaint", complaint),
             ("b", "Intake", "code: mask recall numbers, flag what is missing", intake),
             ("c", "Evidence", "code: SQL, only records dated before the complaint", evidence),
             ("d", "Judge", "AI agent: compares the complaint with each candidate recall", judge),
             ("e", "Verify", "code: recall ids exist, quotes copied exactly, no invented numbers", verify),
             ("f", "Decide", "code: rules turn verified checks into the outcome", decide),
             ("g", "Stored run", "app.db: the whole Result as JSON, the audit record", stored),
             ("h", "What the analyst sees", "workspace: suggestion built from the stored run", suggestion)]
    body = "".join(f'<div class="step"><h3><span class="n">{n}</span> {escape(t)} <small>{escape(sub)}</small></h3>'
                   f"{content}</div>" for n, t, sub, content in steps)
    title = f"{case['id']} · {c.year} {c.make} {c.model} — {case['title']}"
    hindsight = f"<p class='dim'><b>Hindsight (never shown to the system):</b> {escape(case['next'])}</p>" \
        if case.get("next") else ""
    return H(f"""<details class="case"{' open' if case['id'] == 'D1' else ''}><summary>{escape(title)}
{badge(d.outcome, d.outcome)}</summary><p>{escape(case['story'])}</p>{hindsight}{body}</details>""")


CSS = """
body{font:14px/1.5 system-ui,Segoe UI,sans-serif;margin:0;color:#1d2433;background:#f6f7f9}
main{max-width:1200px;margin:0 auto;padding:24px}
h1{margin:0 0 4px}h2{border-bottom:2px solid #dde1e7;padding-bottom:4px;margin-top:36px}
section,.case{background:#fff;border:1px solid #e2e5ea;border-radius:8px;padding:8px 20px 16px;margin:16px 0}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}
th,td{border:1px solid #e2e5ea;padding:4px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
section,.case{overflow-x:auto}
thead th{background:#f0f2f5}table.kv th{width:260px;background:#fafbfc;font-weight:600}
table.raw td:first-child{font-family:Consolas,monospace;white-space:nowrap}
pre{background:#0f172a;color:#e2e8f0;padding:12px;border-radius:6px;overflow:auto;max-height:420px;font-size:12px}
code{background:#eef1f5;padding:1px 4px;border-radius:3px}
.dim{color:#6b7280}mark{background:#fde68a;padding:0 1px}
.text{white-space:pre-wrap;max-height:260px;overflow:auto}
.flow{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:12px 0}
.box{border-radius:6px;padding:6px 10px;display:flex;flex-direction:column;min-width:86px;text-align:center}
.box small{color:#4b5563}.arrow{color:#9ca3af;font-size:18px}
.code{background:#e0ecff}.db{background:#e6f6ea}.ai{background:#fbe4f0}.raw{background:#f3f4f6}.ui{background:#fff4d6}
.badge{display:inline-block;border-radius:10px;padding:0 8px;font-size:12px;background:#eef1f5;margin-right:4px}
.badge.known_recall,.badge.same{background:#d1fae5}.badge.possible_new{background:#fde2e2}
.badge.related_different,.badge.different{background:#ffedd5}.badge.needs_info,.badge.partial{background:#e0e7ff}
.case>summary{font-size:16px;font-weight:600;cursor:pointer;padding:8px 0}
.step{border-left:3px solid #c7d2fe;padding-left:14px;margin:18px 0}
.step h3{margin:6px 0}.step h3 small{font-weight:400;color:#6b7280;font-size:13px}
.n{display:inline-block;width:22px;height:22px;border-radius:11px;background:#4f46e5;color:#fff;text-align:center;
font-size:13px;line-height:22px}
.card{border:1px solid #e2e5ea;border-radius:6px;padding:10px 14px;background:#fffdf5}
.headline{font-weight:600;font-size:15px}details>summary{cursor:pointer}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-raw", action="store_true", help="skip scanning the raw zip files (the slow part)")
    args = ap.parse_args()
    t = time.time()

    cases = json.loads(DEMO.read_text(encoding="utf-8"))["cases"]
    latest = deps.store().latest("queue")
    missing = [x["id"] for x in cases if x["odino"] not in latest]
    if missing:
        raise SystemExit(f"no stored run for {missing}: run `python -m app.store.reset` first")
    runs = [(x, latest[x["odino"]]) for x in cases]
    main_run = runs[0][1]

    cmpl_rows, rcl_rows, repair = {}, {}, None
    if not args.no_raw:
        print("scanning raw files (up to a minute)...")
        cmpl_rows, repair = scan("FLAT_CMPL.zip", CMPL.index("ODINO"), {str(main_run.complaint.odino)}, True)
        if main_run.decision.campno:
            rcl_rows, _ = scan("FLAT_RCL_POST_2010.zip", RCL.index("CAMPNO"), {main_run.decision.campno})

    con = deps.con()
    body = [section_flow(),
            section_raw(main_run, cmpl_rows, rcl_rows, repair) if not args.no_raw else "",
            section_ingest(), section_db(con, main_run),
            H("<section><h2>4 · One complaint through the pipeline</h2><p>Real complaints from the demo inbox, with "
              "their stored AI runs. Each step shows its actual input/output. Highlighted in the text: "
              f"<mark>{escape(MASK)}</mark> and the exact words the AI quoted (verified).</p>"
              + "".join(section_case(x, r) for x, r in runs) + "</section>")]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Recall Match: the data</title>
<style>{CSS}</style></head><body><main><h1>Recall Match: how the data flows</h1>
<p class="dim">Generated by <code>python -m app.data.report</code> from data/raw, data/nhtsa.db and the stored runs in
data/app.db. Static snapshot: no model or server needed to view it.</p>{"".join(body)}</main></body></html>"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e3:,.0f} KB) in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
