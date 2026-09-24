(async function () {
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = n => Number(n || 0).toLocaleString('de-DE');
const LS = 'hog-validation-v1';
const BASE_BY = 'auto-2026-08-19';

// ---------- payload ----------
async function loadPayload() {
  const b64 = $('#data').textContent.trim();
  let bytes;
  try { bytes = await (await fetch('data:application/octet-stream;base64,' + b64)).arrayBuffer(); }
  catch (e) { const bin = atob(b64); bytes = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i); }
  const ds = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(ds).text());
}
let P;
try { P = await loadPayload(); }
catch (e) { $('#loading').textContent = 'Die Daten konnten nicht geladen werden. Bitte eine aktuelle Version von Chrome, Edge oder Firefox verwenden. (' + e.message + ')'; return; }
let DRIVE = {};
try { DRIVE = JSON.parse($('#drive').textContent || '{}'); } catch (e) { DRIVE = {}; }
const E = P.E; // [id, uid, date, vdate, kind, vol, scan, side, place, text, pageid]
$('#exportname').textContent = P.export;

// ---------- state ----------
let S = { who: '', dec: {}, manual: {}, ui: { adv: true } };
try { const raw = localStorage.getItem(LS); if (raw) S = Object.assign(S, JSON.parse(raw)); } catch (e) { }
S.ui = S.ui || { adv: true };
let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try { localStorage.setItem(LS, JSON.stringify(S)); $('#saved').textContent = 'Lokal gespeichert ' + new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }); }
    catch (e) { $('#saved').textContent = 'Speichern im Browser nicht möglich, bitte regelmäßig exportieren'; }
  }, 250);
}
const dget = (task, key) => (S.dec[task] || {})[key];
function dset(task, key, obj) {
  S.dec[task] = S.dec[task] || {};
  if (!obj) delete S.dec[task][key];
  else S.dec[task][key] = Object.assign({}, obj, { by: S.who || '', t: new Date().toISOString() });
  save();
}
$('#who').value = S.who || '';
$('#who').addEventListener('input', e => { S.who = e.target.value.trim(); save(); });

function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('show'), 2200); }

// ---------- vocabularies ----------
const RULES = {
  'gbif-key': 'Gleicher GBIF-Artschlüssel: beide Namen wurden bei GBIF derselben Art zugeordnet (Synonym, alte Bezeichnung oder Schreibvariante).',
  'scientific-name': 'Gleicher wissenschaftlicher Name.',
  'same-key': 'Gleicher Name nach Entfernen von Titeln (Dr., Prof., Lehrer …), Umlaut- und Satzzeichen-Angleichung.',
  'dominant': 'Kurzform wird der häufigsten passenden Vollform zugeordnet.',
  'surname-unique': 'Nur Nachname: es gibt genau eine Person mit diesem Nachnamen.',
  'surname-ambiguous': 'Nur Nachname: mehrere Personen tragen diesen Nachnamen, deshalb nur ein Vorschlag.',
  'initial-unique': 'Initiale + Nachname passt zu genau einem vollen Namen.',
  'initial-ambiguous': 'Initiale + Nachname passt zu mehreren vollen Namen, deshalb nur ein Vorschlag.',
  'wikidata': 'Beide Schreibweisen wurden demselben Wikidata-Objekt zugeordnet.',
  'manual': 'Von Hand ergänzte Zusammenführung (keine Regel hat sie vorgeschlagen).',
  'orthographic': 'Nur Schreibweise: ü/ue, ß/ss, Satzzeichen, Groß/klein, St./Sankt.',
  'similar': 'Ähnliche Schreibweise (Zeichenähnlichkeit ≥ 0,9 bei Orten, ≥ 0,85 bei Habitaten). Häufigste Fehlerquelle: zwei verschiedene Orte mit ähnlichem Namen.',
};
const STATUS_DE = {
  auto: 'automatisch', candidate: 'Vorschlag', manual: 'manuell', 'baseline-only': 'nur alter Vorschlag',
  linked: 'verknüpft', 'linked-broad': 'nur Gattung/übergeordnet', review: 'zu prüfen', no_match: 'fehlt noch', 'linked-nogn': 'ohne GeoNames',
  'multiple-candidates': 'mehrere Kandidaten', 'no-exact-label': 'kein exakter Treffer', 'single-token-name': 'nur ein Namensteil',
  'no-match': 'kein Treffer', 'not-human': 'Treffer ist keine Person',
};
const STATUS_HELP = {
  auto: 'gilt, solange nicht abgelehnt',
  candidate: 'gilt nur nach Zustimmung',
  manual: 'von Hand ergänzt',
  'baseline-only': 'Paar aus dem Abgleich vom 19.08., im aktuellen Export nicht mehr vorhanden',
};
const QA_DE = {
  non_bird: ['Kein Vogel', 'Die Beobachtung wurde entfernt, weil das Modell das Tier nicht als Vogel eingestuft hat.'],
  no_observations: ['Keine Vogelbeobachtung', 'Eintrag ohne Vogelnachweis, aber mit Wetter oder Reise.'],
  empty: ['Leerer Eintrag', 'Keine Beobachtung extrahiert. Möglicherweise ein Segmentierungsfehler.'],
  date_corrected: ['Datum korrigiert', 'Das Eintragsdatum wurde geändert.'],
  date_year_corrected: ['Jahr korrigiert', 'Das Jahr wurde aus der Bandabdeckung oder den Nachbareinträgen korrigiert (OCR-Fehler).'],
  date_out_of_coverage: ['Datum außerhalb des Bandes', 'Das Datum liegt außerhalb des Zeitraums, den der Band abdeckt.'],
  low_confidence_taxon: ['Unsichere Art', 'Die Beobachtung wurde entfernt: Artname nicht auflösbar, Konfidenz niedrig.'],
  nonplace: ['Kein Ort', 'Die Kopfzeile enthält laut Modell keinen verwertbaren Ort.'],
  volume_reassigned: ['Band neu zugeordnet', 'Die Seite wurde einem anderen Band zugeordnet.'],
  date_from_position: ['Datum aus Position', 'Das Datum wurde aus der Position im Band erschlossen.'],
  record_type_conflict: ['Beobachtungstyp widersprüchlich', 'Eigene Beobachtung, obwohl Beobachter oder Zitat genannt ist.'],
  duplicate_entry: ['Doppelter Eintrag', 'Eintrag wurde als Dublette entfernt.'],
  date_out_of_span: ['Datum außerhalb der Tagebuchzeit', 'Eintrag entfernt, das Jahr liegt außerhalb von 1917–1965.'],
  implausible_date: ['Ungültiges Datum', 'Eintrag entfernt, das Datum ist ungültig.'],
};
const KIND_DE = { 'field-day': 'Feldtag', 'species-digest': 'Artenübersicht', 'third-party-report': 'Fremdbericht', other: 'sonstiges' };

// ---------- tasks ----------
const obj = (head, row) => { const o = {}; head.forEach((h, i) => o[h] = row[i] ?? ''); return o; };
const TASKS = [
  { id: 'taxon_merges', group: 'Zusammenführungen', title: 'Arten', type: 'merge', kind: 'taxon', file: 'taxon_merges.csv',
    desc: 'Sind die beiden Vogelnamen dieselbe Art?' },
  { id: 'person_merges', group: 'Zusammenführungen', title: 'Personen', type: 'merge', kind: 'person', file: 'person_merges.csv',
    desc: 'Bezeichnen beide Schreibweisen dieselbe Person?' },
  { id: 'place_merges', group: 'Zusammenführungen', title: 'Orte', type: 'merge', kind: 'place', file: 'place_merges.csv',
    desc: 'Bezeichnen beide Schreibweisen denselben Ort?' },
  { id: 'habitat_merges', group: 'Zusammenführungen', title: 'Habitate', type: 'merge', kind: 'habitat', file: 'habitat_merges.csv',
    desc: 'Bezeichnen beide Schreibweisen denselben Lebensraum?' },
  { id: 'taxon_links', group: 'Verknüpfungen', title: 'Arten → GBIF', type: 'taxonlink', kind: 'taxon', file: 'taxon_link_review.csv', keycol: 'vernacular_de', wcol: 'n_observations',
    desc: 'Passt der GBIF-Eintrag zum Vogelnamen?', on: ['review', 'linked-broad', 'no_match'] },
  { id: 'person_links', group: 'Verknüpfungen', title: 'Personen → Normdaten', type: 'personlink', kind: 'person', file: 'person_link_review.csv', keycol: 'person_name', wcol: 'n_entries',
    desc: 'Wer ist die Person? Wikidata und GND', on: ['multiple-candidates', 'no-exact-label', 'not-human', 'linked'] },
  { id: 'place_links', group: 'Verknüpfungen', title: 'Orte → Normdaten', type: 'placelink', kind: 'place', file: 'place_link_review.csv', keycol: 'place_name', wcol: 'n_uses',
    desc: 'Wo liegt der Ort? Koordinaten, GeoNames, Wikidata', on: ['review', 'no_match', 'linked-nogn'] },
  { id: 'habitat_links', group: 'Verknüpfungen', title: 'Habitate → EUNIS', type: 'habitatlink', kind: 'habitat', file: 'habitat_link_review.csv', keycol: 'habitat_label', wcol: 'n_obs',
    desc: 'Passt die EUNIS-Klasse zur Bezeichnung?', on: ['review', 'no_match'] },
  { id: 'qa_flags', group: 'Qualitätskontrolle', title: 'Qualitätsflags', type: 'qa', file: 'qa_flags.csv',
    desc: 'Hat die automatische Qualitätsprüfung richtig entschieden?' },
];
const TBY = Object.fromEntries(TASKS.map(t => [t.id, t]));
const CAT_ORDER = { candidate: 0, manual: 1, auto: 2, 'baseline-only': 3, review: 0, 'linked-broad': 1, no_match: 2, 'linked-nogn': 2.5, linked: 3,
  'multiple-candidates': 0, 'no-exact-label': 1, 'not-human': 2, 'single-token-name': 5, 'no-match': 6 };

for (const t of TASKS) {
  const D = P.T[t.id];
  t.head = D.head;
  if (t.type === 'merge') {
    t.items = D.rows.map(r => { const o = obj(D.head, r); return { key: o.merge_id, r: o, cat: o.status, w: (+o.n_variant || 0) + (+o.n_canonical || 0), base: D.base[o.merge_id],
      label: o.variant + ' → ' + o.canonical, sub: o.rule + ' · ' + o.n_variant + ' / ' + o.n_canonical }; });
    for (const r of D.bonly) { const o = obj(D.bhead, r); t.items.push({ key: o.merge_id, r: o, cat: 'baseline-only', w: (+o.n_variant || 0) + (+o.n_canonical || 0),
      base: [o.decision, o.reason || ''], bonly: true, label: o.variant + ' → ' + o.canonical, sub: o.rule + ' · ' + o.n_variant + ' / ' + o.n_canonical }); }
    t.on = ['candidate', 'manual', 'auto', 'baseline-only'];
  } else if (t.type === 'personlink') {
    const g = new Map();
    for (const r of D.rows) { const o = obj(D.head, r); const k = o.person_name; if (!g.has(k)) g.set(k, []); g.get(k).push(o); }
    t.items = [...g.entries()].map(([k, rows]) => ({ key: k, rows, r: rows[0], cat: rows[0].rule, w: +rows[0].n_entries || 0, label: k,
      sub: (rows.filter(x => x.qid).length ? rows.filter(x => x.qid).length + ' Kandidat(en)' : 'keine Kandidaten') }));
  } else if (t.type === 'qa') {
    t.items = D.rows.map((r, i) => { const o = obj(D.head, r); return { key: o.entry_id + '|' + o.reason + '|' + o.value, r: o, cat: o.reason, w: 0, ei: D.ei[i],
      label: (QA_DE[o.reason] || [o.reason])[0] + (o.value ? ': ' + o.value : ''), sub: o.entry_id + ' · ' + (o.action === 'excluded' ? 'entfernt' : 'markiert') }; });
    t.on = Object.keys(QA_DE);
  } else {
    t.items = D.rows.map(r => { const o = obj(D.head, r); let sub = '';
      if (t.type === 'taxonlink') sub = o.gbif_canonical_name || o.current_scientific_name || 'kein wiss. Name';
      if (t.type === 'placelink') sub = (o.geonames_name || o.source || '') + (o.country ? ' (' + o.country + ')' : '') + (o.note ? ' · ' + o.note.slice(0, 60) : '');
      if (t.type === 'habitatlink') sub = o.eunis_code ? o.eunis_code + ' ' + o.eunis_label : 'keine Klasse';
      const cat = t.type === 'placelink' && o.status === 'linked' && !o.geonames_id ? 'linked-nogn' : o.status;
      return { key: o[t.keycol], r: o, cat, w: +o[t.wcol] || 0, label: o[t.keycol], sub }; });
  }
  t.cats = {}; for (const it of t.items) t.cats[it.cat] = (t.cats[it.cat] || 0) + 1;
  t.items.sort((a, b) => (CAT_ORDER[a.cat] ?? 4) - (CAT_ORDER[b.cat] ?? 4) || b.w - a.w || String(a.label).localeCompare(String(b.label), 'de'));
  if (t.type === 'qa') t.items.sort((a, b) => a.r.entry_id.localeCompare(b.r.entry_id) || a.r.reason.localeCompare(b.r.reason));
  t.idx = new Map(t.items.map((it, i) => [it.key, i]));
  S.ui.chips = S.ui.chips || {};
  if (!S.ui.chips[t.id] || (S.ui.chipsV || 0) < 2) S.ui.chips[t.id] = t.on.filter(c => t.cats[c]);
}
S.ui.chipsV = 2;
const EUNIS = new Map(P.eunis.map(e => [e[0], e]));

