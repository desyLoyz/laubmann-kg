"""Reviewer value corrections: misread species and place names fixed by hand.

The transcription sometimes misreads exactly the value that matters
("Rehhenne" for „Birkhenne" -> the model calls it a roe deer and QA drops the
observation; heading "Rauchschwalben" for „Kaufbeuren" -> no entry place).
A reviewer records the right reading for ONE entry in ``review/value_corrections.csv``
(a misreading is a property of one handwritten line, never of every entry with the
same reading, so there is no corpus-wide scope); this
stage applies it right after extraction, before coverage and QA, so QA,
linking, resolution and the export all see the corrected value. The
transcription and the LLM cache stay untouched.

CSV contract (one row per correction; extra columns are ignored)::

    kind             taxon | place
    entry_uid        required (entry_id alone is accepted as a fallback)
    entry_id         informative
    old_value        the value as extracted (QA ``value``, the merge ``variant``, a link-review name)
    new_value        the right reading
    scientific_name  taxon only, optional: used when the corrected name occurs nowhere else in the run
    is_bird          taxon only, optional: n/no/0 when the corrected organism is not a bird (default: bird)
    note, reviewed_by, reviewed_at   audit only

Resolution of the corrected value: if the new name already occurs elsewhere in
the run, that Taxon/Place object is reused (it carries the model's scientific
name, rank and bird judgement, or the place kind and coordinates); otherwise a
new object is built from the row. Every applied correction and every row that
matched nothing is reported as a QA flag (``value_corrected`` /
``correction_unmatched``), so the audit trail ends up in ``review/qa_flags.csv``.
"""

from __future__ import annotations

import csv
import dataclasses
import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from laubmann_kg.kg.model import DiaryEntry, Place, Taxon
from laubmann_kg.qa import QAFlag

logger = logging.getLogger(__name__)

FIELDS = ["kind", "entry_uid", "entry_id", "old_value", "new_value",
          "scientific_name", "is_bird", "note", "reviewed_by", "reviewed_at"]
_NO = {"n", "no", "0", "false", "nein"}


@dataclass(frozen=True)
class Correction:
    kind: str                       # taxon | place
    old: str
    new: str
    entry_uid: str = ""
    entry_id: str = ""
    scientific_name: str = ""
    is_bird: bool = True
    note: str = ""

    def covers(self, entry: DiaryEntry) -> bool:
        if self.entry_uid:
            return entry.entry_uid == self.entry_uid
        return bool(self.entry_id) and entry.entry_id == self.entry_id


def load_corrections(path) -> list[Correction]:
    path = Path(path)
    if not path.exists():
        logger.info("no value corrections at %s", path)
        return []
    out: list[Correction] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for i, row in enumerate(csv.DictReader(handle), 2):
            g = lambda k: (row.get(k) or "").strip()   # noqa: E731
            kind = g("kind").lower()
            if kind not in ("taxon", "place") or not g("old_value") or not g("new_value"):
                logger.warning("%s:%d skipped (kind/old_value/new_value invalid)", path.name, i)
                continue
            if not (g("entry_uid") or g("entry_id")) or g("scope").lower() not in ("", "entry"):
                logger.warning("%s:%d skipped (corrections apply to one entry: entry_uid required)", path.name, i)
                continue
            out.append(Correction(kind, g("old_value"), g("new_value"), g("entry_uid"), g("entry_id"),
                                  g("scientific_name"), g("is_bird").lower() not in _NO, g("note")))
    return out


def _same(a: Optional[str], b: str) -> bool:
    return a is not None and a.strip().casefold() == b.casefold()


def _taxon_matches(taxon: Taxon, verbatim: Optional[str], old: str) -> bool:
    return _same(taxon.vernacular_de, old) or _same(verbatim, old)


def _place_matches(place: Optional[Place], old: str) -> bool:
    return place is not None and (_same(place.verbatim, old) or _same(place.canonical, old) or _same(place.name, old))


def _known_taxa(entries: Iterable[DiaryEntry]) -> dict[str, Taxon]:
    """Best Taxon object per vernacular name (casefolded): the most frequent
    variant that carries a scientific name, else the most frequent."""
    seen: dict[str, Counter] = {}
    for e in entries:
        for o in e.observations:
            seen.setdefault(o.taxon.vernacular_de.casefold(), Counter())[o.taxon] += 1
    best = {}
    for key, cnt in seen.items():
        ranked = sorted(cnt.items(), key=lambda kv: (kv[0].scientific_name is None, kv[0].is_bird is False, -kv[1]))
        best[key] = ranked[0][0]
    return best


