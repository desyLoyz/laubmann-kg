"""Derive tools/explorer/index.html from the v7 snapshot (no embedded 34-volume graph).

Reads tools/explorer/Laubmann-KG_Explorer.full.html (the publication snapshot)
and writes a shell that loads html/graph.json from sample runs and can compare two.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tools" / "explorer" / "Laubmann-KG_Explorer.full.html"
OUT = ROOT / "tools" / "explorer" / "index.html"
ALIAS = ROOT / "tools" / "Laubmann-KG_Explorer.html"

CSS = """
#runs { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; padding:6px 14px; border-bottom:1px solid var(--line); background: var(--surface); font-size:.78rem; color:var(--muted); }
#runs label { display:inline-flex; align-items:center; gap:6px; }
#runs input[type=file] { font-size:.72rem; max-width:240px; }
#compare { position:absolute; inset:0; overflow:auto; padding:16px 20px 40px; display:none; background:var(--bg); z-index:3; }
#compare.on { display:block; }
.cmp-row { display:grid; grid-template-columns: minmax(140px, 1.4fr) 1fr 1fr minmax(120px, 1fr); gap:8px; padding:7px 8px; border-bottom:1px solid var(--line2); font-size:.82rem; cursor:pointer; }
.cmp-row:hover { background: var(--surface); }
.cmp-row.head { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); cursor:default; }
.pill.only-a { background:var(--warn-soft); color:var(--warn); }
.pill.only-b { background:var(--ext-soft); color:var(--ext); }
.pill.chg { background:var(--accent-soft); color:var(--accent); }
.cmp-cols { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:12px; }
.cmp-cols h3 { margin-top:0; }
.cmp-miss { color:var(--muted); font-style:italic; }
"""

RUNS_BAR = """
<div id="runs">
  <span class="field">run A <input type="file" id="fileA" accept=".json,.json.gz,application/json" title="html/graph.json from a sample export"></span>
  <span class="field">run B <input type="file" id="fileB" accept=".json,.json.gz,application/json" title="second run to compare"></span>
  <span class="modes" id="runMode">
    <button type="button" id="btnA" data-run="A" aria-pressed="true">A</button>
    <button type="button" id="btnB" data-run="B" aria-pressed="false" disabled>B</button>
    <button type="button" id="btnCmp" data-run="compare" aria-pressed="false" disabled>compare</button>
  </span>
  <span id="runLabels" class="muted"></span>
