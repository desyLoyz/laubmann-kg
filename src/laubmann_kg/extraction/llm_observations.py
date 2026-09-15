"""LLM-backed entry extraction (entry date/place, observations, travel, persons, weather).

Renders the entry-extraction prompt, calls a (cached) LLM client, parses the
structured JSON, and maps it to SHACL-safe domain objects. The model is the
reader and decides the CONTENT (which bird, where, how many, sex, breeding
evidence, whether a record is an absence, who observed it, what the entry's
place and date are). This module only enforces FORM: enum values must be in the
controlled vocabularies (anything else -> None, never guessed from prose),
counts must be integers, dates/times must parse, travel legs need both
endpoints, taxon IRIs come from the resolver/authority (never invented). What
the text does not state stays absent — no default evidence, no default
transcription, no injected behaviours.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from laubmann_kg.kg.model import (
    Behaviour,
    DiaryEntry,
    Evidence,
    Habitat,
    Observation,
    Person,
    Place,
    TravelEvent,
    TravelLeg,
    Taxon,
)
from laubmann_kg.extraction.weather import map_weather
from laubmann_kg.llm.structured_output import extract_json, parse_structured
from laubmann_kg.normalization import vocabularies as vocab
from laubmann_kg.normalization.places import lookup_coordinates, normalize_place
from laubmann_kg.normalization.taxa import TaxonResolver

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path("schemas/observation.schema.json")
_ENTRY_SCHEMA_PATH = Path("schemas/entry_extraction.schema.json")

_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.h](\d{2})\s*$")
_ISO_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")

_PERSON_ROLES = ("companion", "source", "collector", "cited-author", "other")


def load_array_schema(schema_path: Optional[Path] = None) -> dict:
    """Wrap the single-observation schema in an array schema (legacy response
    format; kept for configs/tests that still exercise it)."""
    path = Path(schema_path) if schema_path else _SCHEMA_PATH
    item = json.loads(path.read_text(encoding="utf-8"))
    item.pop("$schema", None)
    return {"type": "array", "items": item}


def load_entry_schema(schema_path: Optional[Path] = None) -> dict:
    """Entry-level response schema ({entry_date, entry_place, entry_kind,
    observations, travel_events, persons, weather}).

    The observation item schema is injected from ``schema_path`` (default
    schemas/observation.schema.json) so it stays single-source."""
    entry = json.loads(_ENTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
    entry.pop("$schema", None)
    item = json.loads((Path(schema_path) if schema_path else _SCHEMA_PATH)
                      .read_text(encoding="utf-8"))
    item.pop("$schema", None)
    entry["properties"]["observations"]["items"] = item
    return entry


# --------------------------------------------------------------------------
# small sanitizers (form only)
# --------------------------------------------------------------------------

def _as_list(value) -> list:
    """Coerce model output to a list: None → [], list → list (minus Nones),
    scalar/dict → [value]. Guards against a bare string being iterated
    character-by-character downstream."""
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v is not None]
    return [value]


def _text(value) -> Optional[str]:
    """Stripped non-empty string, else None (numbers/dicts/lists are not text —
    a citation given as 1949 or {"title": ...} must not become a Python repr)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _sanitize_int(value, minimum: int = 0) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= minimum else None


def _sanitize_bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "ja", "1"):
            return True
        if low in ("false", "no", "nein", "0"):
            return False
    return None