def _known_places(entries: Iterable[DiaryEntry]) -> dict[str, Place]:
    seen: dict[str, Counter] = {}
    for e in entries:
        places = [e.place] + [o.place for o in e.observations] + [o.locality for o in e.observations]
        for p in places:
            if p is not None:
                seen.setdefault(p.name.casefold(), Counter())[p] += 1
    return {k: sorted(c.items(), key=lambda kv: (kv[0].lat is None, kv[0].kind is None, -kv[1]))[0][0]
            for k, c in seen.items()}


def _new_taxon(c: Correction, known: dict[str, Taxon]) -> Taxon:
    t = known.get(c.new.casefold())
    if t is not None and not (c.scientific_name and t.scientific_name != c.scientific_name):
        return t
    sci = c.scientific_name or None
    rank = ("species" if len(sci.split()) == 2 else "subspecies" if len(sci.split()) == 3 else None) if sci else None
    return Taxon(vernacular_de=c.new, scientific_name=sci, match_method="review", confidence=1.0,
                 rank=rank, is_bird=c.is_bird, note="Name bei der Durchsicht korrigiert")


def _new_place(c: Correction, known: dict[str, Place]) -> Place:
    return known.get(c.new.casefold()) or Place(verbatim=c.new)


def _remark(obs, text: str) -> None:
    obs.occurrence_remarks = f"{obs.occurrence_remarks}; {text}" if obs.occurrence_remarks else text


def _fix_legs(entry: DiaryEntry, old: str, new: Place) -> int:
    n = 0
    for ev in entry.travel_events:
        legs = []
        for leg in ev.legs:
            changes = {}
            if _place_matches(leg.departure_place, old):
                changes["departure_place"] = new
            if _place_matches(leg.arrival_place, old):
                changes["arrival_place"] = new
            via = tuple(new if _place_matches(p, old) else p for p in leg.via_places)
            if via != leg.via_places:
                changes["via_places"] = via
            n += bool(changes)
            legs.append(dataclasses.replace(leg, **changes) if changes else leg)
        ev.legs = legs
    return n


def apply_corrections(entries: list[DiaryEntry], corrections: list[Correction]) -> tuple[int, list[QAFlag]]:
    """Apply ``corrections`` in place. Returns (number of changed values, flags)."""
    if not corrections:
        return 0, []
    known_taxa, known_places = _known_taxa(entries), _known_places(entries)
    flags: list[QAFlag] = []
    total = 0
    for c in corrections:
        hits = 0
        for e in entries:
            if not c.covers(e):
                continue
            n = 0
            if c.kind == "taxon":
                new = _new_taxon(c, known_taxa)
                for o in e.observations:
                    if _taxon_matches(o.taxon, o.taxon_verbatim, c.old):
                        o.taxon, o.taxon_verbatim = new, None
                        _remark(o, f"Artname bei der Durchsicht korrigiert: „{c.old}“ → „{c.new}“")
                        n += 1
            else:
                new = _new_place(c, known_places)
                # the entry place, or a heading the model could not use as a place (QA "nonplace")
                old_entry_place = e.place
                header_only = e.place is None and _same(e.location_raw, c.old)
                if _place_matches(e.place, c.old) or header_only:
                    e.place = new
                    n += 1
                entry_changed = e.place is not old_entry_place
                for o in e.observations:
                    if _place_matches(o.locality, c.old):
                        o.locality = new
                        n += 1
                    # effective place: the record's own locality, else the entry place
                    if o.locality is not None:
                        target = o.locality
                    elif _place_matches(o.place, c.old):
                        target = new
                    elif (o.place is None and header_only) or (entry_changed and o.place is old_entry_place):
                        target = e.place
                    else:
                        continue
                    if o.place is not target:
                        o.place = target
                        n += 1
                n += _fix_legs(e, c.old, new)
            if n:
                hits += 1
                total += n
                flags.append(QAFlag(e.entry_id, e.entry_uid, "value_corrected",
                    f"{'Art' if c.kind == 'taxon' else 'Ort'} korrigiert: „{c.old}“ → „{c.new}“ ({n}×)"
                    + (f"; {c.note}" if c.note else ""), "flagged", f"{c.old} -> {c.new}"))
        if not hits:
            flags.append(QAFlag(c.entry_id or "", c.entry_uid or "", "correction_unmatched",
                f"{c.kind}-Korrektur „{c.old}“ → „{c.new}“ passt auf keinen Wert dieses Eintrags",
                "flagged", f"{c.old} -> {c.new}"))
            logger.warning("value correction matched nothing: %s %r -> %r (%s)", c.kind, c.old, c.new, c.entry_uid or c.entry_id)
    logger.info("value corrections: %d rows, %d values changed, %d unmatched", len(corrections), total,
                sum(f.reason == "correction_unmatched" for f in flags))
    return total, flags
