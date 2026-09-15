"""Explorer graph.json (v7 schema) from an ExtractionResult.

The HTML GUI in ``tools/explorer/index.html`` loads this JSON (optionally two
files) so sample runs can be browsed and compared without embedding a
34-volume payload.
"""

from __future__ import annotations

import json
import logging
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from laubmann_kg.kg.model import (
    DIARIST,
    DiaryEntry,
    Habitat,
    Observation,
    Person,
    Place,
    Taxon,
)

logger = logging.getLogger(__name__)

TEMPLATE = Path(__file__).resolve().parents[3] / "tools" / "explorer" / "index.html"


def _obs_uid(obs: Observation) -> str:
    uid = obs.uid
    return uid[4:] if uid.startswith("obs_") else uid


def _page_label(entry: DiaryEntry) -> str:
    scan = f"scan {entry.scan}" if entry.scan else (entry.page_id or entry.page_uid)
    ident = entry.page_id or entry.page_uid
    extra = f" ({ident})" if ident and ident != scan else ""
    return f"Vol. {entry.volume} · {scan}{extra}"


def graph_from_result(result, meta: Optional[dict] = None) -> dict[str, Any]:
    """Compact index-linked graph matching the v7 explorer payload."""
    taxa: list[dict] = []
    places: list[dict] = []
    persons: list[dict] = []
    habitats: list[dict] = []
    tax_i: dict[str, int] = {}
    pl_i: dict[str, int] = {}
    pe_i: dict[str, int] = {}
    hab_i: dict[str, int] = {}
    tax_n: Counter[int] = Counter()
    tax_e: dict[int, set[str]] = defaultdict(set)
    pl_n: Counter[int] = Counter()
    pl_e: dict[int, set[str]] = defaultdict(set)
    pe_n: Counter[int] = Counter()
    pe_e: dict[int, set[str]] = defaultdict(set)
    hab_n: Counter[int] = Counter()

    def intern_taxon(taxon: Taxon) -> int:
        uid = taxon.uid
        if uid not in tax_i:
            tax_i[uid] = len(taxa)
            rec: dict[str, Any] = {
                "u": uid,
                "name": taxon.vernacular_de,
                "sci": taxon.scientific_name,
                "rank": taxon.rank or "species",
                "gbif": str(taxon.gbif_key) if taxon.gbif_key is not None else None,
                "fam": taxon.higher_rank("family"),
                "ord": taxon.higher_rank("order"),
                "bird": taxon.is_bird,
                "n": 0,
                "ne": 0,
            }
            if taxon.alt_names:
                rec["alt"] = list(taxon.alt_names)
            taxa.append(rec)
        return tax_i[uid]

    def intern_place(place: Place) -> int:
        uid = place.uid
        if uid not in pl_i:
            pl_i[uid] = len(places)
            rec = {
                "u": uid,
                "name": place.name,
                "kind": place.kind,
                "lat": place.lat,
                "lon": place.long,
                "verb": place.verbatim,
                "n": 0,
                "ne": 0,
            }
            if place.alt_names:
                rec["alt"] = list(place.alt_names)
            places.append(rec)
        return pl_i[uid]

    def intern_person(person: Person) -> int:
        uid = person.uid
        if uid not in pe_i:
            pe_i[uid] = len(persons)
            rec: dict[str, Any] = {
                "u": uid,
                "name": person.name,
                "roles": person.role,
                "role": person.role,
                "wd": (person.wikidata_iri or "").rsplit("/", 1)[-1] or None,
                "n": 0,
                "ne": 0,
            }
            if person.alt_names:
                rec["alt"] = list(person.alt_names)
            persons.append(rec)
        return pe_i[uid]

    def intern_habitat(habitat: Habitat) -> int:
        uid = habitat.uid
        if uid not in hab_i:
            hab_i[uid] = len(habitats)
            rec: dict[str, Any] = {"u": uid, "name": habitat.label, "n": 0}
            if habitat.alt_labels:
                rec["alt"] = list(habitat.alt_labels)
            habitats.append(rec)
        return hab_i[uid]

    intern_person(DIARIST)

    entries_out: list[dict] = []
    obs_out: list[dict] = []

    for entry in result.entries:
        e_rec: dict[str, Any] = {
            "u": entry.uid,
            "id": entry.entry_id,
            "vol": entry.volume,
            "page": _page_label(entry),
            "date": entry.entry_date or "",
            "vdate": entry.verbatim_event_date or entry.entry_date or "",
            "text": entry.text_clean or "",
            "kind": entry.entry_kind,
        }
        if entry.entry_date_end:
            e_rec["end"] = entry.entry_date_end
        if entry.date_note:
            e_rec["note"] = entry.date_note
        if entry.place is not None:
            pi = intern_place(entry.place)
            e_rec["p"] = pi
            pl_e[pi].add(entry.entry_uid)
        obs_idx: list[int] = []
        for obs in entry.observations:
            oi = len(obs_out)
            rec: dict[str, Any] = {
                "u": _obs_uid(obs),
                "e": entry.uid,
                "st": obs.occurrence_status,
                "d": obs.event_date or entry.entry_date or "",
                "rt": obs.record_type,
                "v": obs.verbatim_notes or "",
            }
            if obs.taxon is not None:
                ti = intern_taxon(obs.taxon)
                rec["t"] = ti
                tax_n[ti] += 1
                tax_e[ti].add(entry.entry_uid)
            if obs.place is not None:
                pi = intern_place(obs.place)
                rec["p"] = pi
                rec["own"] = obs.locality is not None
                pl_n[pi] += 1
                pl_e[pi].add(entry.entry_uid)
            if obs.observer is not None:
                by = intern_person(obs.observer)
                rec["by"] = by
                pe_n[by] += 1
                pe_e[by].add(entry.entry_uid)
            if obs.individual_count is not None:
                rec["n"] = obs.individual_count
            if obs.count_min is not None:
                rec["min"] = obs.count_min
            if obs.count_max is not None:
                rec["max"] = obs.count_max
            if obs.count_qualifier:
                rec["q"] = obs.count_qualifier
            if obs.sex:
                rec["sex"] = obs.sex
            if obs.life_stage:
                rec["ls"] = obs.life_stage
            if obs.breeding_evidence:
                rec["br"] = obs.breeding_evidence
            if obs.vitality:
                rec["vit"] = obs.vitality
            if obs.movement_kind:
                rec["mv"] = obs.movement_kind
            if obs.flight_direction:
                rec["dir"] = obs.flight_direction
            if obs.identification_qualifier:
                rec["iq"] = obs.identification_qualifier
            if obs.event_time:
                rec["tm"] = obs.event_time
            if obs.time_of_day:
                rec["tod"] = obs.time_of_day
            if obs.daylight_phase:
                rec["dl"] = obs.daylight_phase
            if obs.spatial_context:
                rec["sc"] = obs.spatial_context
            if obs.microhabitat:
                rec["mh"] = obs.microhabitat
            if obs.relative_elevation:
                rec["re"] = obs.relative_elevation
            if obs.sampling_protocol:
                rec["sp"] = obs.sampling_protocol
            if obs.estimated_radius_m is not None:
                rec["rad"] = obs.estimated_radius_m
            if obs.spatial_confidence:
                rec["sconf"] = obs.spatial_confidence
            if obs.altitude_m is not None:
                rec["altm"] = obs.altitude_m
            if obs.observation_duration_minutes is not None:
                rec["dur"] = obs.observation_duration_minutes
            if obs.taxon_verbatim:
                rec["tv"] = obs.taxon_verbatim
            if obs.literature_citation:
                rec["cit"] = obs.literature_citation
            if obs.evidence:
                rec["ev"] = [[ev.kind] for ev in obs.evidence]
                voc = [
                    [ev.call_type or "unknown", ev.call_transcription]
                    for ev in obs.evidence if ev.is_call
                ]
                if voc:
                    rec["voc"] = voc
            if obs.behaviour:
                rec["beh"] = [b.label for b in obs.behaviour]
            if obs.habitat is not None:
                hi = intern_habitat(obs.habitat)
                rec["h"] = hi
                hab_n[hi] += 1
            obs_out.append(rec)
            obs_idx.append(oi)
        if obs_idx:
            e_rec["obs"] = obs_idx
        if entry.weather is not None:
            w: dict[str, Any] = {"v": entry.weather.verbatim}
            if entry.weather.temperature_value is not None:
                w["t"] = entry.weather.temperature_value
            if entry.weather.temperature_unit:
                w["u"] = entry.weather.temperature_unit
            if entry.weather.precipitation:
                w["pr"] = entry.weather.precipitation
            if entry.weather.sky:
                w["sky"] = entry.weather.sky
            if entry.weather.wind:
                w["wind"] = entry.weather.wind
            e_rec["w"] = w
        if entry.persons:
            pe_idx = []
            pr: dict[str, str] = {}
            for person in entry.persons:
                pi = intern_person(person)
                pe_idx.append(pi)
                pe_e[pi].add(entry.entry_uid)
                if person.role:
                    pr[str(pi)] = person.role
            e_rec["pe"] = pe_idx
            if pr:
                e_rec["pr"] = pr
        if entry.travel_events:
            e_rec["tr"] = []
            for event in entry.travel_events:
                legs = []
                for leg in event.legs:
                    item: dict[str, Any] = {"mode": leg.transport_mode}
                    if leg.departure_place:
                        item["from"] = intern_place(leg.departure_place)
                        pl_e[item["from"]].add(entry.entry_uid)
                    if leg.arrival_place:
                        item["to"] = intern_place(leg.arrival_place)
                        pl_e[item["to"]].add(entry.entry_uid)
                    if leg.via_places:
                        item["via"] = [intern_place(p) for p in leg.via_places]
                    if leg.departure_time:
                        item["dep"] = leg.departure_time
                    if leg.verbatim:
                        item["v"] = leg.verbatim
                    legs.append(item)
                e_rec["tr"].append(legs)
        entries_out.append(e_rec)

    for i, rec in enumerate(taxa):
        rec["n"] = int(tax_n[i])
        rec["ne"] = len(tax_e[i])
    for i, rec in enumerate(places):
        rec["n"] = int(pl_n[i])
        rec["ne"] = len(pl_e[i])
    for i, rec in enumerate(persons):
        rec["n"] = int(pe_n[i])
        rec["ne"] = len(pe_e[i])
    for i, rec in enumerate(habitats):
        rec["n"] = int(hab_n[i])

    years = sorted({(e.get("date") or "")[:4] for e in entries_out if (e.get("date") or "")[:4]})
    vols: dict[str, str] = {}
    for vol, span in (getattr(result, "volume_spans", {}) or {}).items():
        if isinstance(span, (tuple, list)) and len(span) >= 2:
            vols[str(vol)] = f"{span[0]}/{span[1]}"
        elif span:
            vols[str(vol)] = str(span)
    payload_meta = {
        "source": "pipeline",
        "entries": len(entries_out),
        "observations": len(obs_out),
        "taxa": len(taxa),
        "places": len(places),
        "persons": len(persons),
        "habitats": len(habitats),
        "years": [years[0], years[-1]] if years else [],
        "vols": vols,
    }
    if meta:
        payload_meta.update(meta)
    return {
        "meta": payload_meta,
        "entries": entries_out,
        "obs": obs_out,
        "taxa": taxa,
        "places": places,
        "persons": persons,
        "habitats": habitats,
    }


def write_graph_json(graph: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    logger.info("wrote explorer graph %s (%d entries)", path, len(graph.get("entries") or []))
    return path


def write_explorer(result, output_dir: Path, meta: Optional[dict] = None,
                   template: Optional[Path] = None) -> dict:
    """Write ``html/graph.json`` and copy the explorer shell next to it."""
    output_dir = Path(output_dir)
    html_dir = output_dir / "html"
    graph = graph_from_result(result, meta)
    json_path = write_graph_json(graph, html_dir / "graph.json")
    src = Path(template) if template else TEMPLATE
    html_path = html_dir / "index.html"
    if src.exists():
        html_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, html_path)
    else:
        logger.warning("explorer template missing at %s — graph.json only", src)
    return {"graph": str(json_path), "html": str(html_path) if src.exists() else None,
            "entries": graph["meta"]["entries"], "observations": graph["meta"]["observations"]}