// GBIF: link + German vernacular names, fetched once per key
const GBIF_DE = new Map();
function gbifLink(key, name) {
  if (!key) return esc(name || '');
  return '<a href="https://www.gbif.org/species/' + esc(key) + '" target="_blank" rel="noopener"><i>' + esc(name || key) + '</i> ↗</a> <span class="gbifde" data-gbif="' + esc(key) + '"></span>';
}
async function fillGbifDe() {
  for (const el of document.querySelectorAll('.gbifde[data-gbif]')) {
    const k = el.dataset.gbif;
    try {
      if (!GBIF_DE.has(k)) GBIF_DE.set(k, getJSON('https://api.gbif.org/v1/species/' + k + '/vernacularNames?limit=300')
        .then(j => [...new Set((j.results || []).filter(v => v.language === 'deu').map(v => v.vernacularName))].slice(0, 3)).catch(() => []));
      const names = await GBIF_DE.get(k);
      if (el.isConnected) el.textContent = names.length ? names.join(', ') : '';
    } catch (e) { }
  }
}

// ---------- sidebar ----------
let cur = { task: null, i: -1, list: [], shown: 0 };
function progress(t) {
  let y = 0, n = 0, u = 0; const d = S.dec[t.id] || {};
  for (const it of t.items) { const x = d[it.key]; if (!x) continue; if (x.d === 'y') y++; else if (x.d === 'n') n++; else if (x.d === 'u') u++; }
  return { y, n, u, done: y + n, tot: t.items.length };
}
function renderSide() {
  let h = '<button class="task' + (cur.task ? '' : ' on') + '" data-t=""><div class="t"><span>Übersicht</span><span></span></div></button>';
  let g = '';
  for (const t of TASKS) {
    if (t.group !== g) { g = t.group; h += '<h4>' + esc(g) + '</h4>'; }
    const p = progress(t); const w = x => (100 * x / Math.max(1, p.tot)).toFixed(2) + '%';
    h += '<button class="task' + (cur.task === t ? ' on' : '') + '" data-t="' + t.id + '"><div class="t"><span>' + esc(t.title) + '</span><span>' + fmt(p.done + p.u) + ' / ' + fmt(p.tot) + '</span></div>'
      + '<div class="bar"><i class="y" style="width:' + w(p.y) + '"></i><i class="n" style="width:' + w(p.n) + '"></i><i class="u" style="width:' + w(p.u) + '"></i></div></button>';
  }
  h += '<button class="task" data-t="__corr"><div class="t"><span>Wertkorrekturen</span><span>' + fmt(S.corr.length) + '</span></div></button>';
  h += '<div class="foot">Export ' + esc(P.export) + '<br>Stand der Oberfläche ' + esc(P.built) + '</div>';
  $('#side').innerHTML = h;
}
$('#side').addEventListener('click', e => { const b = e.target.closest('.task'); if (!b) return; if (b.dataset.t === '__corr') return showCorrList(); openTask(b.dataset.t ? TBY[b.dataset.t] : null); });

// ---------- queue ----------
function openTask(t, keepItem) {
  cur.task = t; S.ui.task = t ? t.id : '';
  save();
  renderSide();
  if (!t) { $('#qtitle').textContent = 'Übersicht'; $('#qdesc').textContent = 'Aufgabe links auswählen.'; $('#qchips').innerHTML = ''; $('#qlist').innerHTML = ''; $('#qcount').textContent = ''; renderOverview(); return; }
  $('#qtitle').textContent = t.group + ': ' + t.title;
  $('#qdesc').textContent = t.desc;
  $('#qsearch').value = (S.ui.q || {})[t.id] || '';
  $('#qshow').value = (S.ui.show || {})[t.id] || 'open';
  renderChips();
  buildList();
  const want = keepItem ?? (S.ui.item || {})[t.id];
  let pos = want != null ? cur.list.indexOf(t.idx.get(want)) : -1;
  if (pos < 0) pos = 0;
  select(cur.list.length ? pos : -1);
}
function renderChips() {
  const t = cur.task; const on = new Set(S.ui.chips[t.id]);
  const cats = Object.keys(t.cats).sort((a, b) => (CAT_ORDER[a] ?? 4) - (CAT_ORDER[b] ?? 4) || t.cats[b] - t.cats[a]);
  $('#qchips').innerHTML = cats.map(c => '<span class="chip' + (on.has(c) ? ' on' : '') + '" data-c="' + esc(c) + '" title="' + esc(STATUS_HELP[c] || (QA_DE[c] || [])[1] || '') + '">'
    + esc(t.type === 'qa' ? (QA_DE[c] || [c])[0] : (STATUS_DE[c] || c)) + '<b>' + fmt(t.cats[c]) + '</b></span>').join('');
}
$('#qchips').addEventListener('click', e => {
  const c = e.target.closest('.chip'); if (!c) return; const t = cur.task; const s = new Set(S.ui.chips[t.id]);
  s.has(c.dataset.c) ? s.delete(c.dataset.c) : s.add(c.dataset.c); S.ui.chips[t.id] = [...s]; save(); renderChips(); buildList(); select(cur.list.length ? 0 : -1);
});
function matchesShow(t, it, show) {
  const d = dget(t.id, it.key); const dd = d && d.d;
  if (show === 'open') return !dd;
  if (show === 'done') return dd === 'y' || dd === 'n';
  if (show === 'u') return dd === 'u';
  return true;
}
function buildList() {
  const t = cur.task; const on = new Set(S.ui.chips[t.id]); const q = $('#qsearch').value.trim().toLowerCase();
  const show = $('#qshow').value;
  cur.list = [];
  t.items.forEach((it, i) => {
    if (!on.has(it.cat)) return;
    if (q && !(String(it.label).toLowerCase().includes(q) || String(it.sub).toLowerCase().includes(q))) return;
    if (!matchesShow(t, it, show)) return;
    cur.list.push(i);
  });
  cur.shown = 0; $('#qlist').innerHTML = ''; $('#qlist').scrollTop = 0; renderMore();
  $('#qcount').textContent = fmt(cur.list.length) + ' Einträge';
}
function qiHtml(pos) {
  const t = cur.task; const it = t.items[cur.list[pos]]; const d = dget(t.id, it.key);
  return '<div class="qi' + (pos === cur.i ? ' on' : '') + '" data-p="' + pos + '"><span class="dot ' + (d && d.d || '') + '"></span><div><div class="l1">' + esc(it.label) + '</div><div class="l2">' + esc(it.sub) + '</div></div><div class="num">'
    + (it.w ? fmt(it.w) + '×' : '') + '</div></div>';
}
function renderMore() {
  const end = Math.min(cur.list.length, cur.shown + 150); let h = '';
  for (let p = cur.shown; p < end; p++) h += qiHtml(p);
  $('#qlist').insertAdjacentHTML('beforeend', h); cur.shown = end;
  const m = $('#qlist .qmore'); if (m) m.remove();
  if (cur.shown < cur.list.length) $('#qlist').insertAdjacentHTML('beforeend', '<div class="qmore">weitere werden beim Scrollen geladen …</div>');
  if (!cur.list.length) $('#qlist').innerHTML = '<div class="qmore">Keine Einträge in dieser Auswahl.' + ($('#qshow').value === 'open' ? ' Alles erledigt 🎉' : '') + '</div>';
}
$('#qlist').addEventListener('scroll', e => { const el = e.target; if (el.scrollTop + el.clientHeight > el.scrollHeight - 300 && cur.shown < cur.list.length) renderMore(); });
$('#qlist').addEventListener('click', e => { const q = e.target.closest('.qi'); if (q) select(+q.dataset.p); });
let qTimer; $('#qsearch').addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(() => { S.ui.q = S.ui.q || {}; S.ui.q[cur.task.id] = $('#qsearch').value; save(); buildList(); select(cur.list.length ? 0 : -1); }, 200); });
$('#qshow').addEventListener('change', () => { S.ui.show = S.ui.show || {}; S.ui.show[cur.task.id] = $('#qshow').value; save(); buildList(); select(cur.list.length ? 0 : -1); });
function refreshQi(pos) {
  const el = $('#qlist .qi[data-p="' + pos + '"]'); if (!el) return;
  const tmp = document.createElement('div'); tmp.innerHTML = qiHtml(pos); el.replaceWith(tmp.firstChild);
}
function select(pos) {
  const old = cur.i; cur.i = pos;
  document.querySelectorAll('#qlist .qi.on').forEach(el => el.classList.remove('on'));
  if (pos < 0) { $('#detail').innerHTML = '<div class="empty">Keine Einträge in dieser Auswahl.</div>'; return; }
  while (pos >= cur.shown && cur.shown < cur.list.length) renderMore();
  const el = $('#qlist .qi[data-p="' + pos + '"]'); if (el) { el.classList.add('on'); el.scrollIntoView({ block: 'nearest' }); }
  const it = cur.task.items[cur.list[pos]];
  S.ui.item = S.ui.item || {}; S.ui.item[cur.task.id] = it.key; save();
  renderDetail(it);
  $('#detail').scrollTop = 0;
}
function step(dir) { if (!cur.task || !cur.list.length) return; const p = Math.max(0, Math.min(cur.list.length - 1, cur.i + dir)); if (p !== cur.i) select(p); }
function nextOpen() {
  // keep the item in the list (so the position stays stable) and move on
  const t = cur.task;
  for (let p = cur.i + 1; p < cur.list.length; p++) { const it = t.items[cur.list[p]]; const d = dget(t.id, it.key); if (!d || !d.d) return select(p); }
  if (cur.i < cur.list.length - 1) return select(cur.i + 1);
  toast('Ende der Liste erreicht');
}

// ---------- value corrections ----------
// A misread species or place name ("Reh" for Birkhenne, heading "Rauchschwalben" for Kaufbeuren) is fixed
// at the value; exported as review/value_corrections.csv and applied by the pipeline before QA.
S.corr = (S.corr || []).filter(c => c.scope !== 'all' && c.entry_uid);   // corrections apply to one entry only
const KNOWN = { taxon: new Map(), place: new Map() };
{ const T1 = P.T.taxon_links; for (const r of T1.rows) { const o = obj(T1.head, r); KNOWN.taxon.set(o.vernacular_de.toLowerCase(), { name: o.vernacular_de, n: +o.n_observations || 0, sci: o.gbif_canonical_name || o.current_scientific_name }); }
  const T2 = P.T.place_links; for (const r of T2.rows) { const o = obj(T2.head, r); KNOWN.place.set(o.place_name.toLowerCase(), { name: o.place_name, n: +o.n_uses || 0, geo: !!o.lat }); }
  const dl = k => '<datalist id="dl-' + k + '">' + [...KNOWN[k].values()].sort((x, y) => y.n - x.n).map(v => '<option value="' + esc(v.name) + '">').join('') + '</datalist>';
  document.body.insertAdjacentHTML('beforeend', dl('taxon') + dl('place')); }
