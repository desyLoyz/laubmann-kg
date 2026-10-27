"""Reviewed identities of name forms (validation UI export ``review/identities.csv``).

The review unit is the NAME FORM: a taxon, person, place or habitat name as it
is written in the diary. A reviewer decides which entity the form denotes; the
linking and resolution stages then follow that decision instead of their
rules, so a merge is a consequence of two forms denoting the same entity
(same GBIF taxon, same person, same place). Decisions keyed by the written
form survive re-extraction, because the forms come from the text.

CSV contract (one row per decision; extra columns are ignored)::

    section          taxa | persons | places | habitats
    name_form        the written name (matched case-insensitively)
    decision         same      the form denotes ``target`` (taxa: the GBIF taxon in ``authority``)
                     own       the form is an entity of its own: never merged into another,
                               taxa: the automatic GBIF link is dropped
                     none      not a taxon / person / place / habitat at all (misreading,
                               other organism, ...): its mentions are removed
                     mentions  decided per mention (value_corrections.csv), no form-level effect
                     unsure    no effect
                     link      the entity named ``target`` has the identifiers in ``authority``
                               (persons: wd:Q… gnd:…; places: gn:… wd:… osm:… plus lat/lon;
                               habitats: eunis:<code> with ``eunis_match``)
                     nolink    no authority record fits: automatic links are dropped
    target           entity label (another name form) or the form itself
    authority        space-separated prefixed ids: gbif:2494543 wd:Q2546836 gnd:107753448 gn:2867714 osm:relation/62428 eunis:C3.2
    scientific_name, rank, lat, lon, uncertainty_m, eunis_match, reason, note, reviewed_by, reviewed_at
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SECTIONS = ("taxa", "persons", "places", "habitats")
FORM_DECISIONS = ("same", "own", "none", "mentions", "unsure")
LINK_DECISIONS = ("link", "nolink")
IDENTITY_FIELDS = ["section", "name_form", "decision", "target", "authority", "scientific_name", "rank",
                   "lat", "lon", "uncertainty_m", "eunis_match", "reason", "note", "reviewed_by", "reviewed_at"]


def _key(name: str) -> str:
    return (name or "").strip().casefold()


def _float(v: str) -> Optional[float]:
    try:
        return float(v) if (v or "").strip() else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Identity:
    section: str
    name: str
    decision: str
    target: str = ""
    authority: tuple[tuple[str, str], ...] = ()
    scientific_name: str = ""
    rank: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    uncertainty_m: Optional[int] = None
    eunis_match: str = ""
    reason: str = ""
    note: str = ""
    origin: str = "human"            # human (identities.csv) | machine (machine review fallback)

    def auth(self, prefix: str) -> Optional[str]:
        return next((v for p, v in self.authority if p == prefix), None)

    @property
    def gbif_key(self) -> Optional[int]:
        v = self.auth("gbif")
        return int(v) if v and v.isdigit() else None

    @property
    def geonames_id(self) -> Optional[int]:
        v = self.auth("gn")
        return int(v) if v and v.isdigit() else None


@dataclass
class Identities:
    """Form decisions and entity links per section, keyed by the casefolded name."""
    forms: dict[str, dict[str, Identity]] = field(default_factory=lambda: {s: {} for s in SECTIONS})
    links: dict[str, dict[str, Identity]] = field(default_factory=lambda: {s: {} for s in SECTIONS})

    @classmethod
    def load(cls, path, min_confidence: Optional[float] = None, min_agreement: Optional[int] = None,
             origin: str = "human") -> "Identities":
        """Read one identities.csv. ``min_confidence`` / ``min_agreement`` filter
        rows by their ``confidence`` (0-1) and ``agreement`` (number of
        independent sources) columns - the machine review writes both; a row
        without the column passes. Human review files are read without filters."""
        ids = cls()
        if not path:
            return ids
        path = Path(path)
        if not path.exists():
            logger.info("no reviewed identities at %s", path)
            return ids
        dropped = 0
        with path.open(newline="", encoding="utf-8") as handle:
            for i, row in enumerate(csv.DictReader(handle), 2):
                g = lambda k: (row.get(k) or "").strip()   # noqa: E731
                sec, name, dec = g("section").lower(), g("name_form"), g("decision").lower()
                if sec not in SECTIONS or not name or dec not in FORM_DECISIONS + LINK_DECISIONS:
                    logger.warning("%s:%d skipped (section/name_form/decision invalid)", path.name, i)
                    continue
                conf, agree = _float(g("confidence")), _float(g("agreement"))
                if (min_confidence is not None and conf is not None and conf < min_confidence) or \
                        (min_agreement is not None and agree is not None and agree < min_agreement):
                    dropped += 1
                    continue
                auth = tuple(tuple(tok.split(":", 1)) for tok in g("authority").split() if ":" in tok)
                unc = _float(g("uncertainty_m"))
                ident = Identity(sec, name, dec, g("target"), auth, g("scientific_name"), g("rank").lower(),
                                 _float(g("lat")), _float(g("lon")), int(unc) if unc is not None else None,
                                 g("eunis_match").lower(), g("reason"), g("note"), origin)
                (ids.links if dec in LINK_DECISIONS else ids.forms)[sec][_key(name)] = ident
        logger.info("reviewed identities %s: %s%s", path.name, {s: (len(ids.forms[s]), len(ids.links[s])) for s in SECTIONS},
                    f" ({dropped} rows below the confidence/agreement threshold)" if dropped else "")
        return ids

    @classmethod
    def load_layers(cls, human, machine=None, min_confidence: float = 0.9, min_agreement: int = 2) -> "Identities":
        """Human decisions (``human``) completed by the machine review
        (``machine``, ``machine_review/identities_machine.csv``): a machine row
        counts only where no human decision exists for the same name form (or
        entity link) and it clears both thresholds. So a reviewer's decision
        always wins, and the machine fills the forms nobody has looked at.
        ``machine`` may be a list of files; an earlier file wins over a later one
        (a targeted later check such as the georeference check comes first)."""
        ids = cls.load(human)
        for path in ([machine] if isinstance(machine, (str, Path)) else machine or []):
            if path:
                ids.add_fallback(cls.load(path, min_confidence, min_agreement, origin="machine"))
        return ids

    def add_fallback(self, other: "Identities") -> int:
        """Take over every decision of ``other`` whose (section, name) has none here."""
        added = 0
        for table, src in ((self.forms, other.forms), (self.links, other.links)):
            for sec in SECTIONS:
                for key, ident in src[sec].items():
                    if key not in table[sec]:
                        table[sec][key] = ident
                        added += 1
        if added:
            logger.info("machine identities used as fallback: %d", added)
        return added

    def form(self, section: str, name: Optional[str]) -> Optional[Identity]:
        return self.forms[section].get(_key(name)) if name else None

    def link(self, section: str, name: Optional[str]) -> Optional[Identity]:
        return self.links[section].get(_key(name)) if name else None

    def __bool__(self) -> bool:
        return any(self.forms[s] or self.links[s] for s in SECTIONS)


def identities_of(result) -> Identities:
    """The reviewed identities attached to a pipeline result (empty when none)."""
    ids = getattr(result, "identities", None)
    return ids if isinstance(ids, Identities) else Identities()


def apply_mappings(mapping: dict[str, str], names, section: str, ids: Identities) -> int:
    """Override rule-based merges (``mapping``: name -> canonical) with the
    reviewed form decisions of ``section``: ``same`` points the form at its
    target, ``own`` keeps it out of every merge. Targets are matched
    case-insensitively among ``names``; a decision whose target is absent, or
    that would close a cycle, is skipped with a warning. Returns the number of
    applied decisions."""
    present = {_key(n): n for n in names}
    applied = 0

    def root(n: str) -> str:
        seen = set()
        while n in mapping and n not in seen:
            seen.add(n)
            n = mapping[n]
        return n

    for key, ident in ids.forms[section].items():
        n = present.get(key)
        if n is None:
            continue
        if ident.decision == "own":
            if mapping.pop(n, None) is not None:
                applied += 1
            continue
        if ident.decision != "same":
            continue
        t = present.get(_key(ident.target))
        if t is None:
            logger.warning("%s: reviewed target %r of %r not in this run", section, ident.target, n)
            continue
        if t == n:
            mapping.pop(n, None)            # the form is its entity's own label
            applied += 1
            continue
        if root(t) == n:
            logger.warning("%s: reviewed %r -> %r would close a cycle; skipped", section, n, ident.target)
            continue
        mapping[n] = t
        applied += 1
    return applied