</div>
"""

COMPARE_PANEL = '<div id="compare"></div>\n'

LOADER = r'''
(function () {
  let E = [], O = [], T = [], P = [], PE = [], H = [], META = {};
  let Y0 = 1917, Y1 = 1965, LAUB, entryById, byUid, taxEntries, plEntries, peEntries, WX, GEO;
  let GA = null, GB = null, activeRun = 'A';
  const runNames = { A: '', B: '' };
'''

INGEST_HEAD = r'''
  function ingest(G) {
    E = G.entries || []; O = G.obs || []; T = G.taxa || []; P = G.places || [];
    PE = G.persons || []; H = G.habitats || []; META = G.meta || {};
'''

EXTRA_JS = r'''
  function hideLoading() {
    const el = document.getElementById('loading');
    if (el) el.style.display = 'none';
  }
  function setCompare(on) {
    const c = document.getElementById('compare');
    if (c) c.classList.toggle('on', on);
  }
  function updateRunLabels() {
    const el = document.getElementById('runLabels');
    if (!el) return;
    const bits = [];
    if (runNames.A) bits.push('A · ' + runNames.A);
    if (runNames.B) bits.push('B · ' + runNames.B);
    el.textContent = bits.join('  |  ');
  }
  function startView() {
    setCompare(false);
    hideLoading();
    renderList();
    if (!fromHash() && E.length) {
      const score = e => { const n = (e.obs || []).length; return (n >= 12 && n <= 45 ? 3 : 0) + (e.w ? 1 : 0) + ((e.tr || []).length ? 1 : 0) + ((e.pe || []).length ? 1 : 0) + Math.min(n, 45) / 45; };
      open('entry', E.reduce((a, b) => (score(b) > score(a) ? b : a), E[0]).i);
    }
  }
  function obsKey(o, taxa) {
    const name = (o.t != null && taxa[o.t]) ? taxa[o.t].name : '';
    return [name, o.d || '', (o.v || '').slice(0, 80)].join('|');
  }
  function obsNames(entry, graph) {
    return (entry.obs || []).map(i => {
      const o = graph.obs[i];
      const t = (o.t != null && graph.taxa[o.t]) ? graph.taxa[o.t].name : '?';
      return t + (o.n != null ? ' ×' + o.n : '') + (o.st === 'absent' ? ' (absent)' : '');
    });
  }
  function renderCompare() {
    if (!GA || !GB) return;
    setCompare(true);
    const aBy = new Map((GA.entries || []).map(e => [e.id, e]));
    const bBy = new Map((GB.entries || []).map(e => [e.id, e]));
    const ids = [...new Set([...aBy.keys(), ...bBy.keys()])].sort();
    let onlyA = 0, onlyB = 0, chg = 0, same = 0;
    const rows = ids.map(id => {
      const a = aBy.get(id), b = bBy.get(id);
      const na = a ? (a.obs || []).length : null;
      const nb = b ? (b.obs || []).length : null;
      const ka = a ? new Set((a.obs || []).map(i => obsKey(GA.obs[i], GA.taxa))) : new Set();
      const kb = b ? new Set((b.obs || []).map(i => obsKey(GB.obs[i], GB.taxa))) : new Set();
      let kind = 'both';
      if (!a) { kind = 'only-b'; onlyB++; }
      else if (!b) { kind = 'only-a'; onlyA++; }
      else if (na === nb && [...ka].every(x => kb.has(x)) && ka.size === kb.size) { kind = 'same'; same++; }
      else { kind = 'chg'; chg++; }
      return { id, a, b, na, nb, kind };
    });
    const C = document.getElementById('compare');
    C.innerHTML = `<h2>Compare sample runs</h2>
      <p class="sub">${esc(runNames.A || 'A')} vs ${esc(runNames.B || 'B')} · ${ids.length} entry ids</p>
      <div class="tiles">
        <div class="tile"><b>${fmt(GA.entries.length)}</b><span>entries A</span></div>
        <div class="tile"><b>${fmt(GB.entries.length)}</b><span>entries B</span></div>
        <div class="tile"><b>${fmt((GA.obs || []).length)}</b><span>obs A</span></div>
        <div class="tile"><b>${fmt((GB.obs || []).length)}</b><span>obs B</span></div>
        <div class="tile"><b>${fmt(onlyA)}</b><span>only in A</span></div>
        <div class="tile"><b>${fmt(onlyB)}</b><span>only in B</span></div>
        <div class="tile"><b>${fmt(chg)}</b><span>changed</span></div>
        <div class="tile"><b>${fmt(same)}</b><span>identical keys</span></div>
      </div>
      <div class="cmp-row head"><span>entry</span><span>A observations</span><span>B observations</span><span>status</span></div>
      ${rows.map((r, i) => `<div class="cmp-row" data-cmp="${i}">
        <span><b>${esc(r.id || '—')}</b> <span class="muted">${esc((r.a || r.b || {}).date || '')} ${(r.a || r.b || {}).pname ? '· ' + esc((r.a || r.b || {}).pname) : ''}</span></span>
        <span>${r.na == null ? '—' : fmt(r.na)}</span><span>${r.nb == null ? '—' : fmt(r.nb)}</span>
        <span><span class="pill ${r.kind}">${r.kind}</span></span>
      </div>`).join('')}
      <div id="cmpDetail"></div>`;
    C.querySelectorAll('[data-cmp]').forEach(row => row.addEventListener('click', () => {
      const r = rows[+row.dataset.cmp];
      const da = r.a ? obsNames(r.a, GA).map(esc).join('<br>') : '<span class="cmp-miss">not in A</span>';
      const db = r.b ? obsNames(r.b, GB).map(esc).join('<br>') : '<span class="cmp-miss">not in B</span>';
      document.getElementById('cmpDetail').innerHTML = `<div class="cmp-cols">
        <div><h3>${esc(runNames.A || 'A')}</h3><div class="small">${da || '<span class="muted">no observations</span>'}</div></div>
        <div><h3>${esc(runNames.B || 'B')}</h3><div class="small">${db || '<span class="muted">no observations</span>'}</div></div>
      </div>`;
    }));
  }
  async function parseGraphFile(file) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const gzip = bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
    if (gzip) return await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
    return JSON.parse(new TextDecoder().decode(bytes));
  }
  function setActiveRun(which) {
    document.querySelectorAll('#runMode [data-run]').forEach(b => b.setAttribute('aria-pressed', b.dataset.run === which ? 'true' : 'false'));
    activeRun = which;
    if (which === 'compare') { renderCompare(); return; }
    const G = which === 'B' ? GB : GA;
    if (!G) return;
    ingest(G);
    startView();
  }
  async function onFile(which, file) {
    if (!file) return;
    const G = await parseGraphFile(file);
    runNames[which] = file.name.replace(/\.json(\.gz)?$/i, '');
    if (which === 'A') GA = G; else GB = G;
    document.getElementById('btnB').disabled = !GB;
    document.getElementById('btnCmp').disabled = !(GA && GB);
    updateRunLabels();
    if (which === 'A' || activeRun === which) setActiveRun(which);
    else if (activeRun === 'compare') renderCompare();
  }
  $('#fileA').addEventListener('change', ev => onFile('A', ev.target.files[0]));
  $('#fileB').addEventListener('change', ev => onFile('B', ev.target.files[0]));
  document.querySelectorAll('#runMode [data-run]').forEach(b => b.addEventListener('click', () => {
    if (!b.disabled) setActiveRun(b.dataset.run);
  }));
  fetch('graph.json').then(r => r.ok ? r.json() : Promise.reject()).then(G => {
    GA = G; runNames.A = (G.meta && (G.meta.model || G.meta.backend || G.meta.source)) || 'graph.json';
    updateRunLabels(); ingest(G); startView();
  }).catch(() => {
    hideLoading();
    const d = document.getElementById('detail');
    if (d) d.innerHTML = '<h2>Load a sample run</h2><p class="sub">Use <b>run A</b> in the bar above the page.</p><p>Choose <code>html/graph.json</code> from a folder under <code>data/exports/sample_runs/</code>. Optionally load a second export as <b>run B</b> and click <b>compare</b>.</p>';
  });
})();
'''


def transform_app(app: str) -> str:
    # Drop the async IIFE wrapper and embedded-payload loader; keep helpers.
    start = app.find("  const $ = s =>")
    if start < 0:
        raise SystemExit("could not find helper block in explorer JS")
    idx_start = app.find("  // ---------- indexes ----------")
    ontology = app.find("  // ---------- ontology")
    if idx_start < 0 or ontology < 0:
        raise SystemExit("could not find index/ontology markers")
    helpers = app[start:idx_start]
    index_body = app[idx_start:ontology]
    rest = app[ontology:]

    # Index body used const bindings; ingest() assigns the outer lets.
    index_body = index_body.replace("  const entryById =", "  entryById =")
    index_body = index_body.replace("  const byUid =", "  byUid =")
    index_body = index_body.replace(
        "  const taxEntries = T.map(() => new Set()), plEntries = P.map(() => new Set()), peEntries = PE.map(() => new Set());",
        "  taxEntries = T.map(() => new Set()); plEntries = P.map(() => new Set()); peEntries = PE.map(() => new Set());",
    )
    index_body = index_body.replace("  const WX =", "  WX =")
    index_body = index_body.replace("  const GEO =", "  GEO =")
    index_body = index_body.replace("  const LAUB =", "  LAUB =")
    index_body = index_body.replace(
        "  const core = [...yc.entries()].filter(([, n]) => n >= 20).map(([y]) => y);\n"
        "  const Y0 = Math.min(...core), Y1 = Math.max(...core);\n",
        "  const core = [...yc.entries()].filter(([, n]) => n >= 20).map(([y]) => y);\n"
        "  const years = [...yc.keys()];\n"
        "  Y0 = core.length ? Math.min(...core) : (years.length ? Math.min(...years) : 1917);\n"
        "  Y1 = core.length ? Math.max(...core) : (years.length ? Math.max(...years) : 1965);\n",
    )
    index_body = index_body.replace(
        "  $('#stats').textContent = `${fmt(E.length)} entries · ${fmt(O.length)} observations · ${fmt(T.length)} taxa · ${fmt(P.length)} places · ${fmt(PE.length)} persons · ${fmt(WX.length)} weather reports · export 2026-08-19 · ontology 0.4.1`;\n"
        "  [...new Set(E.map(e => e.vol).filter(v => v != null))].sort((a, b) => a - b).forEach(v => { const o = document.createElement('option'); o.value = v; const sp = (META.vols || {})[v]; o.textContent = 'Vol. ' + String(v).padStart(2, '0') + (sp ? ' · ' + sp.replace('/', ' – ') : ''); $('#vol').appendChild(o); });\n"
        "  document.getElementById('loading').remove();\n",
        "  const src = META.model || META.backend || META.source || '';\n"
        "  const sample = META.sample || {};\n"
        "  const range = (sample.entry_id_from || sample.entry_id_to)\n"
        "    ? ` · ${sample.entry_id_from || '…'}–${sample.entry_id_to || '…'}` : '';\n"
        "  $('#stats').textContent = `${runNames[activeRun] || 'run'} · ${fmt(E.length)} entries · ${fmt(O.length)} observations · ${fmt(T.length)} taxa · ${fmt(P.length)} places · ${fmt(PE.length)} persons · ${fmt(WX.length)} weather reports${src ? ' · ' + src : ''}${range}`;\n"
        "  const vol = $('#vol');\n"
        "  [...vol.querySelectorAll('option')].forEach(o => { if (o.value) o.remove(); });\n"
        "  [...new Set(E.map(e => e.vol).filter(v => v != null))].sort((a, b) => a - b).forEach(v => { const o = document.createElement('option'); o.value = v; const sp = (META.vols || {})[v]; o.textContent = 'Vol. ' + String(v).padStart(2, '0') + (sp ? ' · ' + sp.replace('/', ' – ') : ''); vol.appendChild(o); });\n",
    )

    # Strip the original auto-boot; EXTRA_JS starts the view after a graph is loaded.
    marker = "  renderList();\n  function fromHash()"
    if marker not in rest:
        raise SystemExit("could not find boot marker")
    rest_head, rest_tail = rest.split(marker, 1)
    # keep fromHash function, drop the immediate renderList + initial open
    fromhash_end = rest_tail.find("  window.addEventListener('hashchange', fromHash);")
    if fromhash_end < 0:
        raise SystemExit("could not find hashchange binder")
    fromhash_fn = "  function fromHash()" + rest_tail[:fromhash_end]
    # drop everything after fromHash's closing through })();
    rest = rest_head + fromhash_fn

    if "document.getElementById('loading').remove();" in index_body and "$('#stats').textContent" in index_body:
        if "runNames[activeRun]" not in index_body:
            raise SystemExit("stats/volume rewrite did not apply")
    if "Y0 = core.length" not in index_body:
        raise SystemExit("Y0/Y1 rewrite did not apply")
    ingest = INGEST_HEAD + index_body + "  }\n"
    return LOADER + helpers + ingest + rest + EXTRA_JS


def main() -> None:
    snapshot = SNAPSHOT
    fallback = ROOT / "tools" / "Laubmann-KG_Explorer.html"
    if not snapshot.exists() and fallback.exists() and fallback.stat().st_size > 1_000_000:
        snapshot = fallback
    text = snapshot.read_text(encoding="utf-8", errors="replace")
    data_start = text.find('<script id="data"')
    data_end = text.find("</script>", data_start) + len("</script>")
    head = text[:data_start]
    after = text[data_end:]
    s1 = after.find("<script>")
    e1 = after.find("</script>", s1)
    leaflet = after[s1 : e1 + len("</script>")]
    s2 = after.find("<script>", e1)
    e2 = after.find("</script>", s2)
    app = after[s2 + len("<script>") : e2]

    head = head.replace(
        "<title>Laubmann KG · Explorer v7</title>",
        "<title>Laubmann KG · Explorer (sample runs)</title>",
    )
    head = head.replace("</style>", CSS + "\n</style>")
    head = head.replace(
        '<div id="loading">loading graph …</div>\n<header>',
        '<div id="loading">loading graph …</div>\n<header>',
    )
    if '<div id="runs">' not in head:
        head = head.replace("</header>\n<main>", "</header>\n" + RUNS_BAR + "<main>")
    if 'id="compare"' not in head:
        head = head.replace('<div id="ov"></div>', '<div id="ov"></div>\n    ' + COMPARE_PANEL)

    new_app = transform_app(app)
    out = head + "\n" + leaflet + "\n<script>\n" + new_app + "</script>\n</body>\n</html>\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8")
    ALIAS.write_text(out, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes) and {ALIAS}")


if __name__ == "__main__":
    main()