const QA_KIND = { non_bird: 'taxon', low_confidence_taxon: 'taxon', record_type_conflict: 'taxon', nonplace: 'place' };
function corrContext() {
  const t = cur.task; if (!t || cur.i < 0) return null; const it = t.items[cur.list[cur.i]];
  if (t.type === 'qa') { const k = QA_KIND[it.r.reason]; return k && it.r.value ? { kind: k, olds: [it.r.value] } : null; }
  if (t.kind !== 'taxon' && t.kind !== 'place') return null;
  return { kind: t.kind, olds: t.type === 'merge' ? [it.r.variant, it.r.canonical] : [it.label] };
}
const lc = s => String(s || '').toLowerCase();
function corrsFor(entryUid, olds) {
  return S.corr.filter(c => entryUid && c.entry_uid === entryUid && olds.some(o => lc(o) === lc(c.old)));
}
function corrLine(c) {
  return '<div class="pc">✎ Korrektur: „' + esc(c.old) + '“ → „<b>' + esc(c.new) + '</b>“' + (c.sci ? ' <i>' + esc(c.sci) + '</i>' : '') + (c.kind === 'taxon' && !c.is_bird ? ' (kein Vogel)' : '')
    + (c.by ? ' <span class="muted">' + esc(c.by) + '</span>' : '') + ' <button class="lbtn" data-delcorr="' + esc(c.id) + '">entfernen</button></div>';
}
function corrForm(kind, olds, entryUid, entryId) {
  return '<div class="corrform" data-kind="' + kind + '" data-uid="' + esc(entryUid || '') + '" data-eid="' + esc(entryId || '') + '">'
    + '<div class="cfh">' + (kind === 'taxon' ? 'Artname' : 'Ortsname') + ' in ' + esc(entryId) + ' korrigieren</div>'
    + '<div class="row"><span class="muted small">gelesen</span>' + (olds.length > 1 ? '<select class="c-old">' + olds.map(o => '<option>' + esc(o) + '</option>').join('') + '</select>' : '<input type="text" class="c-old" value="' + esc(olds[0] || '') + '" readonly>')
    + '<span>→</span><span class="muted small">richtig</span><input type="text" class="c-new grow" list="dl-' + kind + '" placeholder="' + (kind === 'taxon' ? 'z. B. Birkhenne' : 'z. B. Kaufbeuren') + '"></div>'
    + '<div class="c-hint small muted"></div>'
    + (kind === 'taxon' ? '<div class="row"><span class="muted small">wiss. Name</span><input type="text" class="c-sci" placeholder="optional, z. B. Lyrurus tetrix" style="width:220px"><label class="small"><input type="checkbox" class="c-bird" checked> ist ein Vogel</label></div>' : '')
    + '<div class="row"><input type="text" class="c-note grow" placeholder="Anmerkung (optional)"><button class="dbtn y c-save">Korrektur speichern</button><button class="lbtn c-cancel">abbrechen</button></div></div>';
}
function corrHint(form) {
  const kind = form.dataset.kind, v = lc(form.querySelector('.c-new').value.trim()), h = form.querySelector('.c-hint');
  if (!v) return; const k = KNOWN[kind].get(v);
  if (k) h.innerHTML = '<span class="tag ok">bekannt</span> ' + fmt(k.n) + (kind === 'taxon' ? ' Beobachtungen' + (k.sci ? ', <i>' + esc(k.sci) + '</i>' : ', noch ohne wiss. Namen') : ' Nennungen' + (k.geo ? ', mit Koordinaten' : ', ohne Koordinaten'));
  else h.innerHTML = '<span class="tag warn">neu</span> ' + (kind === 'taxon' ? 'noch nicht im Graph, bitte wiss. Namen angeben' : 'noch nicht im Graph');
}
function saveCorr(form) {
  const kind = form.dataset.kind, oldv = form.querySelector('.c-old').value.trim(), newv = form.querySelector('.c-new').value.trim();
  if (!newv) return toast('Bitte den richtigen Namen eintragen');
  if (newv === oldv) return toast('Der neue Name ist gleich dem alten');
  if (!form.dataset.uid) return toast('Kein Eintrag gewählt');
  const c = { id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), kind, scope: 'entry', old: oldv, new: newv,
    entry_uid: form.dataset.uid, entry_id: form.dataset.eid,
    sci: kind === 'taxon' ? (form.querySelector('.c-sci').value.trim()) : '', is_bird: kind === 'taxon' ? form.querySelector('.c-bird').checked : true,
    note: form.querySelector('.c-note').value.trim(), by: S.who || '', t: new Date().toISOString() };
  if (kind === 'taxon' && !c.sci && !KNOWN.taxon.has(lc(newv)) && !confirm('„' + newv + '“ kommt im Graph noch nicht vor und hat keinen wissenschaftlichen Namen. Trotzdem speichern?')) return;
  S.corr = S.corr.filter(x => !(x.kind === c.kind && lc(x.old) === lc(c.old) && x.entry_uid === c.entry_uid));
  S.corr.push(c); save(); toast('Korrektur gespeichert');
  const t = cur.task; const it = t.items[cur.list[cur.i]];
  if (t.type === 'qa' && !(dget(t.id, it.key) || {}).d) { dset(t.id, it.key, { d: 'n', note: (dget(t.id, it.key) || {}).note || '', corr: (kind === 'taxon' ? 'Art: ' : 'Ort: ') + oldv + ' -> ' + newv }); refreshQi(cur.i); }
  renderSide(); renderDetail(it);
}
function showCorrList() {
  const rows = S.corr.slice().sort((a, b) => (b.t || '').localeCompare(a.t || ''));
  $('#helpBody').innerHTML = '<button class="lbtn x" data-close>Schließen ✕</button><h2>Wertkorrekturen</h2>'
    + (rows.length ? '<table><tr><td><b>Art</b></td><td><b>gelesen → richtig</b></td><td><b>Eintrag</b></td><td><b>von</b></td><td></td></tr>' + rows.map(c => '<tr><td>' + (c.kind === 'taxon' ? 'Art' : 'Ort') + '</td><td>„' + esc(c.old) + '“ → „<b>' + esc(c.new) + '</b>“' + (c.sci ? ' <i>' + esc(c.sci) + '</i>' : '') + (c.note ? '<br><span class="muted small">' + esc(c.note) + '</span>' : '') + '</td><td>' + esc(c.entry_id) + '</td><td>' + esc(c.by) + '</td><td><button class="lbtn" data-delcorr="' + esc(c.id) + '">entfernen</button></td></tr>').join('') + '</table>' : '<p class="muted">Noch keine Korrekturen.</p>');
  $('#ovHelp').classList.add('show');
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-corr]');
  if (b) { const ctx = corrContext(); if (!ctx) return; const i = +b.dataset.corr;
    const host = b.closest('.psg'); const ex = host.querySelector('.corrform'); if (ex) { ex.remove(); return; }
    host.querySelector('.ph').insertAdjacentHTML('afterend', corrForm(ctx.kind, ctx.olds, E[i][1], E[i][0]));
    host.querySelector('.corrform .c-new').focus(); return; }
  if (e.target.closest('.c-save')) return saveCorr(e.target.closest('.corrform'));
  if (e.target.closest('.c-cancel')) return e.target.closest('.corrform').remove();
  const d = e.target.closest('[data-delcorr]');
  if (d) { if (!confirm('Korrektur entfernen?')) return; S.corr = S.corr.filter(c => c.id !== d.dataset.delcorr); save(); renderSide();
    if ($('#ovHelp').classList.contains('show') && d.closest('#helpBody')) showCorrList();
    if (cur.task && cur.i >= 0) renderDetail(cur.task.items[cur.list[cur.i]]); }
});
document.addEventListener('input', e => { const f = e.target.closest('.corrform'); if (f && e.target.classList.contains('c-new')) corrHint(f); });
document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.closest && e.target.closest('.corrform') && e.target.tagName === 'INPUT') { e.preventDefault(); saveCorr(e.target.closest('.corrform')); } });

// ---------- passages ----------
function termRe(name, loose) {
  const toks = String(name).toLowerCase().match(/[\p{L}\p{N}_]+/gu);
  if (!toks) return null;
  const src = toks.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^\\p{L}\\p{N}_]*');
  try { return new RegExp('(?<![\\p{L}\\p{N}_])' + src + (loose ? '' : '(?![\\p{L}\\p{N}_])'), 'giu'); } catch (e) { return null; }
}
function highlight(text, terms) {
  // terms: [[name, cls]] — collect match ranges, longest first wins
  const ranges = [];
  for (const [name, cls, loose] of terms) { const re = termRe(name, loose); if (!re) continue; let m; while ((m = re.exec(text))) { if (!m[0].length) { re.lastIndex++; continue; } ranges.push([m.index, m.index + m[0].length, cls]); } }
  ranges.sort((a, b) => a[0] - b[0] || (b[1] - b[0]) - (a[1] - a[0]));
  let out = '', pos = 0;
  for (const [s, e, c] of ranges) { if (s < pos) continue; out += esc(text.slice(pos, s)) + '<mark' + (c ? ' class="' + c + '"' : '') + '>' + esc(text.slice(s, e)) + '</mark>'; pos = e; }
  return out + esc(text.slice(pos));
}
function snippet(text, terms, full) {
  if (full || text.length <= 900) return { html: highlight(text, terms), cut: false };
  let first = -1, last = -1;
  for (const [name, , loose] of terms) { const re = termRe(name, loose); if (!re) continue; const m = re.exec(text); if (m && (first < 0 || m.index < first)) { first = m.index; last = m.index + m[0].length; } }
  if (first < 0) { return { html: highlight(text.slice(0, 500), terms) + ' …', cut: true }; }
  let s = Math.max(0, first - 380), e = Math.min(text.length, last + 380);
  if (s > 0) { const sp = text.indexOf(' ', s); if (sp > 0 && sp < first) s = sp + 1; }
  if (e < text.length) { const sp = text.lastIndexOf(' ', e); if (sp > last) e = sp; }
  return { html: (s > 0 ? '… ' : '') + highlight(text.slice(s, e), terms) + (e < text.length ? ' …' : ''), cut: true };
}
function entryHead(i) {
  const e = E[i]; const drive = DRIVE[e[10]];
  const scan = e[6] != null ? 'Band ' + e[5] + ', Scan ' + e[6] + (e[7] === 'L' ? ' links' : e[7] === 'R' ? ' rechts' : '') : 'Band ' + e[5];
  return '<b>' + esc(e[3] || e[2] || 'ohne Datum') + '</b>' + (e[2] && e[3] !== e[2] ? '<span class="muted">' + esc(e[2]) + '</span>' : '')
    + (e[8] ? '<span>' + esc(e[8]) + '</span>' : '') + '<span class="sp"></span><span class="muted">' + esc(e[0]) + ' · ' + esc(scan) + (e[4] && e[4] !== 'field-day' ? ' · ' + esc(KIND_DE[e[4]] || e[4]) : '') + '</span>'
    + (drive ? '<button class="lbtn" data-scan="' + i + '">Scan</button>' : '')
    + (corrContext() ? '<button class="lbtn" data-corr="' + i + '" title="Falsch gelesenen Namen in diesem Eintrag korrigieren">✎ korrigieren</button>' : '');
}
function psgHtml(i, note, terms, full) {
  const e = E[i]; const sn = snippet(e[9] || '', terms, full);
  const ctx = corrContext();
  const cl = ctx ? corrsFor(e[1], ctx.olds).map(corrLine).join('') : '';
  return '<div class="psg" data-e="' + i + '"><div class="ph">' + entryHead(i) + '</div>' + cl + '<div class="pb">' + (sn.html || '<span class="muted">(kein Text)</span>') + '</div>'
    + (note ? '<div class="pn">Beobachtung: ' + highlight(note, terms) + '</div>' : '')
    + (sn.cut || full ? '<div class="pn"><button class="more" data-full="' + (full ? 0 : 1) + '">' + (full ? 'Ausschnitt zeigen' : 'ganzen Eintrag zeigen') + '</button></div>' : '') + '</div>';
}
function ctxBlock(kind, name, terms, color) {
  if (kind === 'taxon' || kind === 'habitat') terms = terms.map(x => [x[0], x[1], 1]);   // inflected forms: Lachmöwen, Schwalben-Kolonie
  const c = P.C[kind + '|' + name];
  const head = '<div class="colh">' + (color ? '<span class="sw" style="background:' + color + '"></span>' : '') + '<b>' + esc(name) + '</b>'
    + (c ? '<span class="muted">in ' + fmt(c.n) + ' Einträgen gefunden' + (c.n > c.e.length ? ', ' + c.e.length + ' Beispiele über die Jahre verteilt' : '') + '</span>' : '') + '</div>';
  if (!c || !c.e.length) return head + '<div class="muted small" style="padding:6px 0 10px">Keine Belegstelle im Text gefunden (z. B. Abkürzung oder nur in Kopfzeilen).</div>';
  return head + '<div data-terms="' + esc(JSON.stringify(terms)) + '">' + c.e.map(([i, note]) => psgHtml(i, note, terms, false)).join('') + '</div>';
}
document.addEventListener('click', e => {
  const m = e.target.closest('button.more');
  if (m) { const card = m.closest('.psg'); const terms = JSON.parse(card.parentElement.dataset.terms || '[]'); const i = +card.dataset.e;
    const noteEl = card.querySelector('.pn'); const note = noteEl && noteEl.textContent.startsWith('Beobachtung: ') ? noteEl.textContent.slice(13) : '';
    const tmp = document.createElement('div'); tmp.innerHTML = psgHtml(i, note, terms, m.dataset.full === '1'); card.replaceWith(tmp.firstChild); return; }
  const s = e.target.closest('[data-scan]'); if (s) openScan(+s.dataset.scan);
});

// ---------- scan viewer ----------
function openScan(i) {
  const e = E[i]; const id = DRIVE[e[10]]; if (!id) return;
  $('#scantitle').textContent = 'Band ' + e[5] + ', Scan ' + e[6] + ' ' + (e[7] || '') + '  ·  ' + e[0];
  $('#scanopen').href = 'https://drive.google.com/file/d/' + id + '/view';
  $('#scanbody').innerHTML = '<div class="msg">Scan wird geladen …</div>';
  const img = new Image(); img.alt = 'Scan';
  img.onload = () => { $('#scanbody').innerHTML = ''; $('#scanbody').appendChild(img); };
  img.onerror = () => { $('#scanbody').innerHTML = '<div class="msg">Das Bild konnte nicht geladen werden. Bitte im Browser bei Google angemeldet sein (Konto mit Zugriff auf den Ordner HistOrniGraph_output) oder den Scan über „In Drive öffnen“ ansehen.</div>'; };
  img.src = 'https://drive.google.com/thumbnail?id=' + id + '&sz=w2000';
  $('#scanpane').classList.add('show');
}
$('#scanclose').onclick = () => $('#scanpane').classList.remove('show');
$('#scanzoom').onclick = () => { const i = $('#scanbody img'); if (i) i.classList.toggle('z'); };

