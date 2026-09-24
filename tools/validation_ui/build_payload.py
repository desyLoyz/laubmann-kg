"""Payload for the HistOrniGraph validation UI: review CSVs of the 08-19 export,
the machine baseline (review/reviewed/), entries (full text) and, per name the
review rows refer to, the diary entries where it occurs."""
import argparse, csv, json, pickle, re, collections, gzip, base64
from pathlib import Path
import rdflib

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("review_dir", help="the export's review/ folder (with reviewed/ baseline)")
ap.add_argument("--triples", default="triples.pkl", help="output of load.py")
ap.add_argument("--eunis", default=str(Path(__file__).resolve().parents[2] / "data" / "eunis_habitats.csv"))
ap.add_argument("--export-name", default=None, help="label shown in the UI (default: name of the export folder)")
ap.add_argument("--built", default="", help="build date shown in the UI")
ap.add_argument("--out", default="payload.b64")
args = ap.parse_args()
R = str(Path(args.review_dir)) + "/"
EUNIS = args.eunis
T = pickle.load(open(args.triples, 'rb'))
D = 'https://w3id.org/laubmann-kg/data/'
def loc(u): u = str(u); return u.rsplit('#', 1)[-1].rsplit('/', 1)[-1]
out = collections.defaultdict(lambda: collections.defaultdict(list))
typ = {}
for s, p, o in T:
    pn = loc(p)
    if pn == 'type': typ[s] = loc(o)
    else: out[s][pn].append(o)
def one(s, p, d=''):
    v = out[s].get(p); return str(v[0]) if v else d
def labels(s):
    return [str(x) for x in out[s].get('label', []) + out[s].get('altLabel', [])]

# entries
ents = sorted([s for s, t in typ.items() if t == 'DiaryEntry'], key=lambda s: (one(s, 'identifier')))
eidx = {s: i for i, s in enumerate(ents)}
coords = {}
for s, t in typ.items():
    if t == 'Place' and out[s].get('lat'):
        coords[s] = (round(float(one(s, 'lat')), 5), round(float(one(s, 'long')), 5))
E = []
for s in ents:
    page = out[s].get('isPartOf', [None])[0]
    pid = one(page, 'identifier') if page else ''
    vol = one(page, 'isPartOf')[-2:] if page else ''
    m = re.search(r'_(\d{4})(?:_([LR]|full))?$', pid)
    pl = out[s].get('entryPlace', [None])[0]
    E.append({'id': one(s, 'identifier'), 'uid': loc(s).replace('entry_', ''), 'd': one(s, 'eventDate'),
              'vd': one(s, 'verbatimEventDate'), 'k': one(s, 'entryKind'), 't': one(s, 'fieldNotes'),
              'v': vol, 'sc': int(m.group(1)) if m else None, 'sd': (m.group(2) or '') if m else '', 'pg': pid,
              'pl': one(pl, 'label') if pl else ''})
print('entries', len(E))
uid2e = {e['uid']: i for i, e in enumerate(E)}

# structured occurrences: kind|name -> {entry: note}
struct = collections.defaultdict(dict)
onotes = collections.defaultdict(list)
place_entries = collections.defaultdict(set)   # entry -> place nodes (for map context)
def add(kind, name, ei, note=''):
    if not name: return
    d = struct[(kind, name)]
    if ei not in d or (note and not d[ei]): d[ei] = note
for s, t in typ.items():
    if t == 'Observation':
        e = out[s].get('isPartOf', [None])[0]
        if e not in eidx: continue
        ei = eidx[e]; note = one(s, 'verbatimNotes')
        onotes[ei].append(note + ' [' + one(s, 'verbatimLocality') + ']' if one(s, 'verbatimLocality') else note)
        tx = out[s].get('observedTaxon', [None])[0]
        # only verbatim evidence: node labels are post-merge canonicals
        vi = one(s, 'verbatimIdentification')
        add('taxon', vi or (one(tx, 'label') if tx is not None else ''), ei, note)
        add('place', one(s, 'verbatimLocality'), ei, note)
        for pl in out[s].get('observedAt', []) + out[s].get('hasLocality', []):
            place_entries[ei].add(pl)
        for h in out[s].get('habitat', []):
            if isinstance(h, rdflib.Literal): add('habitat', str(h), ei, note)
    elif t == 'DiaryEntry':
        for pl in out[s].get('entryPlace', []):
            place_entries[eidx[s]].add(pl)
for s, t in typ.items():   # travel legs -> entry
    if t == 'TravelEvent':
        e = out[s].get('isPartOf', [None])[0] or out[s].get('wasDerivedFrom', [None])[0]
        if e in eidx:
            for leg in out[s].get('hasLeg', []):
                for pl in out[leg].get('departurePlace', []) + out[leg].get('arrivalPlace', []):
                    place_entries[eidx[e]].add(pl)

# token index over entry texts
TOK = re.compile(r'\w+', re.U)
post = collections.defaultdict(set)
low = [(e['t'] + '\n' + '\n'.join(onotes.get(i, []))).lower() for i, e in enumerate(E)]
for i, t in enumerate(low):
    for w in set(TOK.findall(t)): post[w].add(i)
