"""A static, self-contained HTML walkthrough of the data, for showing someone how it flows through the system:

    NHTSA flat files (data/raw) -> ingest.py -> nhtsa.db -> intake -> evidence -> judge (AI) -> verify -> decide
    -> stored run (app.db) -> analyst suggestion

Uses only local files and the stored AI runs of the demo tickets (no model). The data-model diagrams come from
docs/DATA_MODEL.md and are drawn by mermaid, loaded from a CDN (offline they show as text). Run after ingest + reset:
    uv run python -m app.data.report            # -> docs/data_report.html
"""
import argparse
import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from html import escape
from pathlib import Path

from app.ai.prompt import case_message
from app.api import deps
from app.api.workspace import related_for
from app.config import get_settings
from app.data import queries
from app.data.ingest import CMPL, CMPL_USED, COMPLAINTS_FROM, RAW, RCL, ROOT, fix_text
from app.models import Result
from app.pipeline.decide import baseline
from app.pipeline.intake import MASK
from app.store.results import Store
from app.workspace.actions import ActionRequest, apply
from app.workspace.suggest import suggest

OUT = ROOT / "docs" / "data_report.html"
DEMO = ROOT / "data" / "eval" / "demo.json"
DATA_MODEL = ROOT / "docs" / "DATA_MODEL.md"
WORKSPACE_TABLES = ["results", "tickets", "issues", "issue_complaints", "actions", "questions"]
CELL_MAX = 220


class H(str):
    """Already-rendered HTML: not escaped again."""


def h(x) -> str:
    """One value as HTML: escaped and cut to CELL_MAX characters; None shows as a dim 'null'; H passes through."""
    if isinstance(x, H):
        return x
    if x is None:
        return '<span class="dim">null</span>'
    text = str(x)
    if len(text) > CELL_MAX:
        text = text[:CELL_MAX] + "…"
    return escape(text)