// ---------- detail ----------
let map = null;
function decisionBar(t, it, opts) {
  const d = dget(t.id, it.key) || {};
  const b = (k, label, key, dis) => '<button class="dbtn ' + k + (d.d === k ? ' on' : '') + '" data-d="' + k + '"' + (dis ? ' disabled title="' + esc(dis) + '"' : '') + '>' + label + ' <kbd>' + key + '</kbd></button>';
  return '<div class="decide">' + b('y', opts.y, 'Y', opts.yDisabled) + b('n', opts.n, 'N') + b('u', 'Unsicher', 'U')
    + (d.d ? '<button class="dbtn clear" data-d="">Zurücksetzen</button>' : '') + '</div>'
    + '<textarea class="note" id="note" placeholder="Anmerkung (optional)">' + esc(d.note || '') + '</textarea>'
    + '<div class="status-line">' + (d.d ? 'Entschieden' + (d.by ? ' von ' + esc(d.by) : '') + ' am ' + new Date(d.t).toLocaleString('de-DE') : 'Noch nicht entschieden') + '</div>';
}
function frame(t, it, inner) {
  const pos = cur.i + 1;
  return '<div class="dwrap"><div class="crumb"><span>' + esc(t.group + ' · ' + t.title) + '</span><span>' + fmt(pos) + ' von ' + fmt(cur.list.length) + '</span>'
    + '<span class="nav"><button class="nbtn" data-nav="-1" title="Vorheriger (K oder ↑)">↑ zurück</button><button class="nbtn" data-nav="1" title="Nächster (J oder ↓)">weiter ↓</button></span></div>' + inner
    + '<div class="kbdrow"><kbd>Y</kbd> <kbd>N</kbd> <kbd>U</kbd> entscheiden · <kbd>J</kbd>/<kbd>K</kbd> oder <kbd>↓</kbd>/<kbd>↑</kbd> blättern · <kbd>/</kbd> suchen · <kbd>X</kbd> zurücksetzen'
    + (t.type === 'personlink' ? ' · <kbd>1</kbd>–<kbd>9</kbd> Kandidat wählen' : '')
    + ' · <label><input type="checkbox" id="adv"' + (S.ui.adv ? ' checked' : '') + '> nach Entscheidung automatisch weiter</label></div></div>';
}
function baseLine(it) {
  if (!it.base) return '';
  const [d, reason] = it.base;
  const lab = d === 'y' ? 'zusammenführen' : d === 'n' ? 'getrennt lassen' : d;
  return '<div class="sugg" title="maschinell, ungeprüft; gilt, solange hier nichts entschieden wird"><b>Maschineller Vorschlag (19.08.):</b> ' + esc(lab) + (reason ? ' <span class="muted">· ' + esc(reason) + '</span>' : '') + '</div>';
}
function mergeDetail(t, it) {
  const r = it.r;
  const effect = it.bonly ? STATUS_HELP['baseline-only'] : STATUS_HELP[r.status] || '';
  const gm = t.kind === 'taxon' && (r.detail || '').match(/gbif:(\d+)\s*·\s*(.*)/);
  const card = '<div class="card"><div class="cb">'
    + '<div class="q">Dieselbe ' + ({ taxon: 'Art', person: 'Person', place: 'Örtlichkeit', habitat: 'Lebensraumbezeichnung' }[t.kind]) + '?</div>'
    + '<div class="pair"><div class="side-a"><div class="lab">Variante</div><div class="nm">' + esc(r.variant) + '</div><div class="ct">' + fmt(r.n_variant) + '× im Graph</div></div><div class="mid">→</div>'
    + '<div class="side-b"><div class="lab">wird zu (kanonisch)</div><div class="nm">' + esc(r.canonical) + '</div><div class="ct">' + fmt(r.n_canonical) + '× im Graph</div></div></div>'
    + '<dl class="facts"><dt>Regel</dt><dd><span class="tag" title="' + esc(RULES[r.rule] || '') + '">' + esc(r.rule) + '</span> <span class="tag" title="' + esc(effect) + '">' + esc(STATUS_DE[it.cat] || it.cat) + '</span></dd>'
    + (gm ? '<dt>GBIF</dt><dd>' + gbifLink(gm[1], gm[2]) + '</dd>' : r.detail ? '<dt>Detail</dt><dd>' + esc(r.detail) + '</dd>' : '') + '</dl>'
    + baseLine(it) + '</div><div class="cb" style="border-top:1px solid var(--line)">'
    + decisionBar(t, it, { y: 'Zusammenführen', n: 'Getrennt lassen' }) + '</div></div>';
  const terms = [[r.variant, ''], [r.canonical, 'b']];
  const ev = '<div class="card"><div class="ch"><h3>Belegstellen im Tagebuch</h3><span class="small muted">gelb = Variante, blau = kanonischer Name</span></div><div class="cb"><div class="cols">'
    + '<div>' + ctxBlock(t.kind, r.variant, terms, 'var(--hl1)') + '</div><div>' + ctxBlock(t.kind, r.canonical, terms, 'var(--hl2)') + '</div></div></div></div>';
  const man = '<div class="card"><div class="ch"><h3>Fehlende Zusammenführung</h3></div><div class="cb"><div class="row">'
    + '<input type="text" id="manV" placeholder="Variante"><span>→</span><input type="text" id="manC" placeholder="kanonischer Name"><button class="lbtn" id="manAdd">hinzufügen</button></div>'
    + manualList(t) + '</div></div>';
  return card + ev + man;
}
function manualList(t) {
  const L = S.manual[t.id] || []; if (!L.length) return '';
  return '<div style="margin-top:8px">' + L.map((m, i) => '<div class="small">' + esc(m.variant) + ' → ' + esc(m.canonical) + ' <span class="muted">(' + esc(m.by || '') + ')</span> <button class="lbtn" data-delman="' + i + '">entfernen</button></div>').join('') + '</div>';
}
function taxonLinkDetail(t, it) {
  const r = it.r; const d = dget(t.id, it.key) || {}; const fix = d.fix;
  const key = fix ? fix.gbif_key : r.gbif_key;
  const card = '<div class="card"><div class="cb"><div class="q">' + esc(r.vernacular_de) + '<span class="arrow">→</span>' + (r.gbif_canonical_name ? '<i>' + esc(r.gbif_canonical_name) + '</i>' : '<span class="muted">kein GBIF-Eintrag</span>') + '</div>'
    + '<div class="qsub">' + fmt(r.n_observations) + ' Beobachtungen · <span class="tag' + (r.status === 'linked' ? ' ok' : ' warn') + '">' + esc(STATUS_DE[r.status] || r.status) + '</span></div>'
    + '<dl class="facts"><dt>Wiss. Name im Graph</dt><dd>' + (r.current_scientific_name ? '<i>' + esc(r.current_scientific_name) + '</i>' : '—') + '</dd>'
    + (r.llm_scientific_name ? '<dt>Vorschlag Sprachmodell</dt><dd><i>' + esc(r.llm_scientific_name) + '</i> (Konfidenz ' + esc(r.llm_confidence) + ')</dd>' : '')
    + '<dt>GBIF</dt><dd>' + (r.gbif_key ? gbifLink(r.gbif_key, r.gbif_canonical_name) + ' <span class="muted small">' + esc(r.gbif_match_type) + ' ' + esc(r.gbif_confidence) + '</span>'
      + (r.gbif_match_type === 'HIGHERRANK' ? ' <span class="tag warn">nur übergeordnete Ebene</span>' : '') : '—') + '</dd></dl>'
    + '</div><div class="cb" style="border-top:1px solid var(--line)">' + decisionBar(t, it, { y: fix ? 'Korrektur übernehmen' : 'Zuordnung korrekt', n: 'Falsch / keine Zuordnung', yDisabled: key ? '' : 'Erst unten eine GBIF-Art auswählen' })
    + '<div class="fixbox"><h5>GBIF-Suche</h5><div class="row"><input type="text" class="grow" id="gq" value="' + esc(r.llm_scientific_name || r.current_scientific_name || r.vernacular_de) + '"><button class="lbtn" id="gbtn">Suchen</button>'
    + '<a class="lbtn" target="_blank" rel="noopener" href="https://www.gbif.org/species/search?q=' + encodeURIComponent(r.vernacular_de) + '">auf gbif.org</a></div><div id="gres"></div>'
    + (fix ? '<div class="fixed">Gewählt: ' + gbifLink(fix.gbif_key, fix.gbif_canonical_name) + ' <button class="lbtn" id="unfix">verwerfen</button></div>' : '') + '</div></div></div>';
  const terms = [[r.vernacular_de, '']];
  return card + '<div class="card"><div class="ch"><h3>Belegstellen im Tagebuch</h3></div><div class="cb">' + ctxBlock('taxon', r.vernacular_de, terms) + '</div></div>';
}
function personLinkDetail(t, it) {
  const d = dget(t.id, it.key) || {}; const r = it.r;
  const cands = it.rows.filter(x => x.qid);
  const chosen = d.qid || null;
  let list = cands.map((c, k) => '<div class="cand' + (chosen === c.qid ? ' on' : '') + '" data-qid="' + esc(c.qid) + '"><span class="k">' + (k < 9 ? k + 1 : '') + '</span><div><div class="cl">' + esc(c.wd_label) + '</div><div class="cd">' + esc(c.wd_description || 'keine Beschreibung') + '</div></div>'
    + '<a class="ci" href="https://www.wikidata.org/wiki/' + esc(c.qid) + '" target="_blank" rel="noopener">' + esc(c.qid) + ' ↗</a></div>').join('');
  if (d.d === 'y' && d.qid && !cands.some(c => c.qid === d.qid)) list += '<div class="cand on"><span class="k">+</span><div><div class="cl">' + esc(d.wd_label || d.qid) + '</div><div class="cd">' + esc(d.wd_description || 'selbst gesucht') + '</div></div><a class="ci" href="https://www.wikidata.org/wiki/' + esc(d.qid) + '" target="_blank" rel="noopener">' + esc(d.qid) + ' ↗</a></div>';
  const card = '<div class="card"><div class="cb"><div class="q">' + esc(r.person_name) + '</div>'
    + '<div class="qsub">in ' + fmt(r.n_entries) + ' Einträgen · <span class="tag' + (r.rule === 'linked' ? ' ok' : ' warn') + '">' + esc(STATUS_DE[r.rule] || r.rule) + '</span></div>'
    + '<div class="subh">Wikidata</div><div class="cands">' + (list || '<div class="muted small">keine Kandidaten</div>') + '</div>'
    + '<div class="subh">GND</div>' + (d.gnd ? '<div class="cand on"><span class="k">✓</span><div><div class="cl">' + esc(d.gnd_label || d.gnd) + '</div><div class="cd">' + esc(d.gnd_info || '') + '</div></div><span><a class="ci" href="https://d-nb.info/gnd/' + esc(d.gnd) + '" target="_blank" rel="noopener">' + esc(d.gnd) + ' ↗</a> <button class="lbtn" id="gndclear">entfernen</button></span></div>' : '<div class="muted small">noch keine GND</div>')
    + '</div><div class="cb" style="border-top:1px solid var(--line)">' + decisionBar(t, it, { y: 'Verknüpfen', n: 'Keine passt', yDisabled: chosen || d.gnd ? '' : 'Erst Wikidata-Kandidat oder GND wählen' })
    + '<div class="fixbox"><h5>Suchen</h5><div class="row"><input type="text" class="grow" id="wq" value="' + esc(r.person_name.replace(/^(Prof\.|Dr\.|Herr|Frau|Frl\.|Lehrer|Pfarrer|Oberförster|Förster)\s+/g, '')) + '"><button class="lbtn" id="wbtn">Wikidata</button><button class="lbtn" id="gndbtn">GND</button></div>'
    + '<div class="row" style="margin-top:6px"><input type="text" id="wqid" placeholder="QID, z. B. Q12345" style="width:170px"><button class="lbtn" id="wqidbtn">übernehmen</button><input type="text" id="gndid" placeholder="GND-ID oder d-nb.info-Link" style="width:220px"><button class="lbtn" id="gndidbtn">übernehmen</button></div><div id="wres"></div></div></div></div>';
  return card + '<div class="card"><div class="ch"><h3>Belegstellen im Tagebuch</h3></div><div class="cb">' + ctxBlock('person', r.person_name, [[r.person_name, '']]) + '</div></div>';
}
function placeLinkDetail(t, it) {
  const r = it.r; const d = dget(t.id, it.key) || {}; const fix = d.fix;
  const has = r.lat !== '' || (fix && fix.lat);
  const card = '<div class="card"><div class="cb"><div class="q">' + esc(r.place_name) + '</div>'
    + '<div class="qsub">' + fmt(r.n_uses) + ' Nennungen' + (r.kind ? ' · Art: ' + esc(r.kind) : '') + ' · <span class="tag' + (r.status === 'linked' ? ' ok' : ' warn') + '">' + esc(STATUS_DE[r.status] || r.status) + '</span> Konfidenz ' + esc(r.confidence) + '</div>'
    + '<dl class="facts">' + (r.lat ? '<dt>Vorschlag</dt><dd>' + esc(r.lat) + ', ' + esc(r.lon) + ' (± ' + fmt(r.uncertainty_m) + ' m) · Quelle ' + esc(r.source) + '</dd>' : '<dt>Vorschlag</dt><dd class="muted">keine Koordinate gefunden</dd>')
    + (r.geonames_id ? '<dt>GeoNames</dt><dd><a href="https://www.geonames.org/' + esc(r.geonames_id) + '" target="_blank" rel="noopener">' + esc(r.geonames_name) + '</a> · ' + esc(r.feature) + ' · ' + esc(r.country) + '</dd>' : '')
    + (r.osm ? '<dt>OpenStreetMap</dt><dd><a href="https://www.openstreetmap.org/' + esc(r.osm) + '" target="_blank" rel="noopener">' + esc(r.osm) + '</a></dd>' : '')
    + (r.qid ? '<dt>Wikidata</dt><dd><a href="https://www.wikidata.org/wiki/' + esc(r.qid) + '" target="_blank" rel="noopener">' + esc(r.qid) + '</a></dd>' : '')
    + (r.note ? '<dt>Hinweis</dt><dd>' + esc(r.note) + '</dd>' : '') + '</dl>'
    + '<div id="map"></div><div class="maplegend"><span><i style="background:#e0542e"></i>Vorschlag</span><span><i style="background:#1e7a4c"></i>Korrektur</span><span><i style="background:#3a6fb0;opacity:.6"></i>Orte aus denselben Einträgen</span><span>Klick in die Karte setzt einen Punkt</span></div>'
    + '</div><div class="cb" style="border-top:1px solid var(--line)">' + decisionBar(t, it, { y: fix ? 'Korrektur übernehmen' : 'Ort stimmt', n: 'Falsch / nicht bestimmbar', yDisabled: has ? '' : 'Erst eine Koordinate setzen (Karte anklicken oder suchen)' })
    + '<div class="fixbox"><h5>Suchen</h5><div class="row"><input type="text" class="grow" id="nq" value="' + esc(r.place_name) + '"><button class="lbtn" id="nbtn">OpenStreetMap</button><button class="lbtn" id="pwbtn">Wikidata</button>'
    + '<a class="lbtn" target="_blank" rel="noopener" href="https://www.geonames.org/search.html?q=' + encodeURIComponent(r.place_name) + '">GeoNames ↗</a></div>'
    + '<div class="row" style="margin-top:6px"><input type="text" id="ll" placeholder="Breite, Länge" style="width:150px"><select id="unc"><option value="100">± 100 m</option><option value="500">± 500 m</option><option value="1000" selected>± 1 km</option><option value="2000">± 2 km</option><option value="5000">± 5 km</option><option value="10000">± 10 km</option></select><button class="lbtn" id="llbtn">setzen</button>'
    + '<input type="text" id="gnid" placeholder="GeoNames-ID oder Link" style="width:170px" value="' + esc((fix && fix.geonames_id) || '') + '"><input type="text" id="pqid" placeholder="Wikidata-QID" style="width:120px" value="' + esc((fix && fix.qid) || '') + '"><button class="lbtn" id="idbtn">IDs übernehmen</button></div><div id="nres"></div>'
    + (fix ? '<div class="fixed">' + (fix.lat ? fix.lat + ', ' + fix.lon + ' (± ' + fmt(fix.uncertainty_m) + ' m)' : 'Koordinaten wie vorgeschlagen')
      + (fix.geonames_id ? ' · <a href="https://www.geonames.org/' + esc(fix.geonames_id) + '" target="_blank" rel="noopener">GeoNames ' + esc(fix.geonames_id) + '</a>' : '')
      + (fix.qid ? ' · <a href="https://www.wikidata.org/wiki/' + esc(fix.qid) + '" target="_blank" rel="noopener">' + esc(fix.qid) + '</a>' : '')
      + (fix.note ? ' · ' + esc(fix.note) : '') + ' <button class="lbtn" id="unfix">verwerfen</button></div>' : '')
    + '</div></div></div>';
  return card + '<div class="card"><div class="ch"><h3>Belegstellen im Tagebuch</h3></div><div class="cb">' + ctxBlock('place', r.place_name, [[r.place_name, '']]) + '</div></div>';
}
function habitatLinkDetail(t, it) {
  const r = it.r; const d = dget(t.id, it.key) || {}; const fix = d.fix;
  const code = fix ? fix.eunis_code : r.eunis_code;
  const e = EUNIS.get(r.eunis_code);
  const card = '<div class="card"><div class="cb"><div class="q">' + esc(r.habitat_label) + '<span class="arrow">→</span>' + (r.eunis_code ? esc(r.eunis_code) + ' ' + esc(r.eunis_label) : '<span class="muted">keine Klasse</span>') + '</div>'
    + '<div class="qsub">' + fmt(r.n_obs) + ' Beobachtungen · <span class="tag' + (r.status === 'linked' ? ' ok' : ' warn') + '">' + esc(STATUS_DE[r.status] || r.status) + '</span> Konfidenz ' + esc(r.confidence) + (r.match ? ' · Übereinstimmung ' + esc(r.match) : '') + '</div>'
    + '<dl class="facts">' + (r.note ? '<dt>Begründung Modell</dt><dd>' + esc(r.note) + '</dd>' : '')
    + (e ? '<dt>Ebene</dt><dd>' + e[2] + (e[3] ? ' (übergeordnet: ' + esc(e[3]) + ' ' + esc((EUNIS.get(e[3]) || [])[1] || '') + ')' : '') + '</dd>' : '') + '</dl>'
    + '</div><div class="cb" style="border-top:1px solid var(--line)">' + decisionBar(t, it, { y: fix ? 'Korrektur übernehmen' : 'Klasse passt', n: 'Falsch / nicht zuordenbar', yDisabled: code ? '' : 'Erst unten eine Klasse wählen' })
    + '<div class="fixbox"><h5>EUNIS-Suche</h5><div class="row"><input type="text" class="grow" id="eq" placeholder="z. B. Schilf, reed, C3.2, forest …"><select id="em" title="exact = gleiche Bedeutung, close = sehr ähnlich, broad = Klasse ist allgemeiner"><option value="exact">exact</option><option value="close" selected>close</option><option value="broad">broad</option></select></div><div id="eres" class="res" style="display:none"></div>'
    + (fix ? '<div class="fixed">Korrektur: ' + esc(fix.eunis_code) + ' ' + esc((EUNIS.get(fix.eunis_code) || [])[1] || '') + ' (' + esc(fix.match) + ') <button class="lbtn" id="unfix">verwerfen</button></div>' : '') + '</div></div></div>';
  return card + '<div class="card"><div class="ch"><h3>Belegstellen im Tagebuch</h3></div><div class="cb">' + ctxBlock('habitat', r.habitat_label, [[r.habitat_label, '']]) + '</div></div>';
}
function qaDetail(t, it) {
  const r = it.r; const d = dget(t.id, it.key) || {}; const q = QA_DE[r.reason] || [r.reason, ''];
  const card = '<div class="card"><div class="cb"><div class="q">' + esc(q[0]) + (r.value ? '<span class="arrow">·</span>' + esc(r.value) : '') + '</div>'
    + '<div class="qsub">' + esc(q[1]) + ' <span class="tag ' + (r.action === 'excluded' ? 'no' : 'warn') + '">' + (r.action === 'excluded' ? 'entfernt' : 'nur markiert') + '</span></div>'
    + '<dl class="facts"><dt>Eintrag</dt><dd>' + esc(r.entry_id) + '</dd><dt>Begründung</dt><dd>' + esc(r.detail) + '</dd></dl>'
    + (QA_KIND[r.reason] && r.value ? '<div class="corrslot qa">' + corrsFor(r.entry_uid, [r.value]).map(corrLine).join('')
      + (corrsFor(r.entry_uid, [r.value]).length ? '' : corrForm(QA_KIND[r.reason], [r.value], r.entry_uid, r.entry_id)) + '</div>' : '')
    + '</div><div class="cb" style="border-top:1px solid var(--line)">' + decisionBar(t, it, { y: 'Richtig erkannt', n: 'Falsch erkannt' })
    + '<div class="row" style="margin-top:8px"><input type="text" class="grow" id="qacorr" placeholder="Korrektur, falls bekannt (z. B. Datum 1922-07-15)" value="' + esc(d.corr || '') + '"></div></div></div>';
  let ev;
  if (it.ei >= 0) {
    const terms = r.value && !/^\d+$/.test(r.value) ? r.value.split(' -> ').map((v, k) => [v, k ? 'b' : '', 1]) : [];
    ev = '<div class="card"><div class="ch"><h3>Tagebucheintrag</h3></div><div class="cb"><div data-terms="' + esc(JSON.stringify(terms)) + '">' + psgHtml(it.ei, '', terms, true) + '</div></div></div>';
  } else ev = '<div class="card"><div class="cb muted">Eintrag nicht mehr im Graph, kein Text verfügbar.</div></div>';
  return card + ev;
}
function renderOverview() {
  if (map) { map.remove(); map = null; }
  let h = '<div class="dwrap"><div class="q" style="margin-top:6px">Validierung des Laubmann-Wissensgraphen</div><div class="qsub">Export ' + esc(P.export) + ' · ' + fmt(E.length) + ' Tagebucheinträge</div>'
    + '<div class="card"><div class="cb row" style="justify-content:space-between"><span>Aufgabe wählen, Belegstellen prüfen, mit <kbd>Y</kbd> <kbd>N</kbd> <kbd>U</kbd> entscheiden. Häufige Namen stehen oben.</span><button class="dbtn" id="ovHelpBtn">Anleitung</button></div></div><div class="stats">';
  for (const t of TASKS) { const p = progress(t); h += '<div class="stat" data-t="' + t.id + '"><div class="l">' + esc(t.group) + '</div><div class="n">' + fmt(p.done + p.u) + ' <span class="muted" style="font-size:14px;font-weight:400">/ ' + fmt(p.tot) + '</span></div><div class="l"><b>' + esc(t.title) + '</b></div></div>'; }
  h += '</div></div>';
  $('#detail').innerHTML = h;
}
$('#detail').addEventListener('click', e => {
  const st = e.target.closest('.stat'); if (st) return openTask(TBY[st.dataset.t]);
  if (e.target.id === 'ovHelpBtn') return showHelp();
});
function renderDetail(it) {
  const t = cur.task;
  if (map) { map.remove(); map = null; }
  const f = { merge: mergeDetail, taxonlink: taxonLinkDetail, personlink: personLinkDetail, placelink: placeLinkDetail, habitatlink: habitatLinkDetail, qa: qaDetail }[t.type];
  $('#detail').innerHTML = frame(t, it, f(t, it));
  wire(t, it); fillGbifDe();
}