def pattern(name):
    toks = TOK.findall(name.lower())
    return re.compile(r'(?<!\w)' + r'\W*'.join(re.escape(w) for w in toks) + r'(?!\w)', re.I) if toks else None
def note_for(i, name):
    pat = pattern(name)
    if pat is None or pat.search(E[i]['t']): return ''
    for n in onotes.get(i, []):
        if pat.search(n): return n
    return ''
def text_hits(name):
    toks = [w for w in TOK.findall(name.lower())]
    if not toks or sum(len(w) for w in toks) < 3: return set()
    cand = min((post.get(w, set()) for w in toks), key=len)
    if not cand: return set()
    pat = re.compile(r'(?<!\w)' + r'\W*'.join(re.escape(w) for w in toks) + r'(?!\w)')
    return {i for i in cand if pat.search(low[i])}

def pick(ids, k):
    ids = sorted(ids, key=lambda i: (E[i]['d'] or '9999', E[i]['id']))
    if len(ids) <= k: return ids
    return [ids[round(j * (len(ids) - 1) / (k - 1))] for j in range(k)]

CTX = {}
def ctx(kind, name, k=8):
    key = kind + '|' + name
    if key in CTX or not name: return
    st = struct.get((kind, name), {})
    th = text_hits(name)
    allids = set(st) | th
    chosen = pick(st.keys(), k) if st else []
    rest = [i for i in pick(th - set(chosen), k) if i not in chosen]
    chosen = (chosen + rest)[:k]
    item = {'n': len(allids), 's': len(st), 'e': [[i, note_for(i, name) or (st.get(i, '') if i not in th else '')] for i in chosen]}
    if kind == 'place':
        pts = collections.Counter()
        for i in allids:
            for pl in place_entries.get(i, ()):
                if pl in coords and name not in labels(pl): pts[coords[pl] + (one(pl, 'label'),)] += 1
        top = sorted(pts.items(), key=lambda kv: (-kv[1], kv[0][2], kv[0][0], kv[0][1]))[:40]   # stable across hash seeds
        item['m'] = [[a, b, l, c] for (a, b, l), c in top]
    CTX[key] = item

def read(fn):
    with open(fn, newline='', encoding='utf-8') as h:
        r = csv.reader(h); head = next(r); return head, [row for row in r]

TASKS = {}
KIND = {'taxon': 'taxon', 'person': 'person', 'place': 'place', 'habitat': 'habitat'}
for sec, kind in (('taxon', 'taxon'), ('person', 'person'), ('place', 'place'), ('habitat', 'habitat')):
    head, rows = read(R + f'{sec}_merges.csv')
    bh, brows = read(R + f'reviewed/{sec}_merges.csv')
    bd = {}
    for b in brows:
        d = dict(zip(bh, b))
        if d.get('decision'): bd[d['merge_id']] = [d['decision'], d.get('reason', '')]
    cur = {r[0] for r in rows}
    bonly = [b for b in brows if b[0] not in cur and dict(zip(bh, b)).get('decision')]
    for r in rows:
        d = dict(zip(head, r)); ctx(kind, d['variant']); ctx(kind, d['canonical'])
    for b in bonly:
        d = dict(zip(bh, b)); ctx(kind, d['variant']); ctx(kind, d['canonical'])
    TASKS[f'{sec}_merges'] = {'head': head, 'rows': rows, 'base': bd, 'bhead': bh, 'bonly': bonly}
    print(sec, 'merges', len(rows), 'baseline decisions', len(bd), 'baseline-only', len(bonly))

for sec, kind, col in (('taxon', 'taxon', 'vernacular_de'), ('person', 'person', 'person_name'),
                       ('place', 'place', 'place_name'), ('habitat', 'habitat', 'habitat_label')):
    head, rows = read(R + f'{sec}_link_review.csv')
    ci = head.index(col)
    for r in rows: ctx(kind, r[ci])
    TASKS[f'{sec}_links'] = {'head': head, 'rows': rows}
    print(sec, 'links', len(rows))

head, rows = read(R + 'qa_flags.csv')
TASKS['qa_flags'] = {'head': head, 'rows': rows, 'ei': [uid2e.get(r[1], -1) for r in rows]}
print('qa', len(rows), 'unmapped', sum(1 for r in rows if r[1] not in uid2e))

eh, er = read(EUNIS)
eunis = [[r[0], r[1], int(r[2]), r[3]] for r in er]
payload = {'built': args.built, 'export': args.export_name or Path(args.review_dir).resolve().parent.name,
           'E': [[e['id'], e['uid'], e['d'], e['vd'], e['k'], e['v'], e['sc'], e['sd'], e['pl'], e['t'], e['pg']] for e in E],
           'C': CTX, 'T': TASKS, 'eunis': eunis}
raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
gz = gzip.compress(raw, 9, mtime=0)
open(args.out, 'w').write(base64.b64encode(gz).decode())
print('ctx', len(CTX), 'raw MB', len(raw) / 1e6, 'gz MB', len(gz) / 1e6)