def _sanitize_float(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _sanitize_confidence(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(conf, 0.0), 1.0)


def _iso_date(value) -> Optional[str]:
    """'YYYY-MM-DD' if it is a real calendar date, else None."""
    text = _text(value)
    if not text:
        return None
    m = _ISO_DATE_RE.match(text)
    if not m:
        return None
    year, month, day = (int(g) for g in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1000 <= year <= 2100):
        return None
    import datetime as _dt
    try:
        _dt.date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _clock_time(value) -> Optional[str]:
    text = _text(value)
    if not text:
        return None
    m = _TIME_RE.match(text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _evidence_from(items) -> list[Evidence]:
    """Only evidence the model stated. ``kind`` outside the vocabulary (incl. an
    explicit 'unknown') yields no node; an auditory evidence without a
    transcription has none (no placeholder)."""
    out: list[Evidence] = []
    for item in _as_list(items):
        if isinstance(item, str):
            item = {"kind": item}
        if not isinstance(item, dict):
            continue
        kind = vocab.normalize_enum(item.get("kind"), vocab.EVIDENCE_KINDS)
        if kind is None:
            continue
        if kind == "auditory":
            call_type = vocab.normalize_enum(item.get("call_type"), vocab.CALL_TYPES) or "unknown"
            out.append(Evidence("auditory", "Lautäußerung", is_call=True,
                                call_type=call_type,
                                call_transcription=_text(item.get("call_transcription"))))
        else:
            label = {"visual": "Sichtbeobachtung", "nest": "Nestfund / Brutnachweis",
                     "specimen": "Beleg / erlegtes Stück"}[kind]
            out.append(Evidence(kind, label))
    return out


_DIARIST_ALIASES = {"ich", "wir", "lbm", "l", "laubmann", "a. laubmann",
                    "alfred laubmann", "verfasser", "der verfasser"}

_OBSERVER_PLACEHOLDERS = {"n/a", "na", "unbekannt", "unknown", "null", "none"}

_LETTER_RE = re.compile(r"[^\W\d_]")   # any Unicode letter (covers äöüß, é, …)


def _sanitize_observer(value) -> Optional[str]:
    """Observer name, or None when absent/non-string/garbage/the diarist himself.

    The model sometimes wraps the name ({"name": "Kiel"}, ["Kiel"]); unwrap one
    level rather than dropping it, which would silently re-attribute the record
    to the diarist. Only exact diarist aliases are dropped (a "Frau Laubmann"
    stays a distinct person)."""
    if isinstance(value, dict):
        value = value.get("name")
    elif isinstance(value, list):
        value = next((v for v in value if v is not None), None)
        if isinstance(value, dict):
            value = value.get("name")
    if not isinstance(value, str):
        return None
    name = value.strip().strip("()").strip()
    if not name or not _LETTER_RE.search(name):
        return None
    low = name.lower().rstrip(".")
    if low in _OBSERVER_PLACEHOLDERS or low in _DIARIST_ALIASES:
        return None
    return name


def _resolve_observer(name: str, persons: list[Person]) -> Person:
    """Link an observer name to the entry's persons: exact case-insensitive name
    first (the prompt asks the model to spell it as in ``persons``), then a
    unique surname match ("Kiel" -> "Förster Kiel"); otherwise a fresh Person
    with role 'source'."""
    low = name.casefold()
    for p in persons:
        if p.name.casefold() == low:
            return p
    surname = low.split()[-1].rstrip(".")
    matches = [p for p in persons
               if p.name.casefold().split()[-1].rstrip(".") == surname]
    if len(matches) == 1:
        return matches[0]
    return Person(name=name, role="source")


# --------------------------------------------------------------------------
# places (model-named; gazetteer only adds coordinates)
# --------------------------------------------------------------------------

def _model_place(raw, default_kind: str = "locality",
                 verbatim_fallback: Optional[str] = None) -> Optional[Place]:
    """Build a Place from a model-provided ``{name, verbatim, kind}`` (or bare
    string). The model's ``name`` (modern standard spelling) is the canonical
    label; coordinates come only from the confident gazetteer seeds."""
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict):
        return None
    name = _text(raw.get("name"))
    if not name:
        return None
    kind = vocab.normalize_enum(raw.get("kind"), vocab.PLACE_KINDS) or default_kind
    verbatim = _text(raw.get("verbatim")) or verbatim_fallback or name
    lat, lon = lookup_coordinates(name)
    return Place(verbatim=verbatim, canonical=name, lat=lat, long=lon, kind=kind)


def map_entry_place(raw, location_raw: Optional[str]) -> Optional[Place]:
    """The entry's main place as read by the model. ``None`` when the model says
    there is no usable place (explicit null / kind unknown without name)."""
    place = _model_place(raw, default_kind="settlement",
                         verbatim_fallback=(location_raw or "").strip() or None)
    if place is not None and place.kind == "unknown":
        return None           # the model saw no usable place (QA flags 'nonplace')
    return place


def map_entry_date(raw, header_iso: Optional[str]) -> dict:
    """Return {iso, end_iso, plausible, note}. The model's ISO reading wins when
    it parses; otherwise the upstream header date stands. A silent correction is
    made auditable with an automatic note."""
    out = {"iso": header_iso, "end_iso": None, "plausible": None, "note": None}
    if isinstance(raw, str):
        raw = {"iso": raw}
    if not isinstance(raw, dict):
        return out
    iso = _iso_date(raw.get("iso"))
    if iso:
        out["iso"] = iso
    end_iso = _iso_date(raw.get("end_iso"))
    if end_iso and out["iso"] and end_iso >= out["iso"]:
        out["end_iso"] = end_iso
    out["plausible"] = _sanitize_bool(raw.get("plausible"))
    out["note"] = _text(raw.get("note"))
    if iso and header_iso and iso != header_iso and not out["note"]:
        out["note"] = f"Datum vom Modell korrigiert (Kopfzeile: {header_iso})"
    return out


# --------------------------------------------------------------------------
# observations
# --------------------------------------------------------------------------

def map_items(entry: DiaryEntry, items: list, resolver: TaxonResolver,
              place: Optional[Place]) -> list[Observation]:
    observations: list[Observation] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        vernacular = _text(item.get("vernacular_de"))
        if not vernacular:
            continue
        resolution = resolver.resolve(vernacular)
        llm_sci = _text(item.get("scientific_name"))
        scientific = llm_sci or resolution.scientific_name
        rank = vocab.normalize_enum(item.get("taxon_rank"), vocab.TAXON_RANKS)
        if rank is None and "taxon_rank" in item and item.get("taxon_rank") is not None:
            rank = "unknown"      # the model said something outside the vocabulary
        # A resolver IRI is only meaningful for the resolver's own binomial.
        taxon_iri = resolution.taxon_iri if (
            resolution.taxon_iri and (not llm_sci or llm_sci == resolution.scientific_name)) else None
        taxon = Taxon(
            vernacular_de=vernacular,
            scientific_name=scientific,
            taxon_iri=taxon_iri,
            match_method="llm" if llm_sci else resolution.match_method,
            confidence=_sanitize_confidence(item.get("confidence")),
            note=None if scientific else "wissenschaftlicher Name nicht angegeben",
            rank=rank,
            is_bird=_sanitize_bool(item.get("is_bird")),
        )
        behaviour = [Behaviour(str(b).strip()) for b in _as_list(item.get("behaviour"))
                     if str(b).strip()]
        habitat = _text(item.get("habitat"))
        citation = _text(item.get("literature_citation"))
        observer_name = _sanitize_observer(item.get("observer"))
        observer = None
        if observer_name:
            observer = _resolve_observer(observer_name, entry.persons)
            if observer not in entry.persons:
                entry.persons.append(observer)   # the entry mentions its observers
        flags: list[str] = []
        # membership first; a German label the model used for the same concept
        # ("Literaturangabe") is folded onto the vocabulary — the model's own word,
        # not the diary text, is what gets mapped here
        record_type = vocab.normalize_record_type(item.get("record_type"))
        if record_type is None:
            record_type = ("literature-record" if citation
                           else "third-party-report" if observer is not None
                           else "field-observation")
        elif record_type == "field-observation" and (observer is not None or citation):
            # keep the model's reading, but surface the tension for review
            flags.append("record_type_conflict")
        occurrence_status = vocab.normalize_enum(item.get("occurrence_status"),
                                                 vocab.OCCURRENCE_STATUS) or "present"
        count = _sanitize_int(item.get("individual_count"), minimum=0)
        if count == 0 and occurrence_status != "absent":
            count = None          # a zero is only meaningful for an explicit absence
        count_min = _sanitize_int(item.get("count_min"), minimum=0)
        count_max = _sanitize_int(item.get("count_max"), minimum=0)
        if count_min is not None and count_max is not None and count_max < count_min:
            count_min, count_max = count_max, count_min
        if count is None and count_min is not None:
            count = count_min     # prompt: the lower bound is the count
        locality = _model_place(item.get("locality"), default_kind="locality")
        observations.append(Observation(
            entry_uid=entry.entry_uid,
            taxon=taxon,
            verbatim_notes=_text(item.get("verbatim_notes")) or entry.text_clean or vernacular,
            place=locality or place,
            individual_count=count,
            count_qualifier=vocab.normalize_enum(item.get("count_qualifier"), vocab.COUNT_QUALIFIERS),
            evidence=_evidence_from(item.get("evidence")),
            behaviour=behaviour,
            habitat=Habitat(habitat) if habitat else None,
            index=index,
            record_type=record_type,
            observer=observer,
            literature_citation=citation,
            locality=locality,
            occurrence_status=occurrence_status,
            count_min=count_min,
            count_max=count_max,
            sex=vocab.normalize_enum(item.get("sex"), vocab.SEXES),
            life_stage=vocab.normalize_enum(item.get("life_stage"), vocab.LIFE_STAGES),
            breeding_evidence=vocab.normalize_enum(item.get("breeding_evidence"), vocab.BREEDING_EVIDENCE),
            vitality=vocab.normalize_enum(item.get("vitality"), vocab.VITALITY),
            movement_kind=vocab.normalize_enum(item.get("movement_kind"), vocab.MOVEMENT_KINDS),
            flight_direction=_text(item.get("flight_direction")),
            identification_qualifier=_text(item.get("identification_qualifier")),
            event_date=_iso_date(item.get("event_date")),
            event_time=_clock_time(item.get("event_time")),
            spatial_context=_text(item.get("spatial_context")),
            microhabitat=_text(item.get("microhabitat")),
            relative_elevation=_text(item.get("relative_elevation")),
            altitude_m=_sanitize_float(item.get("altitude_m")),
            time_of_day=vocab.normalize_enum(item.get("time_of_day"), vocab.TIME_OF_DAY),
            daylight_phase=vocab.normalize_enum(item.get("daylight_phase"), vocab.DAYLIGHT_PHASE),
            sampling_protocol=_text(item.get("sampling_protocol")),
            estimated_radius_m=_sanitize_int(item.get("estimated_radius_m"), minimum=1),
            spatial_confidence=vocab.normalize_enum(
                item.get("spatial_confidence"), vocab.SPATIAL_CONFIDENCE),
            observation_duration_minutes=_sanitize_int(
                item.get("observation_duration_minutes"), minimum=1),
            flags=tuple(flags),
        ))
    return observations


# --------------------------------------------------------------------------
# travel
# --------------------------------------------------------------------------

def _travel_place(name) -> Optional[Place]:
    """A travel place named by the model (modern spelling requested); the
    gazetteer only adds coordinates. Falls back to the verbatim string."""
    raw = _text(name)
    if not raw:
        return None
    lat, lon = lookup_coordinates(raw)
    return Place(verbatim=raw, canonical=raw, lat=lat, long=lon, kind="settlement" if lat is not None else None)


def _iso_datetime(entry_date: Optional[str], raw) -> Optional[str]:
    """Combine the entry's ISO date with a stated clock time → xsd:dateTime."""
    if not entry_date:
        return None
    clock = _clock_time(raw)
    return f"{entry_date}T{clock}:00" if clock else None


def map_travel(entry: DiaryEntry, items: list,
               entry_place: Optional[Place]) -> list[TravelEvent]:
    """Map LLM travel events onto SHACL-safe TravelEvent/TravelLeg objects.

    A leg missing its departure inherits the previous leg's arrival, then the
    entry's own place (diary semantics: the entry is written somewhere). Legs
    that still lack either endpoint are dropped; events without surviving legs
    are dropped (TravelEventShape requires >= 1 leg)."""
    events: list[TravelEvent] = []
    for ti, item in enumerate(_as_list(items)):
        if not isinstance(item, dict):
            continue
        raw_legs = _as_list(item.get("legs"))
        if not raw_legs and ("arrival_place" in item or "departure_place" in item):
            # The model frequently emits the event as a bare leg object without
            # the legs wrapper — treat the event itself as its single leg.
            raw_legs = [item]
        legs: list[TravelLeg] = []
        prev_arrival: Optional[Place] = None
        for raw_leg in raw_legs:
            if not isinstance(raw_leg, dict):
                continue
            arrival = _travel_place(raw_leg.get("arrival_place"))
            departure = (_travel_place(raw_leg.get("departure_place"))
                         or prev_arrival or entry_place)
            if arrival is None or departure is None:
                logger.debug("dropping travel leg without both endpoints (%s)",
                             entry.entry_id)
                continue
            dep_t = _iso_datetime(entry.entry_date, raw_leg.get("departure_time"))
            arr_t = _iso_datetime(entry.entry_date, raw_leg.get("arrival_time"))
            if dep_t and arr_t and arr_t <= dep_t:
                arr_t = None  # same-day contradiction (overnight or misread) — keep departure
            legs.append(TravelLeg(
                departure_place=departure,
                arrival_place=arrival,
                via_places=tuple(p for p in (_travel_place(v) for v in
                                             _as_list(raw_leg.get("via_places"))) if p),
                transport_mode=vocab.normalize_transport_mode(raw_leg.get("transport_mode")),
                departure_time=dep_t,
                arrival_time=arr_t,
                verbatim=_text(raw_leg.get("verbatim")),
            ))
            prev_arrival = arrival
        if legs:
            events.append(TravelEvent(entry_uid=entry.entry_uid, legs=legs, index=ti))
    return events


def map_persons(items: list) -> list[Person]:
    out: list[Person] = []
    seen: set[str] = set()
    for item in _as_list(items):
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        role = item.get("role")
        out.append(Person(name=name, role=role if role in _PERSON_ROLES else None))
    return out


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def extract_observations_llm(entry: DiaryEntry, client, resolver: TaxonResolver,
                             place: Optional[Place], prompts, schema: dict) -> list[Observation]:
    """One LLM call per entry. Returns the observations; entry place/date/kind,
    travel_events, persons, and weather are attached to ``entry`` directly.
    Legacy array-only responses (old caches, old schema configs) are accepted
    as bare observations.

    ``place`` is the caller's fallback for the entry place (used only when the
    response carries no ``entry_place`` key at all, e.g. legacy responses).

    Ordering is load-bearing: ``entry.persons`` is assigned before ``map_items``
    runs so ``_resolve_observer`` sees the entry's persons; do not reorder."""
    text = entry.text_clean or ""
    if not text.strip():
        return []
    prompt = prompts.render(
        "observation_extraction",
        entry_date=entry.entry_date or "",
        date_raw=entry.verbatim_event_date or "",
        location=entry.location_raw or "",
        text=text,
    )
    raw = client.complete(prompt)
    try:
        data = parse_structured(raw, schema)
    except Exception as exc:  # noqa: BLE001 - eyeball mode: log and degrade gracefully
        logger.warning("schema validation failed for %s (%s); using lenient parse",
                       entry.entry_id, exc)
        try:
            data = extract_json(raw)
        except Exception:
            logger.error("could not parse LLM output for %s; skipping. raw=%r",
                         entry.entry_id, (raw or "")[:800])
            return []
    if isinstance(data, list):
        data = {"observations": data}
    if not isinstance(data, dict):
        data = {}

    # entry-level reading first: date, place, kind
    entry.header_date = entry.entry_date
    date = map_entry_date(data.get("entry_date"), entry.entry_date)
    entry.entry_date = date["iso"]
    entry.entry_date_end = date["end_iso"]
    entry.date_plausible = date["plausible"]
    entry.date_note = date["note"]
    if "entry_place" in data:
        entry.place = map_entry_place(data.get("entry_place"), entry.location_raw)
    else:
        entry.place = place                    # legacy response: caller's fallback
    entry.entry_kind = vocab.normalize_enum(data.get("entry_kind"), vocab.ENTRY_KINDS)

    entry.travel_events = map_travel(entry, data.get("travel_events"), entry.place)
    entry.persons = map_persons(data.get("persons"))
    entry.weather = map_weather(data.get("weather"))
    items = data.get("observations") or []
    if not isinstance(items, list):
        items = [items]
    return map_items(entry, items, resolver, entry.place)