// ---------- decisions ----------
function decide(dv) {
  const t = cur.task; if (!t || cur.i < 0) return; const it = t.items[cur.list[cur.i]];
  const btn = document.querySelector('.dbtn[data-d="' + dv + '"]'); if (btn && btn.disabled) { toast(btn.title); return; }
  const prev = dget(t.id, it.key) || {};
  const noteEl = $('#note'); const note = noteEl ? noteEl.value.trim() : prev.note || '';
  if (!dv) { const keep = {}; if (note) keep.note = note; if (prev.fix) keep.fix = prev.fix; dset(t.id, it.key, Object.keys(keep).length ? Object.assign({ d: '' }, keep) : null); }
  else {
    const o = Object.assign({}, prev, { d: dv, note });
    const qc = $('#qacorr'); if (qc) o.corr = qc.value.trim();
    if (t.type === 'personlink' && dv === 'n') { for (const k of ['qid', 'wd_label', 'wd_description', 'gnd', 'gnd_label', 'gnd_info']) delete o[k]; }
    delete o.by; delete o.t;
    dset(t.id, it.key, o);
  }
  refreshQi(cur.i); renderSide();
  if (dv && S.ui.adv) nextOpen(); else renderDetail(it);
}
function patch(fields) {
  const t = cur.task; const it = t.items[cur.list[cur.i]]; const prev = dget(t.id, it.key) || { d: '' };
  const o = Object.assign({}, prev, fields); delete o.by; delete o.t;
  for (const k in fields) if (fields[k] == null) delete o[k];
  dset(t.id, it.key, o); refreshQi(cur.i); renderSide(); renderDetail(it);
}
function wire(t, it) {
  const D = $('#detail');
  D.querySelectorAll('.dbtn[data-d]').forEach(b => b.onclick = () => decide(b.dataset.d));
  D.querySelectorAll('[data-nav]').forEach(b => b.onclick = () => step(+b.dataset.nav));
  const adv = $('#adv'); if (adv) adv.onchange = () => { S.ui.adv = adv.checked; save(); };
  const note = $('#note');
  if (note) note.oninput = () => { clearTimeout(note.t); note.t = setTimeout(() => { const prev = dget(t.id, it.key) || { d: '' }; const o = Object.assign({}, prev, { note: note.value.trim() }); delete o.by; delete o.t;
    if (!o.d && !o.note && !o.fix) dset(t.id, it.key, null); else dset(t.id, it.key, o); }, 400); };
  const qc = $('#qacorr');
  if (qc) qc.oninput = () => { clearTimeout(qc.t); qc.t = setTimeout(() => { const prev = dget(t.id, it.key) || { d: '' }; const o = Object.assign({}, prev, { corr: qc.value.trim() }); delete o.by; delete o.t; dset(t.id, it.key, o); }, 400); };
  const unfix = $('#unfix'); if (unfix) unfix.onclick = () => patch({ fix: null, d: '' });
  if (t.type === 'merge') {
    $('#manAdd').onclick = () => { const v = $('#manV').value.trim(), c = $('#manC').value.trim(); if (!v || !c || v === c) return toast('Bitte beide Namen eingeben');
      (S.manual[t.id] = S.manual[t.id] || []).push({ variant: v, canonical: c, by: S.who, t: new Date().toISOString() }); save(); toast('Zusammenführung vorgemerkt'); renderDetail(it); };
    D.querySelectorAll('[data-delman]').forEach(b => b.onclick = () => { S.manual[t.id].splice(+b.dataset.delman, 1); save(); renderDetail(it); });
  }
  if (t.type === 'personlink') {
    D.querySelectorAll('.cand[data-qid]').forEach(c => c.onclick = e => { if (e.target.closest('a')) return; pickPerson(it, c.dataset.qid); });
    $('#wbtn').onclick = () => wikidataSearch($('#wq').value, it);
    $('#wq').onkeydown = e => { if (e.key === 'Enter') wikidataSearch($('#wq').value, it); };
    $('#wqidbtn').onclick = () => { const q = ($('#wqid').value.match(/Q\d+/i) || [''])[0].toUpperCase(); if (!q) return toast('Ungültige QID'); pickPerson(it, q, { wd_label: q, wd_description: 'von Hand eingetragen' }); };
    $('#gndbtn').onclick = () => gndSearch($('#wq').value);
    $('#gndidbtn').onclick = () => { const g = gndId($('#gndid').value); if (!g) return toast('Ungültige GND-ID'); patch({ gnd: g, gnd_label: g, gnd_info: 'von Hand eingetragen', d: 'y' }); };
    const gc = $('#gndclear'); if (gc) gc.onclick = () => { const d = dget(t.id, it.key) || {}; patch({ gnd: null, gnd_label: null, gnd_info: null, d: d.qid ? d.d : '' }); };
  }
  if (t.type === 'taxonlink') { $('#gbtn').onclick = () => gbifSearch($('#gq').value); $('#gq').onkeydown = e => { if (e.key === 'Enter') gbifSearch($('#gq').value); }; }
  if (t.type === 'placelink') { initMap(it); $('#nbtn').onclick = () => osmSearch($('#nq').value); $('#nq').onkeydown = e => { if (e.key === 'Enter') osmSearch($('#nq').value); };
    $('#pwbtn').onclick = () => placeWikidataSearch($('#nq').value);
    $('#idbtn').onclick = () => { const g = ($('#gnid').value.match(/\d{3,}/) || [''])[0], q = ($('#pqid').value.match(/Q\d+/i) || [''])[0].toUpperCase();
      if (!g && !q) return toast('GeoNames-ID oder QID eintragen'); const f = (dget(t.id, it.key) || {}).fix || {};
      patch({ fix: Object.assign({}, f, { geonames_id: g, qid: q }), d: 'y' }); };
    $('#llbtn').onclick = () => { const m = $('#ll').value.replace(/,(\d)/g, '.$1').match(/(-?\d+(?:\.\d+)?)[\s;,]+(-?\d+(?:\.\d+)?)/); if (!m) return toast('Format: 48.137, 11.575');
      setPlaceFix(+m[1], +m[2], { note: 'von Hand eingetragen' }); }; }
  if (t.type === 'habitatlink') {
    const eq = $('#eq'); eq.oninput = () => eunisFilter(eq.value);
  }
}
function pickPerson(it, qid, extra) {
  const c = it.rows.find(x => x.qid === qid) || {};
  patch(Object.assign({ d: 'y', qid, wd_label: c.wd_label || '', wd_description: c.wd_description || '' }, extra || {}));
  // the Wikidata item often carries the GND number (P227)
  const t = cur.task, key = it.key;
  if (!(dget(t.id, key) || {}).gnd) wdClaims(qid).then(cl => { const g = claimValue(cl, 'P227');
    const d = dget(t.id, key) || {}; if (!g || d.gnd || d.qid !== qid) return;
    d.gnd = g; d.gnd_label = g; d.gnd_info = 'aus Wikidata übernommen'; dset(t.id, key, (({ by, t: _t, ...rest }) => rest)(d));
    if (cur.task === t && t.items[cur.list[cur.i]] === it) renderDetail(it); toast('GND aus Wikidata übernommen'); });
}
const gndId = v => { const m = String(v || '').match(/(?:d-nb\.info\/gnd\/)?([0-9]+-[0-9X]|[0-9]{1,10}[0-9X])\b/); return m ? m[1] : ''; };
async function wdClaims(qid) {
  try { const j = await getJSON('https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&origin=*&props=claims|labels|descriptions&languages=de|en&ids=' + qid); return (j.entities || {})[qid] || {}; }
  catch (e) { return {}; }
}
function claimValue(ent, p) { const c = ((ent.claims || {})[p] || [])[0]; return c && c.mainsnak && c.mainsnak.datavalue ? c.mainsnak.datavalue.value : null; }
async function gndSearch(q) {
  const box = $('#wres'); box.innerHTML = '<div class="small muted" style="margin-top:6px">suche …</div>';
  try {
    const j = await getJSON('https://lobid.org/gnd/search?format=json&size=12&filter=type:Person&q=' + encodeURIComponent(q));
    const res = (j.member || []).map(x => ({ id: x.gndIdentifier, name: x.preferredName,
      info: [[(x.dateOfBirth || [])[0], (x.dateOfDeath || [])[0]].filter(Boolean).join('–'), (x.professionOrOccupation || []).map(p => p.label).slice(0, 3).join(', '), (x.placeOfActivity || []).map(p => p.label).slice(0, 2).join(', ')].filter(Boolean).join(' · ') }));
    box.innerHTML = res.length ? '<div class="res">' + res.map((x, k) => '<div class="r" data-k="' + k + '"><b>' + esc(x.name) + '</b> <small>GND ' + esc(x.id) + '</small><br><small>' + esc(x.info) + '</small></div>').join('') + '</div>' : '<div class="small muted">Keine Treffer.</div>';
    box.querySelectorAll('.r[data-k]').forEach(el => el.onclick = () => { const x = res[+el.dataset.k]; patch({ gnd: x.id, gnd_label: x.name, gnd_info: x.info, d: 'y' }); });
  } catch (e) { box.innerHTML = '<div class="small muted">GND-Suche nicht erreichbar (' + esc(e.message) + ').</div>'; }
}
async function placeWikidataSearch(q) {
  const box = $('#nres'); box.innerHTML = '<div class="small muted" style="margin-top:6px">suche …</div>';
  try {
    const j = await getJSON('https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&origin=*&language=de&uselang=de&type=item&limit=12&search=' + encodeURIComponent(q));
    const res = j.search || [];
    box.innerHTML = res.length ? '<div class="res">' + res.map((x, k) => '<div class="r" data-k="' + k + '"><b>' + esc(x.label || x.id) + '</b> <small>' + esc(x.id) + '</small><br><small>' + esc(x.description || '') + '</small></div>').join('') + '</div>' : '<div class="small muted">Keine Treffer.</div>';
    box.querySelectorAll('.r[data-k]').forEach(el => el.onclick = async () => {
      const x = res[+el.dataset.k]; const ent = await wdClaims(x.id); const c = claimValue(ent, 'P625'); const g = claimValue(ent, 'P1566');
      const ids = { qid: x.id, geonames_id: g || '', note: (x.label || '') + (x.description ? ', ' + x.description : '') };
      if (c) setPlaceFix(c.latitude, c.longitude, ids);
      else { const f = (dget(cur.task.id, cur.task.items[cur.list[cur.i]].key) || {}).fix || {}; patch({ fix: Object.assign({}, f, ids), d: 'y' }); toast('Wikidata-Eintrag ohne Koordinaten'); }
    });
  } catch (e) { box.innerHTML = '<div class="small muted">Wikidata nicht erreichbar (' + esc(e.message) + ').</div>'; }
}
async function getJSON(url) { const r = await fetch(url); if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }
async function wikidataSearch(q, it) {
  const box = $('#wres'); box.innerHTML = '<div class="small muted" style="margin-top:6px">suche …</div>';
  try {
    const j = await getJSON('https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&origin=*&language=de&uselang=de&type=item&limit=12&search=' + encodeURIComponent(q));
    const res = j.search || [];
    box.innerHTML = res.length ? '<div class="res">' + res.map(x => '<div class="r" data-q="' + esc(x.id) + '" data-l="' + esc(x.label || '') + '" data-dd="' + esc(x.description || '') + '"><b>' + esc(x.label || x.id) + '</b> <small>' + esc(x.id) + '</small><br><small>' + esc(x.description || '') + '</small></div>').join('') + '</div>' : '<div class="small muted">Keine Treffer.</div>';
    box.querySelectorAll('.r').forEach(el => el.onclick = () => pickPerson(it, el.dataset.q, { wd_label: el.dataset.l, wd_description: el.dataset.dd }));
  } catch (e) { box.innerHTML = '<div class="small muted">Wikidata nicht erreichbar (' + esc(e.message) + ').</div>'; }
}
async function gbifSearch(q) {
  const box = $('#gres'); box.innerHTML = '<div class="small muted" style="margin-top:6px">suche …</div>';
  try {
    const [m, s] = await Promise.all([
      getJSON('https://api.gbif.org/v1/species/match?verbose=true&class=Aves&name=' + encodeURIComponent(q)).catch(() => ({})),
      getJSON('https://api.gbif.org/v1/species/search?datasetKey=d7dddbf4-2cf0-4f39-9b2a-bb099caae36c&limit=15&q=' + encodeURIComponent(q)).catch(() => ({ results: [] }))]);
    const seen = new Set(); const rows = [];
    const push = x => { const key = x.usageKey || x.key; if (!key || seen.has(key)) return; seen.add(key);
      rows.push({ key, name: x.canonicalName || x.scientificName, rank: x.rank, status: x.status || x.taxonomicStatus, acc: x.acceptedUsageKey || x.acceptedKey, cls: x.class, fam: x.family, vn: (x.vernacularNames || []).filter(v => v.language === 'deu').map(v => v.vernacularName).slice(0, 2).join(', ') }); };
    if (m.usageKey) push(m); (m.alternatives || []).forEach(push); (s.results || []).forEach(push);
    box.innerHTML = rows.length ? '<div class="res">' + rows.map((x, k) => '<div class="r" data-k="' + k + '"><b><i>' + esc(x.name) + '</i></b> <small>' + esc(x.rank || '') + ' · ' + esc(x.status || '') + ' · ' + esc(x.key) + (x.fam ? ' · ' + esc(x.fam) : '') + (x.cls ? ' · ' + esc(x.cls) : '') + '</small>' + (x.vn ? '<br><small>' + esc(x.vn) + '</small>' : '') + '</div>').join('') + '</div>' : '<div class="small muted">Keine Treffer.</div>';
    box.querySelectorAll('.r').forEach(el => el.onclick = async () => {
      const x = rows[+el.dataset.k]; let key = x.key, name = x.name, rank = x.rank;
      if (x.acc && x.acc !== x.key && x.status && x.status !== 'ACCEPTED') {
        try { const a = await getJSON('https://api.gbif.org/v1/species/' + x.acc); key = a.key; name = a.canonicalName || a.scientificName; rank = a.rank; toast('Synonym: auf akzeptierten Namen ' + name + ' umgestellt'); } catch (e) { }
      }
      const mt = ['SPECIES', 'SUBSPECIES'].includes(String(rank).toUpperCase()) ? 'EXACT' : 'HIGHERRANK';
      patch({ fix: { gbif_key: String(key), gbif_canonical_name: name, gbif_match_type: mt }, d: 'y' });
    });
  } catch (e) { box.innerHTML = '<div class="small muted">GBIF nicht erreichbar (' + esc(e.message) + ').</div>'; }
}
async function osmSearch(q) {
  const box = $('#nres'); box.innerHTML = '<div class="small muted" style="margin-top:6px">suche …</div>';
  try {
    const res = await getJSON('https://nominatim.openstreetmap.org/search?format=jsonv2&extratags=1&limit=10&accept-language=de&q=' + encodeURIComponent(q));
    box.innerHTML = res.length ? '<div class="res">' + res.map((x, k) => '<div class="r" data-k="' + k + '"><b>' + esc(x.name || x.display_name.split(',')[0]) + '</b> <small>' + esc(x.category + '/' + x.type) + '</small><br><small>' + esc(x.display_name) + '</small></div>').join('') + '</div>' : '<div class="small muted">Keine Treffer.</div>';
    box.querySelectorAll('.r').forEach(el => {
      const x = res[+el.dataset.k];
      el.onmouseenter = () => { if (map) { if (map._hover) map.removeLayer(map._hover); map._hover = L.circleMarker([+x.lat, +x.lon], { radius: 8, color: '#1e7a4c', dashArray: '3', fillOpacity: .2 }).addTo(map); } };
      el.onclick = async () => { const place = ['city', 'town', 'administrative'].includes(x.type) ? 5000 : ['village', 'suburb'].includes(x.type) ? 2000 : 1000;
        const qid = ((x.extratags || {}).wikidata || '').match(/^Q\d+$/) ? x.extratags.wikidata : '';
        const g = qid ? claimValue(await wdClaims(qid), 'P1566') || '' : '';
        setPlaceFix(+x.lat, +x.lon, { osm: x.osm_type + '/' + x.osm_id, note: x.display_name.slice(0, 160), uncertainty_m: place, qid, geonames_id: g }); };
    });
  } catch (e) { box.innerHTML = '<div class="small muted">OpenStreetMap-Suche nicht erreichbar (' + esc(e.message) + ').</div>'; }
}
function setPlaceFix(lat, lon, extra) {
  const unc = (extra && extra.uncertainty_m) || +($('#unc') ? $('#unc').value : 1000);
  patch({ fix: Object.assign({ lat: (+lat).toFixed(5), lon: (+lon).toFixed(5), uncertainty_m: unc, osm: '', note: '', qid: '', geonames_id: '' }, extra || {}, { uncertainty_m: unc }), d: 'y' });
}
function initMap(it) {
  if (typeof L === 'undefined') { $('#map').outerHTML = '<div class="muted small">Karte nicht verfügbar.</div>'; return; }
  const r = it.r; const d = dget(cur.task.id, it.key) || {}; const fix = d.fix;
  map = L.map('map', { zoomSnap: .5 });
  const esri = s => 'https://server.arcgisonline.com/ArcGIS/rest/services/' + s + '/MapServer/tile/{z}/{y}/{x}';
  const street = L.tileLayer(esri('World_Street_Map'), { maxZoom: 19, attribution: 'Tiles © Esri, HERE, Garmin, OpenStreetMap' });
  const topo = L.tileLayer(esri('World_Topo_Map'), { maxZoom: 19, attribution: 'Tiles © Esri' });
  const sat = L.tileLayer(esri('World_Imagery'), { maxZoom: 19, attribution: 'Tiles © Esri, Maxar, Earthstar' });
  const basemaps = { 'Straßenkarte': street, 'Topographie': topo, 'Luftbild': sat };
  (basemaps[S.ui.basemap] || street).addTo(map); L.control.layers(basemaps, null, { position: 'topright' }).addTo(map);
  map.on('baselayerchange', e => { S.ui.basemap = e.name; save(); });
  const pts = [];
  const c = P.C['place|' + r.place_name];
  if (c && c.m) { const mx = Math.max(1, ...c.m.map(x => x[3]));
    for (const [la, lo, lab, n] of c.m) { L.circleMarker([la, lo], { radius: 3 + 9 * Math.sqrt(n / mx), color: '#3a6fb0', weight: 1, fillOpacity: .35 }).bindTooltip(esc(lab) + ' (' + n + '× gemeinsam)').addTo(map); pts.push([la, lo]); } }
  if (r.lat !== '') { const ll = [+r.lat, +r.lon];
    if (+r.uncertainty_m) L.circle(ll, { radius: +r.uncertainty_m, color: '#e0542e', weight: 1, fillOpacity: .06 }).addTo(map);
    L.circleMarker(ll, { radius: 8, color: '#fff', weight: 2, fillColor: '#e0542e', fillOpacity: 1 }).bindTooltip('Vorschlag: ' + esc(r.geonames_name || r.place_name)).addTo(map); pts.push(ll); }
  if (fix && fix.lat) { const ll = [+fix.lat, +fix.lon];
    L.circle(ll, { radius: +fix.uncertainty_m || 1000, color: '#1e7a4c', weight: 1, fillOpacity: .08 }).addTo(map);
    L.circleMarker(ll, { radius: 8, color: '#fff', weight: 2, fillColor: '#1e7a4c', fillOpacity: 1 }).bindTooltip('Korrektur').addTo(map); pts.push(ll); }
  if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(.25), { maxZoom: 12 }); else map.setView([48.14, 11.58], 8);
  map.on('click', e => { const p = L.popup().setLatLng(e.latlng).setContent('<div style="font-size:13px">' + e.latlng.lat.toFixed(5) + ', ' + e.latlng.lng.toFixed(5) + '<br><button class="lbtn" id="popset">als Korrektur setzen</button></div>').openOn(map);
    setTimeout(() => { const b = document.getElementById('popset'); if (b) b.onclick = () => setPlaceFix(e.latlng.lat, e.latlng.lng, { note: 'auf der Karte gesetzt' }); }, 0); });
}
function eunisFilter(q) {
  const box = $('#eres'); q = q.trim().toLowerCase(); if (!q) { box.style.display = 'none'; return; }
  const res = P.eunis.filter(e => e[0].toLowerCase().startsWith(q) || e[1].toLowerCase().includes(q)).sort((a, b) => a[2] - b[2] || a[0].localeCompare(b[0])).slice(0, 80);
  box.style.display = 'block';
  box.innerHTML = res.length ? res.map(e => '<div class="r" data-c="' + esc(e[0]) + '" style="padding-left:' + (6 + 10 * (e[2] - 1)) + 'px"><b>' + esc(e[0]) + '</b> ' + esc(e[1]) + ' <small>Ebene ' + e[2] + '</small></div>').join('') : '<div class="r muted">Keine Klasse gefunden (Namen sind englisch).</div>';
  box.querySelectorAll('.r[data-c]').forEach(el => el.onclick = () => patch({ fix: { eunis_code: el.dataset.c, match: $('#em').value }, d: 'y' }));
}

