"""Georeference check: places whose coordinates lie far from the rest of their entries.

The place linking matches a diary's place name against GeoNames and
OpenStreetMap/Nominatim. A local name the gazetteers do not know is then often
matched to a namesake elsewhere: the "Tafelberg" at the Ismaning reservoir went
to a Tafelberg near Mühldorf, "Oberbecken" and "Keilberg" to the Spessart,
"Verbindungskanal" to Mannheim, the Ionian island Kalamos to Attica (GBIF
export review of 2026-10-26, docs/gbif_export.md).

``dossiers`` selects every (place label, coordinates) whose median distance to
the other georeferenced places of the same entries (and to the entry's own
place) exceeds ``--min-km``, and writes one dossier per place: the current
georeference, the entries with a passage of their text around the name, the
other places of those entries, and the GeoNames features of the same name
within 250 km of the entries (the candidates for the right namesake).

Two judges answer independently (Claude subagents, the same instructions, the
second without the first's verdicts), each writing a list of
{"id", "verdict", "gn", "parent", "uncertainty_km", "confidence", "reason"}
with verdict correct | relocate_gn | relocate_parent | drop | unsure. The second
judge sees only the dossiers the first did not find correct, plus a random
control sample of those it did.

``merge`` keeps what both agree on and writes ``georef_machine.csv`` in the
contract of ``review/identities.csv`` (section places): both relocate to the
same point (same GeoNames id, same parent place or points within 5 km) -> link
row with those coordinates; both find the coordinates wrong but disagree on the
replacement, or both drop -> nolink row (coordinates removed). Confidence
1 - (1 - c1)(1 - c2) as in record_check_combine.py, agreement = 2. Everything
else (one judge finds the coordinates right, unsure, mixed labels) is listed in
``georef_open.csv`` for a person. The pipeline reads the CSV through
``review.machine.georef`` (before identities_machine.csv), the GBIF export
through ``place_corrections``.

    python tools/validation_ui/machine_review/georef_check.py dossiers --export <export> --out <work> [--gbif output/gbif/observations]
    python tools/validation_ui/machine_review/georef_check.py batches --out <work> --pass 1 --n 8
    python tools/validation_ui/machine_review/georef_check.py batches --out <work> --pass 2 --n 4 [--control 60]
    python tools/validation_ui/machine_review/georef_check.py merge --out <work> [--csv data/review/machine/georef_machine.csv]

A second selection (``dossiers --mode week``) compares each place with the records of
the surrounding days instead of its own entries; it finds entries with a single place or
with only wrong places (Tietzing in Hungary, Kalamos in Attica). Both judges see every one
of those dossiers.

Work folder: dossiers.json (dossiers_week.json), batch_<i>.json / verdicts1_<i>.json, p2batch_<i>.json / verdicts2_<i>.json,
p2_ids.json, georef_judgements.csv (every dossier with both verdicts), georef_open.csv, summary.json.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import glob
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from laubmann_kg.review.identities import IDENTITY_FIELDS  # noqa: E402

FIELDS = IDENTITY_FIELDS + ["confidence", "agreement", "sources", "round"]
ROUND = "georef-2026-10-26"
SAME_POINT_KM = 5.0
WRONG = ("drop", "relocate_gn", "relocate_parent")
# a river's GeoNames point (often its mouth) can lie far from the stretch the diary means:
# a relocation onto one is not taken (the coordinates are removed instead)
LINEAR_FEATURES = {"H.STM", "H.STMI", "H.CNL", "H.STMS"}


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def read_tsv(path: Path) -> list[dict]:
    csv.field_size_limit(10 * 1024 * 1024)
    with path.open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h, delimiter="\t", quoting=csv.QUOTE_NONE))


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


# ------------------------------------------------------------------ dossiers


def candidates(occ: list[dict], events: dict[str, dict], min_km: float) -> list[dict]:
    """(locality, lat, lon) whose median distance to the rest of its entries exceeds ``min_km``."""
    by_event: dict[str, list[dict]] = collections.defaultdict(list)
    for o in occ:
        if o.get("decimalLatitude"):
            by_event[o["eventID"]].append(o)
    seen: dict[tuple, dict] = {}
    for eid, rows in by_event.items():
        e = events[eid]
        for o in rows:
            refs = [(float(x["decimalLatitude"]), float(x["decimalLongitude"])) for x in rows if x["locality"] != o["locality"]]
            if e.get("decimalLatitude") and e.get("locality") != o["locality"]:
                refs.append((float(e["decimalLatitude"]), float(e["decimalLongitude"])))
            if not refs:
                continue
            centre = (statistics.median(p[0] for p in refs), statistics.median(p[1] for p in refs))
            key = (o["locality"], o["decimalLatitude"], o["decimalLongitude"])
            c = seen.setdefault(key, {"records": [], "dists": [], "entries": set(),
                                      "locationID": o.get("locationID", ""), "source": o.get("georeferenceSources", "")})
            c["records"].append(o["occurrenceID"])
            c["dists"].append(km((float(o["decimalLatitude"]), float(o["decimalLongitude"])), centre))
            c["entries"].add(e.get("fieldNumber") or eid)
    out = []
    for (place, lat, lon), c in seen.items():
        if statistics.median(c["dists"]) > min_km:
            out.append({"place": place, "lat": lat, "lon": lon, **c,
                        "median_km": round(statistics.median(c["dists"]))})
    return sorted(out, key=lambda c: -len(c["records"]))


def week_candidates(occ: list[dict], events: dict[str, dict], min_km: float, days: int = 3) -> list[dict]:
    """(locality, lat, lon) whose median distance to every other georeferenced record
    of the surrounding days (+-``days``) exceeds ``min_km``. Catches what ``candidates``
    cannot: entries with a single place, or whose places are all wrong (Kalamos, Tietzing)."""
    by_date: dict[str, list[tuple]] = collections.defaultdict(list)
    for o in occ:
        if o.get("decimalLatitude") and len(o.get("eventDate", "")) >= 10 and "/" not in o["eventDate"]:
            by_date[o["eventDate"][:10]].append((float(o["decimalLatitude"]), float(o["decimalLongitude"]), o["locality"]))
    seen: dict[tuple, dict] = {}
    for o in occ:
        if not o.get("decimalLatitude") or len(o.get("eventDate", "")) < 10 or "/" in o["eventDate"]:
            continue
        day = dt.date.fromisoformat(o["eventDate"][:10])
        ctx = [p for k in range(-days, days + 1)
               for p in by_date.get((day + dt.timedelta(k)).isoformat(), []) if p[2] != o["locality"]]
        if len(ctx) < 3:
            continue
        centre = (statistics.median(p[0] for p in ctx), statistics.median(p[1] for p in ctx))
        key = (o["locality"], o["decimalLatitude"], o["decimalLongitude"])
        c = seen.setdefault(key, {"records": [], "dists": [], "entries": set(), "context": [],
                                  "locationID": o.get("locationID", ""), "source": o.get("georeferenceSources", "")})
        c["records"].append(o["occurrenceID"])
        c["dists"].append(km((float(o["decimalLatitude"]), float(o["decimalLongitude"])), centre))
        c["entries"].add(events[o["eventID"]].get("fieldNumber") or o["eventID"])
        c["context"] += ctx
    out = []
    for (place, lat, lon), c in seen.items():
        if statistics.median(c["dists"]) > min_km:
            out.append({"place": place, "lat": lat, "lon": lon, **c, "median_km": round(statistics.median(c["dists"]))})
    return sorted(out, key=lambda c: -len(c["records"]))


def build_dossiers(export: Path, geonames_dir: Path, gbif_dir: Path | None, min_km: float,
                   mode: str = "entry", exclude: set | None = None, id_start: int = 0) -> list[dict]:
    from laubmann_kg.linking.places import GeoNamesIndex

    occ = read_tsv(export / "dwca" / "occurrence.txt")
    events = {e["eventID"]: e for e in read_tsv(export / "dwca" / "event.txt")}
    by_number = {e["fieldNumber"]: e for e in events.values()}
    by_event: dict[str, list[dict]] = collections.defaultdict(list)
    for o in occ:
        by_event[o["eventID"]].append(o)
    in_gbif = {o["occurrenceID"] for o in read_tsv(gbif_dir / "occurrence.txt")} if gbif_dir else set()
    review = read_csv(export / "review" / "place_link_review.csv")
    by_point: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in review:
        if r.get("lat"):
            by_point[(round(float(r["lat"]), 3), round(float(r["lon"]), 3))].append(r)
    gn = GeoNamesIndex(geonames_dir, download=False)
    dossiers = []
    found = candidates(occ, events, min_km) if mode == "entry" else week_candidates(occ, events, min_km)
    found = [c for c in found if (c["place"], c["lat"], c["lon"]) not in (exclude or set())]
    for i, c in enumerate(found, id_start):
        forms = [{"label": r["place_name"], "uses": r["n_uses"], "status": r["status"], "source": r["source"],
                  "gn": r["geonames_name"], "feature": r["feature"], "country": r["country"],
                  "conf": r["confidence"], "note": r["note"]}
                 for r in by_point.get((round(float(c["lat"]), 3), round(float(c["lon"]), 3)), [])][:6]
        entries = []
        for number in sorted(c["entries"])[:3]:
            e = by_number.get(number)
            if not e:
                continue
            text, pos = e.get("fieldNotes", ""), -1
            for label in [c["place"]] + [f["label"] for f in forms]:
                pos = text.lower().find(label.lower()[:max(4, len(label) - 2)])
                if pos >= 0:
                    break
            snippet = text[max(0, pos - 350):pos + 250] if pos >= 0 else text[:500]
            others = sorted({o["locality"] for o in by_event[e["eventID"]] if o["locality"] and o["locality"] != c["place"]})[:12]
            entries.append({"fieldNumber": number, "date": e["eventDate"], "entry_locality": e["locality"],
                            "other_places_in_entry": others, "text_snippet": " ".join(snippet.split())})
        # context: every other georeferenced place of the entries using the label, and their own places
        # (week mode: every georeferenced record of the surrounding days)
        context = [p[:2] for p in c.get("context", [])]
        for number in (c["entries"] if mode == "entry" else []):
            e = by_number.get(number)
            if not e:
                continue
            context += [(float(o["decimalLatitude"]), float(o["decimalLongitude"])) for o in by_event[e["eventID"]]
                        if o.get("decimalLatitude") and o["locality"] != c["place"]]
            if e.get("decimalLatitude") and e.get("locality") != c["place"]:
                context.append((float(e["decimalLatitude"]), float(e["decimalLongitude"])))
        centre = (statistics.median(p[0] for p in context), statistics.median(p[1] for p in context))
        namesakes, ids = [], set()
        for label in [c["place"]] + [f["label"] for f in forms]:
            for g in gn.lookup(label):
                if g.id not in ids and km((g.lat, g.lon), centre) < 250:
                    ids.add(g.id)
                    namesakes.append({"gn": g.id, "name": g.name, "feature": f"{g.fclass}.{g.fcode}", "cc": g.cc,
                                      "lat": g.lat, "lon": g.lon, "km_from_entry_context": round(km((g.lat, g.lon), centre))})
        dossiers.append({
            "id": i, "place": c["place"],
            "current": {"lat": c["lat"], "lon": c["lon"], "locationID": c["locationID"], "source": c["source"]},
            "n_records": len(c["records"]), "n_in_gbif_subset": sum(r in in_gbif for r in c["records"]),
            "median_km_from_rest_of_entry": c["median_km"],
            "entry_context_center": [round(centre[0], 3), round(centre[1], 3)],
            "all_entries": sorted(c["entries"])[:15], "name_forms_with_these_coords": forms, "entries": entries,
            "geonames_namesakes_near_context": sorted(namesakes, key=lambda a: a["km_from_entry_context"])[:6]}
            | ({"places_of_surrounding_days": [n for n, _ in collections.Counter(p[2] for p in c["context"]).most_common(12)]}
               if mode == "week" else {}))
    return dossiers


# ------------------------------------------------------------------ batches


def write_batches(work: Path, pass_no: int, n: int, control: int, seed: int = 26) -> None:
    dossiers = json.loads((work / "dossiers.json").read_text(encoding="utf-8"))
    if pass_no == 1:
        chosen = [d["id"] for d in dossiers]
        prefix = "batch"
    else:
        first = verdicts(work, 1)
        flagged = [i for i, v in first.items() if v["verdict"] != "correct"]
        rng = random.Random(seed)
        ctrl = rng.sample(sorted(i for i, v in first.items() if v["verdict"] == "correct"), control)
        chosen = flagged + ctrl
        rng.shuffle(chosen)
        (work / "p2_ids.json").write_text(json.dumps({"changed": flagged, "control": ctrl}), encoding="utf-8")
        prefix = "p2batch"
    by_id = {d["id"]: d for d in dossiers}
    size = -(-len(chosen) // n)
    for b in range(n):
        part = [by_id[i] for i in chosen[b * size:(b + 1) * size]]
        (work / f"{prefix}_{b}.json").write_text(json.dumps(part, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pass {pass_no}: {len(chosen)} dossiers in {n} batches")


# ------------------------------------------------------------------ merge


def verdicts(work: Path, pass_no: int) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for path in sorted(glob.glob(str(work / f"verdicts{pass_no}_*.json"))):
        for v in json.loads(Path(path).read_text(encoding="utf-8")):
            out[int(v["id"])] = v
    return out


def target(v: dict, dossier: dict, places: dict[str, dict], gn_points: dict[int, tuple]) -> tuple | None:
    """(lat, lon, uncertainty_m, gn id or None, basis) a relocation verdict points to, None if it cannot be resolved."""
    if v["verdict"] == "relocate_gn" and v.get("gn"):
        p = gn_points.get(int(v["gn"]))
        if p:
            unc = int(1000 * (v.get("uncertainty_km") or 2))
            return p[0], p[1], unc, int(v["gn"]), f"GeoNames {v['gn']}"
    if v["verdict"] == "relocate_parent" and v.get("parent"):
        parent = places.get((v["parent"] or "").casefold())
        if parent and parent.get("lat"):
            unc = int(1000 * (v.get("uncertainty_km") or 3)) + int(float(parent.get("uncertainty_m") or 0))
            return float(parent["lat"]), float(parent["lon"]), unc, None, f"within {v['parent']}"
    return None


def combine(c1: float, c2: float) -> float:
    return round(1 - (1 - c1) * (1 - c2), 3)


def merge(work: Path, csv_path: Path, export: Path) -> dict:
    dossiers = {d["id"]: d for path in sorted(work.glob("dossiers*.json"))
                for d in json.loads(path.read_text(encoding="utf-8"))}
    first, second = verdicts(work, 1), verdicts(work, 2)
    review = read_csv(export / "review" / "place_link_review.csv")
    places = {r["place_name"].casefold(): r for r in review}
    gn_points = {d["gn"]: (d["lat"], d["lon"]) for dos in dossiers.values() for d in dos["geonames_namesakes_near_context"]
                 if d["feature"] not in LINEAR_FEATURES}
    flagged_ids = {i for i, v in first.items() if v["verdict"] != "correct"}
    rows, judgements, open_rows = [], [], []
    stamp = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")
    outcome = collections.Counter()
    for i, d in sorted(dossiers.items()):
        v1, v2 = first.get(i), second.get(i)
        result = "unchanged"
        if v1 and v2:
            a, b = v1["verdict"], v2["verdict"]
            c = combine(float(v1.get("confidence") or 0), float(v2.get("confidence") or 0))
            row = {"section": "places", "name_form": d["place"], "target": d["place"], "reviewed_by": "machine:claude-opus-5-5",
                   "reviewed_at": stamp, "confidence": c, "agreement": 2, "sources": "judge1+judge2", "round": ROUND}
            if a in WRONG and b in WRONG:
                t1, t2 = target(v1, d, places, gn_points), target(v2, d, places, gn_points)
                if a != "drop" and b != "drop" and t1 and t2 and km(t1[:2], t2[:2]) <= SAME_POINT_KM:
                    t = t1 if t1[3] else t2          # prefer the GeoNames point
                    rows.append(row | {"decision": "link", "authority": f"gn:{t[3]}" if t[3] else "",
                                       "lat": f"{t[0]:.5f}", "lon": f"{t[1]:.5f}", "uncertainty_m": max(t1[2], t2[2]),
                                       "reason": f"georeference check: was {d['current']['lat']}/{d['current']['lon']} ({d['current']['source'][:60]}); {t[4]}",
                                       "note": f"{v1['reason']} | {v2['reason']}"})
                    result = "relocated"
                else:
                    rows.append(row | {"decision": "nolink",
                                       "reason": f"georeference check: {d['current']['lat']}/{d['current']['lon']} is not the place meant; no agreed replacement",
                                       "note": f"{v1['reason']} | {v2['reason']}"})
                    result = "coordinates removed"
            elif a == "correct" and b == "correct":
                result = "confirmed"
            else:
                result = "open"
                open_rows.append({"place": d["place"], "lat": d["current"]["lat"], "lon": d["current"]["lon"],
                                  "records": d["n_records"], "gbif_records": d["n_in_gbif_subset"],
                                  "entries": " ".join(d["all_entries"]), "judge1": a, "judge1_reason": v1["reason"],
                                  "judge2": b, "judge2_reason": v2["reason"]})
        elif v1 and i in flagged_ids:
            result = "open"          # no second verdict
        outcome[result] += 1
        judgements.append({"id": i, "place": d["place"], "records": d["n_records"], "gbif_records": d["n_in_gbif_subset"],
                           "judge1": (v1 or {}).get("verdict", ""), "judge2": (v2 or {}).get("verdict", ""), "result": result})
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    for path, fields, data in ((csv_path, FIELDS, rows),
                               (work / "georef_judgements.csv", list(judgements[0]), judgements),
                               (work / "georef_open.csv", list(open_rows[0]) if open_rows else ["place"], open_rows)):
        with path.open("w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
    control = json.loads((work / "p2_ids.json").read_text())["control"] if (work / "p2_ids.json").exists() else []
    ctrl_agree = sum(1 for i in control if second.get(i, {}).get("verdict") == "correct")
    by_result = collections.Counter()
    for j in judgements:
        by_result[j["result"]] += j["records"]
    summary = {"dossiers": len(dossiers), "outcome (places)": dict(outcome), "outcome (records)": dict(by_result),
               "rows": len(rows), "rows applied at confidence >= 0.9": sum(float(r["confidence"]) >= 0.9 for r in rows),
               "control": {"sample": len(control), "second judge also correct": ctrl_agree}}
    (work / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dossiers")
    d.add_argument("--export", type=Path, required=True, help="export folder with dwca/ and review/place_link_review.csv")
    d.add_argument("--geonames", type=Path, default=ROOT / "data/cache/linking/geonames")
    d.add_argument("--gbif", type=Path, help="a GBIF archive folder (counts records in the subset)")
    d.add_argument("--min-km", type=float, default=60.0)
    d.add_argument("--mode", choices=("entry", "week"), default="entry",
                   help="entry: far from the rest of its entries; week: far from the records of the surrounding days")
    d.add_argument("--exclude", type=Path, help="a dossiers.json whose places are not repeated")
    d.add_argument("--id-start", type=int, default=0)
    d.add_argument("--name", default="dossiers.json")
    d.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("batches")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--pass", dest="pass_no", type=int, choices=(1, 2), required=True)
    b.add_argument("--n", type=int, default=8)
    b.add_argument("--control", type=int, default=60)
    m = sub.add_parser("merge")
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--export", type=Path, required=True)
    m.add_argument("--csv", type=Path, default=ROOT / "data/review/machine/georef_machine.csv")
    a = ap.parse_args()
    if a.cmd == "dossiers":
        a.out.mkdir(parents=True, exist_ok=True)
        exclude = {(d["place"], d["current"]["lat"], d["current"]["lon"])
                   for d in json.loads(a.exclude.read_text(encoding="utf-8"))} if a.exclude else None
        dossiers = build_dossiers(a.export, a.geonames, a.gbif, a.min_km, a.mode, exclude, a.id_start)
        (a.out / a.name).write_text(json.dumps(dossiers, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(dossiers)} dossiers")
    elif a.cmd == "batches":
        write_batches(a.out, a.pass_no, a.n, a.control)
    else:
        print(json.dumps(merge(a.out, a.csv, a.export), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
