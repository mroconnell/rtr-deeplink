"""Build the Archive meeting inventory report: a CSV and a self-contained,
sortable/filterable HTML review page, one row per archived meeting page.

Reads production ONLY over HTTP, via the token-gated
GET /internal/meeting-inventory (rows, keyset-paginated) and
GET /internal/meeting-inventory/summary (missing-field counts) -- never a
database connection, and never more than 500 rows per request
(BACKLOG.md's standing "production access is HTTP-only" decision). The
row shape and every derived column live in
archive/utils/meeting_inventory.py; this script only walks, counts, and
renders.

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/inventory
    python scripts/export_meeting_inventory.py --out-dir /tmp/inventory --limit 10
    python scripts/export_meeting_inventory.py --out-dir /tmp/inventory --source export

`--source export` walks the older GET /internal/export/pages instead and
derives every row locally with the same inventory_row() the endpoint
uses -- for a production that has the export endpoint deployed but not
yet the inventory one (deploys are manual here; merged is not live). The
summary is then counted from the rows rather than the SQL aggregate,
with the same keys.

Reads ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN from the environment
(.env is loaded; the token is never printed). Writes
meeting_inventory.csv, meeting_inventory.html and summary.json.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

import certifi

# Same fresh-venv trust-store fix every network script here carries (see
# CLAUDE.md); harmless when the store is already populated.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from archive.utils.meeting_inventory import COLUMNS, inventory_row  # noqa: E402

REQUEST_PAUSE_SECONDS = 0.4

# Column bands and labels for the review page. Order matches COLUMNS.
BANDS = [
    (
        "Government",
        [
            ("stored_jurisdiction", "Stored name"),
            ("page_display_name", "Page shows"),
            ("gov_id", "Gov id"),
            ("gov_display_name", "Registry name"),
            ("names_match", "Match"),
            ("follows_city_st", "City, ST"),
            ("gov_type", "Gov type"),
            ("jurisdiction_confidence", "Confidence"),
        ],
    ),
    (
        "Meeting",
        [
            ("meeting_body", "Body (stored)"),
            ("meeting_name", "Meeting name"),
            ("meeting_date", "Date"),
        ],
    ),
    (
        "Media",
        [
            ("has_video", "Video"),
            ("video_format", "Format"),
            ("has_transcript", "Transcript"),
            ("transcript_source", "Source"),
            ("transcript_segments", "Segments"),
            ("transcript_warnings", "Warnings"),
            ("outcome", "Outcome"),
        ],
    ),
    (
        "Platforms",
        [
            ("page_platform", "Page platform"),
            ("page_platform_by_url", "By URL today"),
            ("stored_platform", "Stored"),
            ("best_effort_resolve", "Best-effort"),
            ("video_platform", "Video platform"),
            ("video_host_domain", "Video host"),
        ],
    ),
    (
        "Links",
        [
            ("archive_url", "Archive"),
            ("source_url", "Source"),
            ("video_url", "Video"),
            ("created_at", "Archived"),
        ],
    ),
]

# Summary tiles: (label, key in the summary dict, column + value that
# filters the table to those rows when the tile is clicked).
TILES = [
    ("Pages", "total_pages", None, None),
    ("No stored body", "missing_meeting_body", "meeting_body", ""),
    ("No date", "missing_date", "meeting_date", ""),
    ("No gov id", "missing_gov_id", "gov_id", ""),
    ("Name ≠ registry", "names_mismatch", "names_match", "no"),
    ("Not City, ST", "not_city_st", "follows_city_st", "no"),
    ("No video", "no_video", "has_video", "no"),
    ("No transcript", "no_transcript", "has_transcript", "no"),
    ("Best-effort", "best_effort", "best_effort_resolve", "yes"),
]


def _get(base: str, token: str, path: str, params: dict | None = None) -> dict:
    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                sys.exit(
                    "404 from the Archive: wrong token, or the inventory "
                    "endpoint is not deployed there yet (merged is not live)."
                )
            last_exc = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
        wait = 2**attempt
        print(f"  retry {attempt + 1} after {last_exc} ({wait}s)", file=sys.stderr)
        time.sleep(wait)
    sys.exit(f"inventory endpoint failed after retries: {last_exc}")


def fetch_rows(base: str, token: str, max_rows: int | None) -> list[dict]:
    rows: list[dict] = []
    after_id = 0
    while True:
        page_size = 500 if max_rows is None else min(500, max_rows - len(rows))
        if page_size <= 0:
            return rows
        body = _get(
            base,
            token,
            "/internal/meeting-inventory",
            {"after_id": after_id, "limit": page_size},
        )
        rows.extend(body["rows"])
        print(f"  fetched {len(rows)} rows", file=sys.stderr)
        if body["next_after_id"] is None:
            return rows
        after_id = body["next_after_id"]
        time.sleep(REQUEST_PAUSE_SECONDS)


def sql_summary_from_rows(rows: list[dict]) -> dict:
    """The same keys get_meeting_inventory_summary() returns, counted from
    derived rows -- used only with --source export."""
    return {
        "total_pages": len(rows),
        "missing_meeting_body": sum(r["meeting_body"] == "" for r in rows),
        "missing_date": sum(r["meeting_date"] == "" for r in rows),
        "missing_title": sum(r["meeting_name"] == "" for r in rows),
        "missing_jurisdiction": sum(r["stored_jurisdiction"] == "" for r in rows),
        "missing_gov_id": sum(r["gov_id"] == "" for r in rows),
        "missing_gov_type": sum(r["gov_type"] == "" for r in rows),
        "no_video": sum(r["has_video"] == "no" for r in rows),
        "no_transcript": sum(r["has_transcript"] == "no" for r in rows),
    }


def fetch_rows_via_export(base: str, token: str, max_rows: int | None) -> list[dict]:
    rows: list[dict] = []
    after_id = 0
    while True:
        page_size = 500 if max_rows is None else min(500, max_rows - len(rows))
        if page_size <= 0:
            return rows
        body = _get(
            base,
            token,
            "/internal/export/pages",
            {"after_id": after_id, "limit": page_size},
        )
        rows.extend(inventory_row(p) for p in body["pages"])
        print(f"  fetched {len(rows)} rows (via export/pages)", file=sys.stderr)
        if body["next_after_id"] is None:
            return rows
        after_id = body["next_after_id"]
        time.sleep(REQUEST_PAUSE_SECONDS)


def local_summary(rows: list[dict]) -> dict:
    """Counts the endpoint's SQL summary can't produce because they're
    derived in Python (name match, convention, best-effort)."""
    return {
        "names_mismatch": sum(r["names_match"] == "no" for r in rows),
        "names_prefix_only": sum(r["names_match"] == "prefix only" for r in rows),
        "not_city_st": sum(r["follows_city_st"] == "no" for r in rows),
        "best_effort": sum(r["best_effort_resolve"] == "yes" for r in rows),
        "rows_in_report": len(rows),
        "gov_type_counts": dict(Counter(r["gov_type"] or "(blank)" for r in rows)),
        "page_platform_counts": dict(Counter(r["page_platform"] for r in rows)),
        "video_platform_counts": dict(
            Counter(r["video_platform"] or "(none)" for r in rows)
        ),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(COLUMNS), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


HTML_TEMPLATE = """<title>Archive Meeting Inventory</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,600&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400&display=swap">
<style>
:root{--bg:#F2F4F6;--panel:#FFFFFF;--ink:#1B2530;--muted:#66717D;--line:#D5DBE1;--band:#E4E9EE;--accent:#1E5A66;--ok-bg:#DDF0E3;--ok:#1F6B3E;--bad-bg:#F8DCD9;--bad:#9F2A22;--warn-bg:#FBEAD0;--warn:#8A5410;--mut-bg:#E9ECEF;--focus:#1E5A66}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#12181E;--panel:#1A222A;--ink:#E4E9ED;--muted:#93A0AC;--line:#2E3941;--band:#222C35;--accent:#7FC4CF;--ok-bg:#1E3A2A;--ok:#8FD6A8;--bad-bg:#432322;--bad:#F1A29A;--warn-bg:#43331A;--warn:#F0C070;--mut-bg:#2A343D;--focus:#7FC4CF}}
:root[data-theme="dark"]{--bg:#12181E;--panel:#1A222A;--ink:#E4E9ED;--muted:#93A0AC;--line:#2E3941;--band:#222C35;--accent:#7FC4CF;--ok-bg:#1E3A2A;--ok:#8FD6A8;--bad-bg:#432322;--bad:#F1A29A;--warn-bg:#43331A;--warn:#F0C070;--mut-bg:#2A343D;--focus:#7FC4CF}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:14px/1.45 "Source Sans 3",system-ui,sans-serif;margin:0;padding:24px 20px 40px}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px 24px;margin-bottom:14px}
h1{font:600 24px/1.15 "Source Serif 4",Georgia,serif;margin:0 0 4px;text-wrap:balance}
header p{margin:0;color:var(--muted);max-width:70ch}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:8px;margin:0 0 14px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:8px 10px;text-align:left;cursor:pointer;font:inherit;color:var(--ink)}
.tile b{display:block;font-size:22px;line-height:1.1;font-variant-numeric:tabular-nums}
.tile small{display:block;color:var(--muted);font-size:12px;margin-top:2px}
.tile[aria-pressed="true"]{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
.tile:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--focus);outline-offset:1px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:10px}
.bar input[type=search]{flex:1 1 260px;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font:inherit}
.bar button{padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink);font:inherit;cursor:pointer}
.bar button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.bar .count{color:var(--muted);font-variant-numeric:tabular-nums;margin-left:auto}
.wrap{overflow:auto;max-height:calc(100vh - 230px);border:1px solid var(--line);border-radius:6px;background:var(--panel)}
table{border-collapse:separate;border-spacing:0;font-size:13px;white-space:nowrap;min-width:100%}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
thead th{position:sticky;background:var(--panel);z-index:3}
thead tr.bands th{top:0;background:var(--band);color:var(--accent);text-transform:uppercase;letter-spacing:.06em;font-size:11px;border-left:1px solid var(--line);padding:4px 10px}
thead tr.heads th{top:25px;font-weight:600;cursor:pointer;user-select:none;font-size:12px}
thead tr.heads th .dir{color:var(--accent);margin-left:4px}
thead tr.filters th{top:55px;padding:3px 6px}
thead tr.filters input{width:100%;min-width:70px;padding:3px 6px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--ink);font:12px "Source Sans 3",system-ui,sans-serif}
td.id,thead th.id{position:sticky;left:0;z-index:2;background:var(--panel);border-right:1px solid var(--line)}
thead th.id{z-index:4}
tbody tr:hover td{background:var(--band)}
td.mono{font:12px/1.5 "JetBrains Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
td.empty{color:var(--muted);text-align:center}
td.url a{color:var(--accent);text-decoration:none;font:12px/1.5 "JetBrains Mono",ui-monospace,monospace}
td.url a:hover{text-decoration:underline}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.bad{background:var(--bad-bg);color:var(--bad)}
.pill.warn{background:var(--warn-bg);color:var(--warn)}.pill.muted{background:var(--mut-bg);color:var(--muted)}
.note{color:var(--muted);font-size:12px;margin-top:8px}
@media (prefers-reduced-motion: no-preference){.tile{transition:border-color .15s}}
</style>
<header>
  <div>
    <h1>Archive Meeting Inventory</h1>
    <p>One row per archived meeting page. Every value is stored or derived by the site itself; blanks are real and are counted above the table. Click a tile to filter to those rows, a column header to sort, and type in the filter row to narrow a column.</p>
  </div>
  <p>Built __BUILT__ from __TOTAL__ pages.</p>
</header>
<div class="tiles" id="tiles"></div>
<div class="bar">
  <input type="search" id="q" placeholder="Search every column" aria-label="Search every column">
  <button type="button" id="clear">Clear filters</button>
  <button type="button" id="dl" class="primary">Download CSV</button>
  <span class="count" id="count"></span>
</div>
<div class="wrap"><table id="t"><thead></thead><tbody></tbody></table></div>
<p class="note" id="note"></p>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
const DATA = JSON.parse(document.getElementById('data').textContent);
const ROWS = DATA.rows, BANDS = DATA.bands, SUMMARY = DATA.summary, TILES = DATA.tiles;
const COLS = [['page_id','#']].concat(BANDS.flatMap(b => b[1]));
const KEYS = COLS.map(c => c[0]);
const PILL = {has_video:1,has_transcript:1,follows_city_st:1,names_match:1,best_effort_resolve:1,outcome:1};
const MONO = {gov_id:1,video_host_domain:1,stored_platform:1,page_platform_by_url:1,transcript_segments:1,transcript_warnings:1,meeting_date:1,created_at:1,page_id:1};
const URL = {archive_url:1,source_url:1,video_url:1};
const NUM = {page_id:1,transcript_segments:1,transcript_warnings:1};
let filters = {}, query = '', sortKey = 'page_id', sortDir = 1, activeTile = null;

function esc(s){return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function pillClass(k, v){
  if(k==='best_effort_resolve') return v==='yes'?'warn':'muted';
  if(k==='outcome') return v.startsWith('Transcript')?'ok':'bad';
  if(k==='names_match') return v==='yes'?'ok':(v==='prefix only'?'warn':'bad');
  return v==='yes'?'ok':'bad';
}
function cell(k, v){
  if(v===''||v===null||v===undefined) return '<td class="empty">—</td>';
  if(URL[k]){let l=String(v).replace(/^https?:\\/\\//,''); if(l.length>44) l=l.slice(0,41)+'…'; return '<td class="url"><a href="'+esc(v)+'" target="_blank" rel="noopener">'+esc(l)+'</a></td>';}
  if(PILL[k]) return '<td><span class="pill '+pillClass(k,String(v))+'">'+esc(v)+'</span></td>';
  if(k==='page_id') return '<td class="id mono">'+esc(v)+'</td>';
  if(k==='created_at') return '<td class="mono">'+esc(String(v).slice(0,10))+'</td>';
  if(MONO[k]) return '<td class="mono">'+esc(v)+'</td>';
  return '<td>'+esc(v)+'</td>';
}
function renderHead(){
  const bands = '<tr class="bands"><th class="id">id</th>'+BANDS.map(b=>'<th colspan="'+b[1].length+'">'+esc(b[0])+'</th>').join('')+'</tr>';
  const heads = '<tr class="heads">'+COLS.map(c=>'<th data-k="'+c[0]+'" class="'+(c[0]==='page_id'?'id':'')+'">'+esc(c[1])+(sortKey===c[0]?'<span class="dir">'+(sortDir>0?'▲':'▼')+'</span>':'')+'</th>').join('')+'</tr>';
  const fl = '<tr class="filters">'+COLS.map(c=>'<th class="'+(c[0]==='page_id'?'id':'')+'"><input data-k="'+c[0]+'" value="'+esc(filters[c[0]]||'')+'" placeholder="filter" aria-label="Filter '+esc(c[1])+'"></th>').join('')+'</tr>';
  document.querySelector('#t thead').innerHTML = bands+heads+fl;
}
function matches(r){
  for(const k in filters){const f=filters[k]; if(f===undefined) continue;
    const v = String(r[k]===null||r[k]===undefined?'':r[k]);
    if(f.exact!==undefined){ if(v!==f.exact) return false; }
    else if(f.text && !v.toLowerCase().includes(f.text)) return false;}
  if(query){const q=query; if(!KEYS.some(k=>String(r[k]??'').toLowerCase().includes(q))) return false;}
  return true;
}
function visible(){
  const out = ROWS.filter(matches);
  out.sort((a,b)=>{let x=a[sortKey]??'',y=b[sortKey]??''; if(NUM[sortKey]){x=+x||0;y=+y||0;} else {x=String(x).toLowerCase();y=String(y).toLowerCase();} return x<y?-sortDir:(x>y?sortDir:0);});
  return out;
}
let current = [];
function renderBody(){
  current = visible();
  document.querySelector('#t tbody').innerHTML = current.map(r=>'<tr>'+KEYS.map(k=>cell(k,r[k])).join('')+'</tr>').join('');
  document.getElementById('count').textContent = current.length.toLocaleString()+' of '+ROWS.length.toLocaleString()+' rows';
}
function renderTiles(){
  document.getElementById('tiles').innerHTML = TILES.map(t=>{const n = SUMMARY[t[1]]; const pct = t[1]==='total_pages'||!SUMMARY.total_pages?'':' · '+(100*n/SUMMARY.total_pages).toFixed(1)+'%';
    return '<button type="button" class="tile" data-i="'+TILES.indexOf(t)+'" aria-pressed="'+(activeTile===t[1])+'"'+(t[2]?'':' disabled')+'><b>'+(n===undefined?'—':n.toLocaleString())+'</b><small>'+esc(t[0])+pct+'</small></button>';}).join('');
}
function applyTile(t){
  if(activeTile===t[1]){activeTile=null; delete filters[t[2]];}
  else { for(const u of TILES){ if(u[2]) delete filters[u[2]]; } activeTile=t[1]; filters[t[2]]={exact:t[3]}; }
  renderTiles(); renderHead(); renderBody();
}
document.getElementById('tiles').addEventListener('click', e=>{const b=e.target.closest('.tile'); if(!b||b.disabled) return; applyTile(TILES[+b.dataset.i]);});
document.querySelector('#t thead').addEventListener('click', e=>{const th=e.target.closest('tr.heads th'); if(!th) return; const k=th.dataset.k; if(sortKey===k) sortDir=-sortDir; else {sortKey=k; sortDir=1;} renderHead(); renderBody();});
document.querySelector('#t thead').addEventListener('input', e=>{const i=e.target; if(!i.dataset.k) return; const v=i.value.trim().toLowerCase(); if(v) filters[i.dataset.k]={text:v}; else delete filters[i.dataset.k]; if(activeTile){activeTile=null; renderTiles();} renderBody();});
document.getElementById('q').addEventListener('input', e=>{query=e.target.value.trim().toLowerCase(); renderBody();});
document.getElementById('clear').addEventListener('click', ()=>{filters={}; query=''; activeTile=null; document.getElementById('q').value=''; renderTiles(); renderHead(); renderBody();});
function toCsv(rows){
  const cols = DATA.columns;
  const q = v => {const s = String(v??''); return /[",\\n]/.test(s) ? '"'+s.replace(/"/g,'""')+'"' : s;};
  return cols.join(',')+'\\n'+rows.map(r=>cols.map(c=>q(r[c])).join(',')).join('\\n')+'\\n';
}
let downloads = null;
if(window.claude && typeof window.claude.use==='function'){ window.claude.use('downloads').then(d=>{downloads=d;}).catch(()=>{}); }
document.getElementById('dl').addEventListener('click', async ()=>{
  const csv = toCsv(current), name = 'meeting_inventory'+(current.length===ROWS.length?'':'_filtered')+'.csv';
  const note = document.getElementById('note');
  if(downloads){ try{ await downloads.save({filename:name, data:csv}); note.textContent='Saved '+name+' ('+current.length.toLocaleString()+' rows).'; }catch(e){ note.textContent = e && e.code==='declined' ? 'Download cancelled.' : 'Download unavailable here ('+(e&&e.code||'error')+'). Open the HTML file locally to save.'; } return; }
  try{ const a=document.createElement('a'); a.href=window.URL.createObjectURL(new Blob([csv],{type:'text/csv'})); a.download=name; document.body.appendChild(a); a.click(); a.remove(); note.textContent='Downloading '+name+' ('+current.length.toLocaleString()+' rows).'; }
  catch(e){ note.textContent='Download unavailable in this viewer. Open the HTML file locally to save.'; }
});
renderTiles(); renderHead(); renderBody();
})();
</script>
"""


def write_html(path: Path, rows: list[dict], summary: dict) -> None:
    payload = {
        "rows": rows,
        "bands": BANDS,
        "tiles": TILES,
        "summary": summary,
        "columns": list(COLUMNS),
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    page = (
        HTML_TEMPLATE.replace("__DATA__", data)
        .replace("__BUILT__", html.escape(date.today().isoformat()))
        .replace("__TOTAL__", f"{summary.get('total_pages', len(rows)):,}")
    )
    path.write_text(page, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many rows (a quick preview); default is every page",
    )
    ap.add_argument(
        "--source",
        choices=("inventory", "export"),
        default="inventory",
        help="'export' derives rows locally from /internal/export/pages (see above)",
    )
    args = ap.parse_args()

    base = os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    if not base or not token:
        sys.exit("ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN must be set (see .env)")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.source == "export":
        print("rows (via export/pages)...", file=sys.stderr)
        rows = fetch_rows_via_export(base, token, args.limit)
        summary = sql_summary_from_rows(rows)
    else:
        print("summary...", file=sys.stderr)
        summary = _get(base, token, "/internal/meeting-inventory/summary")
        print("rows...", file=sys.stderr)
        rows = fetch_rows(base, token, args.limit)
    summary.update(local_summary(rows))

    write_csv(args.out_dir / "meeting_inventory.csv", rows)
    write_html(args.out_dir / "meeting_inventory.html", rows, summary)
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(
        json.dumps({k: v for k, v in summary.items() if isinstance(v, int)}, indent=2)
    )
    print(f"wrote {len(rows)} rows to {args.out_dir}")


if __name__ == "__main__":
    main()