// ---------- keyboard ----------
document.addEventListener('keydown', e => {
  const tag = (e.target.tagName || '').toLowerCase();
  if (e.key === 'Escape') { $('#scanpane').classList.remove('show'); document.querySelectorAll('.ov.show').forEach(o => o.classList.remove('show')); if (tag === 'input' || tag === 'textarea') e.target.blur(); return; }
  if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.ctrlKey || e.metaKey || e.altKey) return;
  if (!cur.task) return;
  const k = e.key.toLowerCase();
  if (k === 'j' || e.key === 'ArrowDown') { e.preventDefault(); step(1); }
  else if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); step(-1); }
  else if (k === 'y') decide('y');
  else if (k === 'n') decide('n');
  else if (k === 'u') decide('u');
  else if (k === 'x') decide('');
  else if (e.key === '/') { e.preventDefault(); $('#qsearch').focus(); }
  else if (/^[1-9]$/.test(e.key) && cur.task.type === 'personlink') { const it = cur.task.items[cur.list[cur.i]]; const c = it.rows.filter(x => x.qid)[+e.key - 1]; if (c) pickPerson(it, c.qid); }
});

// ---------- export ----------
const csvCell = v => { v = v == null ? '' : String(v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
const toCSV = (head, rows) => [head.map(csvCell).join(',')].concat(rows.map(r => head.map(h => csvCell(r[h])).join(','))).join('\n') + '\n';
function exportMerge(t) {
  const D = P.T[t.id];
  const head = D.head.slice(); for (const c of ['reason', 'reviewed_by', 'reviewed_at']) if (!head.includes(c)) head.push(c);
  const out = [];
  for (const it of t.items) {
    const o = Object.assign({}, it.r); const d = dget(t.id, it.key); const b = it.base;
    if (d && (d.d === 'y' || d.d === 'n')) { o.decision = d.d; o.reason = d.note || ''; o.reviewed_by = d.by || 'student'; o.reviewed_at = d.t; }
    else { o.decision = b ? b[0] : (o.decision || ''); o.reason = (d && d.d === 'u' ? 'UNSICHER' + (d.note ? ': ' + d.note : '') + (b && b[1] ? ' | ' : '') : (d && d.note ? d.note + (b && b[1] ? ' | ' : '') : '')) + (b ? b[1] || '' : '');
      o.reviewed_by = d && d.d === 'u' ? (d.by || 'student') + ' (unsicher)' : (b ? BASE_BY : ''); o.reviewed_at = d && d.d === 'u' ? d.t : ''; }
    out.push(o);
  }
  const section = (t.items[0] && t.items[0].r.section) || t.id.split('_')[0];
  for (const m of S.manual[t.id] || []) out.push({ merge_id: section + ': ' + m.variant + ' -> ' + m.canonical, section, variant: m.variant, canonical: m.canonical, rule: 'manual', status: 'manual', decision: 'y', reason: 'manuell ergänzt', reviewed_by: m.by || 'student', reviewed_at: m.t });
  return toCSV(head, out);
}
function exportLinks(t) {
  const D = P.T[t.id]; const head = D.head.slice(); for (const c of ['review_note', 'reviewed_by', 'reviewed_at']) if (!head.includes(c)) head.push(c);
  if (t.type === 'personlink' && !head.includes('gnd')) head.splice(head.indexOf('decision'), 0, 'gnd');
  const out = [];
  if (t.type === 'personlink') {
    for (const it of t.items) {
      const d = dget(t.id, it.key); const has = d && d.d;
      let matched = false;
      for (const r0 of it.rows) {
        const o = Object.assign({}, r0);
        if (has) { o.reviewed_by = d.by || 'student'; o.reviewed_at = d.t; o.review_note = (d.d === 'u' ? 'UNSICHER ' : '') + (d.note || ''); }
        if (d && d.d === 'y') {
          // the accepted row: the chosen Wikidata candidate, or (GND only) the row without a candidate
          if (!matched && ((d.qid && o.qid === d.qid) || (!d.qid && d.gnd && !o.qid))) { o.decision = 'y'; o.gnd = d.gnd || ''; matched = true; } else o.decision = '';
        }
        else if (d && d.d === 'n') o.decision = o.qid ? 'n' : '';
        out.push(o);
      }
      if (d && d.d === 'y' && !matched) out.push(Object.assign({}, it.rows[0], { qid: d.qid || '', wd_label: d.wd_label || '', wd_description: d.wd_description || '', gnd: d.gnd || '', rule: 'manual', decision: 'y', reviewed_by: d.by || 'student', reviewed_at: d.t, review_note: d.note || '' }));
    }
    return toCSV(head, out);
  }
  for (const it of t.items) {
    const o = Object.assign({}, it.r); const d = dget(t.id, it.key);
    if (d && d.d) { o.reviewed_by = d.by || 'student'; o.reviewed_at = d.t; o.review_note = (d.d === 'u' ? 'UNSICHER ' : '') + (d.note || ''); }
    if (d && (d.d === 'y' || d.d === 'n')) o.decision = d.d;
    if (d && d.d === 'y' && d.fix) {
      const f = d.fix;
      if (t.type === 'taxonlink') Object.assign(o, { gbif_key: f.gbif_key, gbif_canonical_name: f.gbif_canonical_name, gbif_match_type: f.gbif_match_type });
      if (t.type === 'placelink') {
        // new coordinates: the old gazetteer identities belonged to the rejected candidate
        if (f.lat) Object.assign(o, { lat: f.lat, lon: f.lon, uncertainty_m: f.uncertainty_m, source: 'reviewed', geonames_id: '', geonames_name: '', feature: '', country: '', admin1: '', qid: '', osm: f.osm || '', note: f.note || '' });
        if (f.geonames_id) Object.assign(o, { geonames_id: f.geonames_id, geonames_name: f.geonames_id === it.r.geonames_id ? it.r.geonames_name : '' });
        if (f.qid) o.qid = f.qid;
        o.confidence = '1.00';
      }
      if (t.type === 'habitatlink') { const e = EUNIS.get(f.eunis_code) || []; Object.assign(o, { eunis_code: f.eunis_code, eunis_label: e[1] || '', eunis_level: e[2] || '', eunis_uri: 'http://eunis.eea.europa.eu/eunishabitats/' + f.eunis_code, match: f.match, confidence: '1.00' }); }
    }
    out.push(o);
  }
  return toCSV(head, out);
}
function exportQA(t) {
  const D = P.T[t.id]; const head = D.head.concat(['decision', 'correction', 'review_note', 'reviewed_by', 'reviewed_at']);
  const lab = { y: 'confirmed', n: 'wrong', u: 'unsure' };
  return toCSV(head, t.items.map(it => { const d = dget(t.id, it.key) || {}; return Object.assign({}, it.r, { decision: lab[d.d] || '', correction: d.corr || '', review_note: d.note || '', reviewed_by: d.d ? d.by || 'student' : '', reviewed_at: d.d ? d.t : '' }); }));
}
function exportTask(t) { return t.type === 'merge' ? exportMerge(t) : t.type === 'qa' ? exportQA(t) : exportLinks(t); }
function exportCorrections() {
  const head = ['kind', 'entry_uid', 'entry_id', 'old_value', 'new_value', 'scientific_name', 'is_bird', 'note', 'reviewed_by', 'reviewed_at'];
  return toCSV(head, S.corr.map(c => ({ kind: c.kind, entry_uid: c.entry_uid, entry_id: c.entry_id, old_value: c.old, new_value: c.new,
    scientific_name: c.sci || '', is_bird: c.kind === 'taxon' ? (c.is_bird ? 'y' : 'n') : '', note: c.note || '', reviewed_by: c.by || 'student', reviewed_at: c.t })));
}
function exportLog() {
  const rows = [];
  for (const t of TASKS) { const d = S.dec[t.id] || {}; for (const k in d) { const x = d[k]; if (!x.d && !x.note) continue;
    rows.push({ task: t.id, key: k, decision: x.d, note: x.note || '', correction: x.corr || '', fix: x.fix ? JSON.stringify(x.fix) : (x.qid ? x.qid : ''), reviewed_by: x.by || '', reviewed_at: x.t || '' }); }
    for (const m of S.manual[t.id] || []) rows.push({ task: t.id, key: 'manual: ' + m.variant + ' -> ' + m.canonical, decision: 'y', note: '', correction: '', fix: '', reviewed_by: m.by || '', reviewed_at: m.t || '' }); }
  for (const c of S.corr) rows.push({ task: 'value_corrections', key: c.kind + ' ' + c.entry_id, decision: 'y', note: c.note || '', correction: c.old + ' -> ' + c.new, fix: c.sci || '', reviewed_by: c.by || '', reviewed_at: c.t || '' });
  return toCSV(['task', 'key', 'decision', 'note', 'correction', 'fix', 'reviewed_by', 'reviewed_at'], rows);
}
function progressJSON() { return JSON.stringify({ app: 'histornigraph-validation', version: 1, export: P.export, who: S.who, saved_at: new Date().toISOString(), dec: S.dec, manual: S.manual, corr: S.corr }, null, 1); }
// minimal ZIP (store)
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = b => { let c = 0xFFFFFFFF; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
function zip(files) {
  const enc = new TextEncoder(); const parts = [], central = []; let off = 0;
  const now = new Date(); const dt = ((now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1)) & 0xFFFF; const dd = (((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate()) & 0xFFFF;
  for (const [name, text] of files) {
    const nb = enc.encode(name), data = enc.encode(text), crc = crc32(data);
    const h = new DataView(new ArrayBuffer(30)); h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(6, 0x0800, true); h.setUint16(8, 0, true); h.setUint16(10, dt, true); h.setUint16(12, dd, true);
    h.setUint32(14, crc, true); h.setUint32(18, data.length, true); h.setUint32(22, data.length, true); h.setUint16(26, nb.length, true); h.setUint16(28, 0, true);
    parts.push(new Uint8Array(h.buffer), nb, data);
    const c = new DataView(new ArrayBuffer(46)); c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true); c.setUint16(8, 0x0800, true); c.setUint16(10, 0, true); c.setUint16(12, dt, true); c.setUint16(14, dd, true);
    c.setUint32(16, crc, true); c.setUint32(20, data.length, true); c.setUint32(24, data.length, true); c.setUint16(28, nb.length, true); c.setUint32(42, off, true);
    central.push(new Uint8Array(c.buffer), nb); off += 30 + nb.length + data.length;
  }
  const csize = central.reduce((a, b) => a + b.length, 0);
  const e = new DataView(new ArrayBuffer(22)); e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true); e.setUint32(12, csize, true); e.setUint32(16, off, true);
  return new Blob([...parts, ...central, new Uint8Array(e.buffer)], { type: 'application/zip' });
}
function download(name, blob) { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000); }
const stamp = () => new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '').replace(/^(\d{8})/, '$1-');
const whoSlug = () => (S.who || 'unbenannt').replace(/[^\p{L}\p{N}]+/gu, '_');
const README = () => 'HistOrniGraph Validierung, Export ' + new Date().toLocaleString('de-DE') + ' von ' + (S.who || '?') + '\nGrundlage: ' + P.export + '\n\n'
  + 'review/*.csv sind vollständige Review-Dateien im Format der Pipeline (Spalte decision).\n'
  + '- *_merges.csv: ersetzen data/review/*_merges.csv (resolution.*.reviewed_csv). Ohne eigene Entscheidung bleibt die automatische vom 19.08. stehen (reviewed_by = ' + BASE_BY + ').\n'
  + '- place/habitat_link_review.csv: y/n werden von linking.*.reviewed_csv gelesen; Korrekturen stehen in den Zeilen (source=reviewed).\n'
  + '- taxon/person_link_review.csv: y wird gelesen (reviewed_csv), bei Personen mit qid und/oder gnd; n wird derzeit nicht ausgewertet.\n'
  + '- qa_flags.csv: decision confirmed/wrong/unsure + correction; die Pipeline liest diese Datei noch nicht ein.\n'
  + '- value_corrections.csv: falsch gelesene Art-/Ortsnamen; nach data/review/value_corrections.csv legen (Config corrections.csv), wird vor der QA angewendet.\n'
  + 'validation_log.csv: alle Entscheidungen der Bearbeiterin/des Bearbeiters in einer Liste.\nvalidation_progress.json: Sicherung, lässt sich über „Fortschritt laden“ wieder einspielen.\n';
function showExport() {
  let h = '<button class="lbtn x" data-close>Schließen ✕</button><h2>Exportieren</h2><p>Die Entscheidungen sind nur in diesem Browser gespeichert. Bitte regelmäßig exportieren und die Datei an Tobias schicken (oder in den gemeinsamen Drive-Ordner legen).</p>'
    + '<p><button class="dbtn y" id="exZip">Alles als ZIP herunterladen</button> <button class="dbtn" id="exJson">Nur Sicherung (JSON)</button></p><h3>Einzelne Dateien</h3><table>';
  for (const t of TASKS) { const p = progress(t); h += '<tr><td><b>' + esc(t.group + ': ' + t.title) + '</b></td><td>' + fmt(p.y) + ' ja · ' + fmt(p.n) + ' nein · ' + fmt(p.u) + ' unsicher</td><td><button class="lbtn" data-ex="' + t.id + '">' + esc(t.file) + '</button></td></tr>'; }
  h += '<tr><td><b>Wertkorrekturen</b></td><td>' + fmt(S.corr.length) + ' Korrekturen</td><td><button class="lbtn" id="exCorr">value_corrections.csv</button></td></tr>';
  h += '</table><h3>Fortschritt übertragen</h3><p>„Fortschritt laden“ (oben) spielt eine JSON-Sicherung oder ein ZIP wieder ein, z. B. auf einem anderen Rechner. Vorhandene Entscheidungen werden zusammengeführt, bei Konflikten gilt die neuere.</p>';
  $('#exportBody').innerHTML = h; $('#ovExport').classList.add('show');
  $('#exZip').onclick = () => { const files = TASKS.map(t => ['review/' + t.file, exportTask(t)]); files.push(['review/value_corrections.csv', exportCorrections()], ['validation_log.csv', exportLog()], ['validation_progress.json', progressJSON()], ['LIESMICH.txt', README()]);
    download('histornigraph_validierung_' + whoSlug() + '_' + stamp() + '.zip', zip(files)); toast('ZIP heruntergeladen'); };
  $('#exJson').onclick = () => download('histornigraph_validierung_' + whoSlug() + '_' + stamp() + '.json', new Blob([progressJSON()], { type: 'application/json' }));
  $('#exCorr').onclick = () => download('value_corrections.csv', new Blob([exportCorrections()], { type: 'text/csv' }));
  document.querySelectorAll('[data-ex]').forEach(b => b.onclick = () => download(TBY[b.dataset.ex].file, new Blob([exportTask(TBY[b.dataset.ex])], { type: 'text/csv' })));
}
$('#btnExport').onclick = showExport;
document.querySelectorAll('.ov').forEach(o => o.addEventListener('click', e => { if (e.target === o || e.target.closest('[data-close]')) o.classList.remove('show'); }));
$('#btnImport').onclick = () => $('#fileImport').click();
async function readZipJSON(buf) {
  // find validation_progress.json in a stored (uncompressed) zip written by this page
  const u = new Uint8Array(buf); const dv = new DataView(buf); const dec = new TextDecoder();
  for (let i = 0; i + 30 < u.length;) { if (dv.getUint32(i, true) !== 0x04034b50) break; const size = dv.getUint32(i + 18, true), nl = dv.getUint16(i + 26, true), xl = dv.getUint16(i + 28, true);
    const name = dec.decode(u.subarray(i + 30, i + 30 + nl)); const start = i + 30 + nl + xl; if (name === 'validation_progress.json') return JSON.parse(dec.decode(u.subarray(start, start + size))); i = start + size; }
  throw new Error('keine validation_progress.json im ZIP');
}
$('#fileImport').addEventListener('change', async e => {
  const f = e.target.files[0]; e.target.value = ''; if (!f) return;
  try {
    const j = /\.zip$/i.test(f.name) ? await readZipJSON(await f.arrayBuffer()) : JSON.parse(await f.text());
    if (!j.dec) throw new Error('keine Entscheidungen gefunden');
    if (j.export && j.export !== P.export && !confirm('Die Sicherung stammt von ' + j.export + ', diese Oberfläche von ' + P.export + '. Trotzdem laden?')) return;
    let n = 0;
    for (const tid in j.dec) { S.dec[tid] = S.dec[tid] || {}; for (const k in j.dec[tid]) { const a = S.dec[tid][k], b = j.dec[tid][k]; if (!a || (b.t || '') > (a.t || '')) { S.dec[tid][k] = b; n++; } } }
    for (const c of j.corr || []) if (c.entry_uid && c.scope !== 'all' && !S.corr.some(x => x.id === c.id)) { S.corr.push(c); n++; }
    for (const tid in j.manual || {}) { S.manual[tid] = S.manual[tid] || []; for (const m of j.manual[tid]) if (!S.manual[tid].some(x => x.variant === m.variant && x.canonical === m.canonical)) S.manual[tid].push(m); }
    save(); toast(n + ' Entscheidungen übernommen'); openTask(cur.task);
  } catch (err) { alert('Import fehlgeschlagen: ' + err.message); }
});
fileImport.accept = '.json,.zip,application/json,application/zip';

// ---------- help ----------
function showHelp() {
  $('#helpBody').innerHTML = '<button class="lbtn x" data-close>Schließen ✕</button><h2>Anleitung</h2>'
    + '<p>Geprüft werden Entscheidungen, die die Pipeline automatisch getroffen hat. Im Zweifel <b>Unsicher</b> und eine kurze Anmerkung.</p>'
    + '<h3>Ablauf</h3><ol><li>Namen oben rechts eintragen.</li><li>Aufgabe links wählen, Belegstellen lesen, bei Bedarf den Scan öffnen.</li><li><kbd>Y</kbd> ja, <kbd>N</kbd> nein, <kbd>U</kbd> unsicher.</li><li>Am Ende: <b>Exportieren → Alles als ZIP</b>.</li></ol>'
    + '<h3>Zusammenführungen</h3><ul><li>Arten: alte Namen und OCR-Varianten ja, verschiedene Arten nein.</li><li>Personen: nur bei eindeutigem Kontext. „Frau X“ ist nicht „Herr X“.</li><li>Orte: nein bei verschiedenen Orten mit ähnlichem Namen (Nord/Süd, Teich 1/2).</li><li>Habitate: Singular/Plural ja.</li></ul>'
    + '<h3>Normdaten</h3><ul><li>Arten: GBIF-Link prüfen, sonst über die Suche die richtige Art wählen.</li><li>Personen: Wikidata-Kandidat und/oder GND wählen. GND steht oft schon im Wikidata-Eintrag und wird dann übernommen.</li><li>Orte: Koordinate prüfen (blau = Orte aus denselben Einträgen). Über OpenStreetMap oder Wikidata suchen; GeoNames und Wikidata werden mit übernommen, wenn vorhanden. Die GeoNames-ID lässt sich auch von geonames.org einfügen.</li><li>Habitate: EUNIS-Klasse wählen (englische Namen).</li></ul>'
    + '<p>Die Auswahl „fehlt noch“ bzw. „ohne GeoNames“ zeigt, wo Normdaten noch recherchiert werden müssen.</p>'
    + '<h3>Falsch gelesene Werte</h3><p>„✎ korrigieren“ an der Belegstelle: z. B. „Reh“ → Birkhenne oder „Rauchschwalben“ → Kaufbeuren. Gilt nur für diesen einen Eintrag. Alle Korrekturen: links „Wertkorrekturen“.</p>'
    + '<h3>Tastatur</h3><table><tr><td><kbd>Y</kbd> <kbd>N</kbd> <kbd>U</kbd></td><td>entscheiden</td></tr><tr><td><kbd>X</kbd></td><td>zurücksetzen</td></tr><tr><td><kbd>J</kbd> <kbd>K</kbd></td><td>weiter / zurück</td></tr><tr><td><kbd>1</kbd>–<kbd>9</kbd></td><td>Wikidata-Kandidat</td></tr><tr><td><kbd>/</kbd></td><td>Suche</td></tr></table>'
    + '<h3>Speichern</h3><p>Automatisch im Browser, nur auf diesem Rechner. Regelmäßig exportieren; „Fortschritt laden“ spielt eine Sicherung wieder ein.</p>';
  $('#ovHelp').classList.add('show');
}
$('#btnHelp').onclick = showHelp;
$('#btnTheme').onclick = () => { const r = document.documentElement; const dark = r.dataset.theme ? r.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; r.dataset.theme = dark ? 'light' : 'dark'; S.ui.theme = r.dataset.theme; save(); };
if (S.ui.theme) document.documentElement.dataset.theme = S.ui.theme;

// ---------- start ----------
$('#loading').remove();
openTask(S.ui.task ? TBY[S.ui.task] : null);
if (!S.who) setTimeout(showHelp, 300);
})();