def table(headers: list[str], rows: list[list], cls: str = "") -> H:
    """An HTML table; every cell goes through h()."""
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{h(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "".join(body_rows)
    return H(f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def kv(pairs: list[tuple[str, object]]) -> H:
    """A two-column key/value table; values go through h()."""
    rows = "".join(f"<tr><th>{escape(key)}</th><td>{h(value)}</td></tr>" for key, value in pairs)
    return H(f'<table class="kv">{rows}</table>')


def pre(text: str, title: str | None = None, open_: bool = False) -> H:
    """Preformatted text; with a title it goes inside a collapsible <details> block."""
    block = f"<pre>{escape(text)}</pre>"
    if title is None:
        return H(block)
    open_attr = " open" if open_ else ""
    return H(f"<details{open_attr}><summary>{escape(title)}</summary>{block}</details>")


def badge(text: str, kind: str = "") -> H:
    return H(f'<span class="badge {kind}">{escape(text)}</span>')


def mark(text: str, needles: list[str]) -> H:
    """Escape text and highlight the masked recall numbers and every verified quote found in it."""
    out = escape(text)
    non_empty = {needle for needle in needles if needle}
    # Longest first: once a short quote is wrapped in <mark>, a longer quote containing it would no longer match.
    for needle in sorted(non_empty, key=len, reverse=True):
        escaped = escape(needle)
        if escaped in out:
            out = out.replace(escaped, f"<mark>{escaped}</mark>")
    return H(out)


def mb(path: Path) -> str:
    return f"{path.stat().st_size / 1e6:,.1f} MB"


def diagram(name: str) -> H:
    """The mermaid diagram marked '%% diagram: <name>' in docs/DATA_MODEL.md (one source for the doc and the report)."""
    blocks = DATA_MODEL.read_text(encoding="utf-8").split("```mermaid")[1:]
    for block in blocks:
        source = block.split("```")[0].strip()
        if source.startswith(f"%% diagram: {name}"):
            return H(f'<pre class="mermaid">{escape(source)}</pre>')
    raise ValueError(f"no diagram named {name!r} in {DATA_MODEL}")


def sample(con: sqlite3.Connection, sql: str, args: tuple = ()) -> H:
    """A query's result as a table, headed by its column names."""
    cursor = con.execute(sql, args)
    headers = [column[0] for column in cursor.description]
    rows = [list(row) for row in cursor.fetchall()]
    if not rows:
        return H('<p class="dim">(no rows)</p>')
    return table(headers, rows)


def outline(value, name: str, open_: bool = False) -> H:
    """A JSON value as a collapsible tree: objects and lists open one level at a time, lists show their first 3 items,
    long text is cut."""
    open_attr = " open" if open_ else ""
    if isinstance(value, dict):
        items = "".join(f"<li>{outline(item, key)}</li>" for key, item in value.items())
        size = f"{{{len(value)} fields}}"
    elif isinstance(value, list) and value:
        items = "".join(f"<li>{outline(item, f'[{index}]')}</li>" for index, item in enumerate(value[:3]))
        if len(value) > 3:
            items += f'<li class="dim">… {len(value) - 3} more</li>'
        size = f"[{len(value)} items]"
    else:
        return H(f"<b>{escape(name)}</b>: {h(json.dumps(value, ensure_ascii=False))}")
    return H(f'<details{open_attr}><summary><b>{escape(name)}</b> <span class="dim">{size}</span></summary>'
             f'<ul class="outline">{items}</ul></details>')


# ---------------------------------------------------------------------------------------------------------- raw files

def scan(zip_name: str, key_col: int, keys: set[str], repair_example: bool = False) -> tuple[dict, dict | None]:
    """Raw rows (as published, split on tabs) whose key column is in keys, grouped by key; optionally also the first
    complaint since COMPLAINTS_FROM whose text needed the UTF-8 repair."""
    found: dict[str, list[list[str]]] = {}
    repair = None
    key_bytes = [key.encode() for key in keys]
    since = COMPLAINTS_FROM.replace("-", "")  # raw dates are YYYYMMDD
    with zipfile.ZipFile(RAW / zip_name) as archive, archive.open(archive.namelist()[0]) as fh:
        for line in fh:
            # Cheap byte tests first; only lines that may be wanted are decoded and split.
            has_key = any(key in line for key in key_bytes)
            still_looking_for_repair = repair_example and repair is None
            want_repair = still_looking_for_repair and b"\xe2\x80" in line  # UTF-8 punctuation bytes
            if not has_key and not want_repair:
                continue

            parts = line.rstrip(b"\r\n").decode("latin-1").split("\t")
            # The key bytes may appear anywhere in the line; keep it only if they are in the key column.
            if has_key and len(parts) > key_col and parts[key_col] in keys:
                key = parts[key_col]
                if key not in found:
                    found[key] = []
                found[key].append(parts)
            if want_repair and len(parts) >= len(CMPL):
                row = dict(zip(CMPL, parts, strict=False))
                if row["LDATE"] >= since and fix_text(row["CDESCR"]) != row["CDESCR"]:
                    repair = row
    return found, repair


def repair_snippet(text: str, width: int = 70) -> tuple[str, str]:
    """The text around its first non-ASCII character, as published and after fix_text()."""
    first_non_ascii = 0
    for index, char in enumerate(text):
        if ord(char) > 127:
            first_non_ascii = index
            break
    raw = text[max(0, first_non_ascii - width):first_non_ascii + width]
    return raw, fix_text(raw)


# -------------------------------------------------------------------------------------------------------- sections

def section_flow() -> H:
    steps = [  # (name, detail, CSS class for its colour)
        ("NHTSA flat files", "data/raw/*.zip", "raw"),
        ("ingest.py", "clean + split", "code"),
        ("nhtsa.db", "SQLite, read-only", "db"),
        ("intake", "mask + flags", "code"),
        ("evidence", "SQL, as of date", "code"),
        ("judge", "AI agent", "ai"),
        ("verify", "quotes, ids", "code"),
        ("decide", "rules", "code"),
        ("app.db", "stored run", "db"),
        ("suggestion", "analyst view", "ui"),
    ]
    boxes = []
    for name, detail, kind in steps:
        boxes.append(f'<div class="box {kind}"><b>{escape(name)}</b><small>{escape(detail)}</small></div>')
    flow = '<span class="arrow">→</span>'.join(boxes)
    return H(f"""<section><h2>The path, end to end</h2><div class="flow">{flow}</div>
<p>One complaint flows left to right. Only <b>judge</b> calls a model; everything else is code, so every number and
every recall shown comes from the data, not from the AI. The AI proposes; <b>verify</b> checks every quote word for
word and <b>decide</b> sets the outcome by rules. If the answer fails verification twice, decide falls back to a
labelled rules-only answer.</p>
<p class="legend">{badge('code', 'code')} {badge('database', 'db')} {badge('AI', 'ai')} {badge('raw file', 'raw')}
{badge('UI', 'ui')}</p></section>""")


def section_raw(main_run: Result, cmpl_rows: dict, rcl_rows: dict, repair: dict | None) -> H:
    # The three files: what they contain, and which NHTSA document describes their columns.
    files = [
        ("FLAT_CMPL.zip", "Consumer complaints since 1995 (one row per complaint × product × component)", "CMPL.txt"),
        ("FLAT_RCL_PRE_2010.zip", "Recall campaigns 1966-2009 (one row per campaign × vehicle × component)",
         "RCL.txt"),
        ("FLAT_RCL_POST_2010.zip", "Recall campaigns since 2010 (one row per campaign × vehicle × component)",
         "RCL.txt"),
        ("FLAT_INV.zip", "Defect investigations (one row per investigation × vehicle)", "INV.txt"),
    ]
    file_rows = []
    for name, what, doc in files:
        if not (RAW / name).exists():
            continue
        file_format = H(f"tab-delimited, no header, no quoting; fields described in <code>docs/nhtsa/{doc}</code>")
        file_rows.append([name, mb(RAW / name), what, file_format])
    files_table = table(["File", "Size", "What it is", "Format"], file_rows)

    # The main complaint as raw rows: one table column per raw row, one table row per field we read (not shown: the
    # fields we do not read, which include personal data such as dealer contact and the operator's name).
    complaint = main_run.complaint
    complaint_rows = cmpl_rows.get(str(complaint.odino), [])
    raw_complaint = ""
    if complaint_rows:
        named_rows = [dict(zip(CMPL, row, strict=False)) for row in complaint_rows]
        headers = ["Column"] + [f"row {i + 1}" for i in range(len(complaint_rows))]
        table_rows = []
        for column in CMPL_USED:
            values = [named[column] for named in named_rows]
            table_rows.append([column] + values)
        raw_complaint = (f"<h3>One raw complaint: ODINO {complaint.odino}</h3><p>{len(complaint_rows)} raw row(s) for "
                         "this complaint (one per product and component the owner picked). The "
                         f"{len(CMPL_USED)} of {len(CMPL)} documented fields that ingest reads:</p>"
                         + table(headers, table_rows, "raw"))

    # The matched recall: only its first raw row.
    campno = main_run.decision.campno
    raw_recall = ""
    if campno and rcl_rows.get(campno):
        recall_rows = rcl_rows[campno]
        raw_recall = (f"<h3>One raw recall: CAMPNO {campno}</h3><p>{len(recall_rows)} raw rows (one per covered "
                      "make × model × year × component). Row 1:</p>" + kv(list(zip(RCL, recall_rows[0], strict=False))))

    # An example of the encoding problem that ingest repairs.
    raw_encoding = ""
    if repair:
        before, after = repair_snippet(repair["CDESCR"])
        raw_encoding = (f"<h3>Encoding problem in the raw text (ODINO {repair['ODINO']})</h3><p>UTF-8 bytes published "
                        "as Latin-1. Quotes must match word for word later, so ingest repairs this:</p>"
                        + kv([("as published", before), ("after fix_text()", after)]))

    return H(f"<section><h2>1 · Raw NHTSA files</h2>{files_table}{raw_complaint}{raw_recall}{raw_encoding}</section>")


def section_ingest() -> H:
    rows = [
        ["Keep complaints received ≥ " + COMPLAINTS_FROM, "LDATE", "similar-complaint counts start here"],
        ["One complaint row + one row per component", "ODINO repeated per COMPDESC",
         "complaints + complaint_components"],
        ["Top-level component", "AIR BAGS:FRONTAL", "component = AIR BAGS:FRONTAL, comp = AIR BAGS"],
        ["Dates to ISO", "20240318", "2024-03-18 (compares correctly as text)"],
        ["Flags to integers", "CRASH = 'Y'", "crash = 1"],
        ["Who wrote it, from NHTSA's own field", "CMPL_TYPE = 'EVOQ' (hotline)", "cmpl_type kept; source = 'hotline' "
         "(else 'owner')"],
        ["One vehicle per complaint", "ODINO lines naming 2+ vehicles (1.1%)", "first vehicle and its components; "
         "vehicles = how many were named"],
        ["Text repair only", "â€œInsufficientâ€", "“Insufficient”; nothing else in the text is edited"],
        ["One recall row + one row per covered vehicle", "CAMPNO repeated", "recalls + recall_vehicles"],
        ["Full-text index", "complaints.text", "complaints_fts (SQLite FTS5) for the AI's search tool"],
    ]
    return H("<section><h2>2 · Preprocessing (<code>python -m app.data.ingest</code>)</h2>"
             "<p>Built into a temporary file and swapped in at the end, so a failed build never leaves a half "
             "database. Text is otherwise kept exactly as published.</p>"
             + table(["Step", "Raw", "In nhtsa.db"], rows) + "</section>")


def section_db(con: sqlite3.Connection, runs: list[tuple[dict, Result]]) -> H:
    main_run = runs[0][1]
    complaint = main_run.complaint

    # Every table: row count and columns.
    table_rows = []
    for table_name in ["complaints", "complaint_components", "recalls", "recall_vehicles", "investigations",
                       "investigation_vehicles"]:
        columns = [info[1] for info in con.execute(f"PRAGMA table_info({table_name})")]
        row_count = con.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
        table_rows.append([table_name, f"{row_count:,}", ", ".join(columns)])
    table_rows.append(["complaints_fts", "(index)", "text: FTS5 full-text index over complaints.text, rowid = odino"])
    tables_table = table(["Table", "Rows", "Columns"], table_rows)
    complaint_span = con.execute("SELECT min(received), max(received) FROM complaints").fetchone()
    recall_span = con.execute("SELECT min(filed), max(filed) FROM recalls").fetchone()

    # The main case's own records, as stored in the database: one sample from every table.
    odino = complaint.odino
    parts = [
        f"<h3>complaints (ODINO {odino})</h3>",
        sample(con, "SELECT * FROM complaints WHERE odino = ?", (odino,)),
        "<h3>complaint_components</h3>",
        sample(con, "SELECT * FROM complaint_components WHERE odino = ?", (odino,)),
    ]
    campno = main_run.decision.campno
    if campno:
        parts.append(f"<h3>recalls ({campno})</h3>")
        parts.append(sample(con, "SELECT * FROM recalls WHERE campno = ?", (campno,)))
        parts.append(f"<h3>recall_vehicles ({campno}, {complaint.make} {complaint.model} only)</h3>")
        parts.append(sample(con, "SELECT * FROM recall_vehicles WHERE campno = ? AND make = ? AND model = ? "
                                 "ORDER BY year", (campno, complaint.make, complaint.model)))
    parts.append(f"<h3>investigations ({complaint.make} {complaint.model})</h3>")
    parts.append(sample(con, """SELECT i.action, i.opened, i.closed, i.subject FROM investigations i
                                JOIN investigation_vehicles v USING (action) WHERE v.make = ? AND v.model = ?
                                GROUP BY i.action ORDER BY i.opened DESC LIMIT 3""", (complaint.make, complaint.model)))
    parts.append("<h3>investigation_vehicles (the newest of those investigations)</h3>")
    parts.append(sample(con, """SELECT * FROM investigation_vehicles WHERE action = (
                                  SELECT i.action FROM investigations i JOIN investigation_vehicles v USING (action)
                                  WHERE v.make = ? AND v.model = ? ORDER BY i.opened DESC LIMIT 1) LIMIT 6""",
                        (complaint.make, complaint.model)))
    parts.append(fts_sample(con, runs))
    samples = "".join(parts)

    joins = table(["Join", "How", "Used for"], [
        ["complaints → complaint_components", "odino", "the owner's components (comps = top level)"],
        ["recalls → recall_vehicles", "campno", "which make/model/year/component a recall covers"],
        ["complaints ⇢ recall_vehicles", "same make + model + year, recall filed before received",
         "candidate recalls (queries.recalls_for)"],
        ["complaints ⇢ complaints", "same make + model + year + comp, received before",
         "earlier-complaint counts, the agent's search"],
        ["investigation_vehicles ⇢ recalls", "campno on the vehicle's own line, when the investigation led to a "
         "recall", "context only"],
    ])
    db_size = mb(get_settings().db_path)
    date_ranges = (f"Complaints received {complaint_span[0]} to {complaint_span[1]}; "
                   f"recalls filed {recall_span[0]} to {recall_span[1]}.")
    return H(f"""<section><h2>3 · The database (<code>data/nhtsa.db</code>, {db_size})</h2>
<p>{date_ranges} The app opens it read-only.
Analyst work and AI runs live in a separate file (<code>data/app.db</code>, section 5).</p>
{diagram("nhtsa")}
<p>Solid lines are keys inside the file; dashed lines are joins made at query time. Every dashed join carries the
<b>as_of</b> rule: only records dated strictly before the complaint was received.</p>
{joins}{tables_table}
<p>One sample from every table: the records behind the demo complaint below.</p>{samples}</section>""")


def fts_sample(con: sqlite3.Connection, runs: list[tuple[dict, Result]]) -> H:
    """What the agent's search tool returned in a demo run: complaints_fts, as the agent uses it."""
    for _, run in runs:
        if not run.tool_calls:
            continue
        query = str(run.tool_calls[0].get("arguments", {}).get("query", ""))
        complaint = run.complaint
        vehicle = queries.Vehicle(complaint.make, complaint.model, complaint.year)
        hits = queries.search_complaints(con, vehicle, query, complaint.received, exclude=complaint.odino)
        rows = [[hit["odino"], hit["received"], hit["snippet"]] for hit in hits]
        return H(f"<h3>complaints_fts (the agent's search in complaint {complaint.odino}: “{escape(query)}”)</h3>"
                 f"<p class='dim'>Same vehicle, received before {complaint.received}, ranked by bm25; "
                 "[brackets] mark the matched words.</p>" + table(["odino", "received", "snippet"], rows))
    return H("")


def section_case(case: dict, run: Result) -> H:
    """One demo case through every pipeline step (a-h), each step showing its actual input/output."""
    complaint = run.complaint
    intake = run.intake
    evidence = run.evidence
    judgment = run.judgment
    decision = run.decision

    # a. Complaint
    complaint_html = kv([
        ("odino", complaint.odino),
        ("vehicle", f"{complaint.year} {complaint.make} {complaint.model}"),
        ("received (as_of)", complaint.received),
        ("crash / fire / injured", f"{complaint.crash} / {complaint.fire} / {complaint.injured}"),
        ("components (as the owner chose)", ", ".join(complaint.components) or "—"),
        ("comps (top level, used for matching)", ", ".join(complaint.comps) or "—"),
    ])

    # b. Intake. The text highlights the masked recall numbers and every quote the AI took from it.
    if judgment:
        quotes = [check.complaint_quote for check in judgment.checks]
    else:
        quotes = []
    flag_badges = " ".join(badge(flag) for flag in intake.flags) or '<span class="dim">none</span>'
    highlighted_text = mark(intake.text, [MASK, *quotes])
    intake_html = kv([
        ("flags", H(flag_badges)),
        ("recall numbers masked", intake.masked),
        ("text the AI sees", H(f'<div class="text">{highlighted_text}</div>')),
    ])

    # c. Evidence
    recall_rows = []
    for recall in evidence.recalls:
        same_component = ""
        complaints_since = ""
        if recall.same_component:
            same_component = "✔"
            complaints_since = recall.complaints_since
        recall_rows.append([recall.campno, recall.filed, ", ".join(recall.comps), same_component,
                            recall.replaced_by or "", complaints_since, ", ".join(recall.model_years), recall.defect])
    recalls_table = table(
        ["campno", "filed", "comps", "same comp.", "replaced by", "complaints since", "covers years", "defect"],
        recall_rows)
    stats = evidence.stats
    stats_table = kv([
        ("earlier complaints, same vehicle + component", stats.total),
        ("… with crash / fire / injury", f"{stats.crash} / {stats.fire} / {stats.injury}"),
        ("… in the last 12 months", stats.last_12_months),
        ("first / last", f"{stats.first} / {stats.last}"),
        ("investigations on this vehicle", len(evidence.investigations)),
    ])
    evidence_html = H(f"<p>{len(evidence.recalls)} candidate recall(s) shown of {evidence.recalls_total} covering "
                      f"this exact vehicle before {complaint.received} (same component first, then newest).</p>"
                      + recalls_table + stats_table)

    # d. Judge
    if judgment:
        judge_parts = [pre(case_message(complaint, intake, evidence), "Exactly what the AI received (built by code)")]

        if run.tool_calls:
            search_rows = []
            for call in run.tool_calls:
                query = json.dumps(call.get("arguments"), ensure_ascii=False)
                returned_ids = ", ".join(map(str, call.get("results") or []))
                search_rows.append([call.get("tool"), query, returned_ids, call.get("ms")])
            searches = table(["tool", "query (the AI's own words)", "complaint ids returned", "ms"], search_rows)
            judge_parts.append(f"<h4>Searches the agent chose to run</h4>{searches}")

        check_rows = []
        for check in judgment.checks:
            verdict = H(badge(check.verdict, check.verdict))
            check_rows.append([check.campno, verdict, check.complaint_quote, check.recall_quote, check.reason])
        checks = table(["recall", "verdict", "owner wrote", "recall says", "reason"], check_rows)
        judge_parts.append(f"<h4>Per-recall checks</h4>{checks}")

        if judgment.similar:
            similar_rows = [[earlier.odino, earlier.quote] for earlier in judgment.similar]
            similar_table = table(["earlier complaint", "quote"], similar_rows)
            judge_parts.append(f"<h4>Earlier owners describing the same failure</h4>{similar_table}")

        judge_parts.append(kv([
            ("proposed outcome", judgment.proposed),
            ("summary", judgment.summary),
            ("questions for the owner", " · ".join(judgment.questions) or "—"),
            ("model", run.model),
        ]))
        judge_html = H("".join(judge_parts))
    else:
        judge_html = H('<p class="dim">No AI judgment for this run (rules only).</p>')

    # e. Verify
    attempt_rows = []
    for attempt in run.attempts:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in attempt.issues) or "none ✔"
        tokens = f"{attempt.input_tokens:,} / {attempt.output_tokens:,}"
        attempt_rows.append([attempt.n, attempt.error or "", issues, tokens])
    verify_html = table(["attempt", "error", "issues found by the verifier", "tokens in / out"], attempt_rows)

    # f. Decide, next to what the rules alone would have decided.
    rules_only = baseline(intake, evidence, [], "rules")
    rules_only_text = f"{rules_only.outcome}"
    if rules_only.campno:
        rules_only_text += f" ({rules_only.campno})"
    rules_only_text += f" — {rules_only.reasons[0]}"
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in decision.reasons)
    decide_html = kv([
        ("outcome", H(badge(decision.outcome, decision.outcome))),
        ("confidence", decision.confidence),
        ("matched recall", decision.campno or "—"),
        ("escalate", "yes" if decision.escalate else "no"),
        ("source", decision.source),
        ("flags", ", ".join(decision.flags) or "—"),
        ("reasons", H(f"<ul>{reasons}</ul>")),
        ("for contrast: rules-only baseline", rules_only_text),
    ])

    # g. Stored run
    stored_html = kv([
        ("app.db results.id", run.id),
        ("created_at", run.created_at),
        ("steps that ran", " → ".join(run.steps)),
        ("latency", f"{run.latency_ms:,} ms"),
    ])

    # h. What the analyst sees
    suggestion = suggest(run, deps.store().tickets, related_for(run))
    action_items = []
    for action in suggestion.actions:
        label = escape(action.label)
        if action.primary:
            label = f"<b>{label}</b> (suggested)"
        action_items.append(f"<li>{label}</li>")
    actions = "".join(action_items)
    why = "".join(f"<li>{escape(reason.text)}</li>" for reason in suggestion.why)
    suggestion_html = H(f'<div class="card"><div class="headline">{escape(suggestion.headline)}</div>'
                        f"<p>{escape(suggestion.summary)}</p><b>Why</b><ul>{why}</ul><b>Actions</b><ul>{actions}</ul>"
                        "</div>")

    # Put the steps together.
    steps = [
        ("a", "Complaint", "nhtsa.db → Complaint", complaint_html),
        ("b", "Intake", "code: mask recall numbers, flag what is missing", intake_html),
        ("c", "Evidence", "code: SQL, only records dated before the complaint", evidence_html),
        ("d", "Judge", "AI agent: compares the complaint with each candidate recall", judge_html),
        ("e", "Verify", "code: recall ids exist, quotes copied exactly, no invented numbers", verify_html),
        ("f", "Decide", "code: rules turn verified checks into the outcome", decide_html),
        ("g", "Stored run", "app.db: the whole Result as JSON, the audit record", stored_html),
        ("h", "What the analyst sees", "workspace: suggestion built from the stored run", suggestion_html),
    ]
    step_blocks = []
    for letter, name, subtitle, content in steps:
        heading = f'<h3><span class="n">{letter}</span> {escape(name)} <small>{escape(subtitle)}</small></h3>'
        step_blocks.append(f'<div class="step">{heading}{content}</div>')
    body = "".join(step_blocks)

    title = f"{case['id']} · {complaint.year} {complaint.make} {complaint.model} — {case['title']}"
    hindsight = ""
    if case.get("next"):
        hindsight = f"<p class='dim'><b>Hindsight (never shown to the system):</b> {escape(case['next'])}</p>"
    open_attr = " open" if case["id"] == "D1" else ""
    return H(f"""<details class="case"{open_attr}><summary>{escape(title)}
{badge(decision.outcome, decision.outcome)}</summary><p>{escape(case['story'])}</p>{hindsight}{body}</details>""")


def demo_workspace(runs: list[tuple[dict, Result]]) -> tuple[Path, Store]:
    """A throwaway copy of app.db with the demo tickets worked through, so the workspace tables have real rows to show
    without touching the real workspace: the suggested action on each ticket, except D2 where the analyst disagrees
    (records and watches instead of escalating, and says why)."""
    folder = Path(tempfile.mkdtemp(prefix="report-"))
    path = folder / "app.db"
    shutil.copy(get_settings().app_db_path, path)
    store = Store(path)
    for case, run in runs:
        if case["id"] == "D2":
            request = ActionRequest(action="monitor", disagrees=True,
                                    reason="Demo: engineering already tracks air bag non-deployment on this model")
        else:
            suggestion = suggest(run, store.tickets, related_for(run))
            primary = next(action for action in suggestion.actions if action.primary)
            request = ActionRequest(action=primary.id, campno=primary.campno, issue_id=primary.issue_id,
                                    issue_title=primary.issue_title, issue_kind=primary.issue_kind,
                                    issue_comp=primary.issue_comp, message=primary.message)
        apply(store.tickets, run, request)
    return folder, store


def section_app(runs: list[tuple[dict, Result]]) -> H:
    """data/app.db: what the system did (results) and what people did with it (the workspace tables)."""
    app_path = get_settings().app_db_path
    real = sqlite3.connect(f"file:{app_path}?mode=ro", uri=True)

    # Every table in the real file, with what uses it.
    table_rows = []
    names = [row[0] for row in real.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'sqlite_sequence' ORDER BY name")]
    for name in names:
        columns = [info[1] for info in real.execute(f"PRAGMA table_info([{name}])")]
        row_count = real.execute(f"SELECT count(*) FROM [{name}]").fetchone()[0]
        if name not in WORKSPACE_TABLES:
            name = H(f"{escape(name)} <span class='dim'>(left from an earlier version; not used by the code)</span>")
        table_rows.append([name, f"{row_count:,}", ", ".join(columns)])
    tables_table = table(["Table", "Rows (your file)", "Columns"], table_rows)
    by_label = sample(real, "SELECT label, count(*) AS runs, min(created_at) AS first, max(created_at) AS last "
                            "FROM results GROUP BY label ORDER BY last DESC")
    results_rows = sample(real, "SELECT id, odino, label, created_at, outcome, confidence, escalate, source, "
                                "length(body) AS body_chars FROM results WHERE label = 'queue' "
                                "ORDER BY created_at DESC LIMIT 4")
    real.close()

    # The workspace tables, filled by replaying the demo actions on a copy.
    folder, store = demo_workspace(runs)
    try:
        workspace = [
            "<h3>tickets</h3>", sample(store.con, "SELECT * FROM tickets ORDER BY odino"),
            "<h3>issues</h3>", sample(store.con, "SELECT * FROM issues ORDER BY id"),
            "<h3>issue_complaints</h3>", sample(store.con, "SELECT * FROM issue_complaints ORDER BY issue_id"),
            "<h3>actions</h3>", sample(store.con, "SELECT * FROM actions ORDER BY id"),
        ]
    finally:
        store.con.close()
        shutil.rmtree(folder, ignore_errors=True)
    workspace.append("<h3>questions</h3><p class='dim'>One row per follow-up question; <code>body</code> is the whole "
                     "Turn as JSON (question, answer with citations, verified, issues, searches, result_id). Empty "
                     "until an analyst asks.</p>")

    main_run = runs[0][1]
    body = json.loads(main_run.model_dump_json())
    return H(f"""<section><h2>5 · What the app stores (<code>data/app.db</code>, {mb(app_path)})</h2>
<p>Everything the system did (<b>results</b>, append-only, one row per run) and everything people did with it
(<b>tickets, issues, issue_complaints, actions, questions</b>). NHTSA records are referred to by their public ids
(<code>odino</code>, <code>campno</code>); there are no constraints across the two files (dashed lines).
<code>python -m app.store.reset</code> clears the people's tables and keeps the runs.</p>
{diagram("app")}{tables_table}
<h3>results: runs by label</h3>{by_label}
<h3>results: the newest workspace runs</h3>
<p class="dim">The listing columns are copies of fields in <code>body</code>, so runs can be listed without parsing
JSON.</p>{results_rows}
<h3>The workspace tables after working the four demo tickets</h3>
<p class="dim">Replayed by this report on a temporary copy of app.db (your workspace is not touched): the suggested
action on D1, D3 and D4; on D2 the analyst records and watches instead of escalating, so the log shows a
<i>disagreed</i> row with the reason.</p>{"".join(workspace)}
<h3>results.body: one stored run (D1), field by field</h3>
{diagram("result")}
<div class="outline-root">{outline(body, "Result", open_=True)}</div></section>""")


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
pre.mermaid{background:#fff;color:#1d2433;max-height:none;border:1px solid #e2e5ea;text-align:center}
.outline-root{font-size:13px;font-family:Consolas,monospace}ul.outline{list-style:none;margin:2px 0;padding-left:18px}
ul.outline li{margin:1px 0;overflow-wrap:anywhere}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--no-raw", action="store_true", help="skip scanning the raw zip files (the slow part)")
    args = parser.parse_args()
    started = time.time()

    # The demo cases and their stored AI runs. The first case is the one followed through the raw files and the db.
    cases = json.loads(DEMO.read_text(encoding="utf-8"))["cases"]
    latest = deps.store().latest("queue")
    missing = [case["id"] for case in cases if case["odino"] not in latest]
    if missing:
        raise SystemExit(f"no stored run for {missing}: run `python -m app.store.reset` first")
    runs = [(case, latest[case["odino"]]) for case in cases]
    main_run = runs[0][1]

    # The raw rows behind the first case.
    cmpl_rows = {}
    rcl_rows = {}
    repair = None
    if not args.no_raw:
        print("scanning raw files (up to a minute)...")
        odino = str(main_run.complaint.odino)
        cmpl_rows, repair = scan("FLAT_CMPL.zip", CMPL.index("ODINO"), {odino}, repair_example=True)
        campno = main_run.decision.campno
        if campno:
            rcl_rows, _ = scan("FLAT_RCL_POST_2010.zip", RCL.index("CAMPNO"), {campno})

    con = deps.con()
    sections = [section_flow()]
    if not args.no_raw:
        sections.append(section_raw(main_run, cmpl_rows, rcl_rows, repair))
    sections.append(section_ingest())
    sections.append(section_db(con, runs))
    cases_html = "".join(section_case(case, run) for case, run in runs)
    sections.append(H("<section><h2>4 · One complaint through the pipeline</h2><p>Real complaints from the demo inbox, "
                      "with their stored AI runs. Each step shows its actual input/output. Highlighted in the text: "
                      f"<mark>{escape(MASK)}</mark> and the exact words the AI quoted (verified).</p>"
                      + cases_html + "</section>"))
    sections.append(section_app(runs))
    content = "".join(sections)

    mermaid = ('<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/'
               'mermaid.esm.min.mjs"; mermaid.initialize({startOnLoad: true, theme: "neutral"});</script>')
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Recall Match: the data</title>
<style>{CSS}</style>{mermaid}</head><body><main><h1>Recall Match: how the data flows</h1>
<p class="dim">Generated by <code>python -m app.data.report</code> from data/raw, data/nhtsa.db and the stored runs in
data/app.db. Static snapshot: no model or server needed to view it (the diagrams load mermaid from a CDN; offline
they show as text, also in docs/DATA_MODEL.md).</p>{content}</main></body></html>"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e3:,.0f} KB) in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
