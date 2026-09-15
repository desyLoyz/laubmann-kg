"""Controlled vocabularies mirroring the SHACL sh:in constraints."""

from __future__ import annotations

import re
from typing import Optional

TRANSPORT_MODES = ("train", "foot", "boat", "car", "carriage", "bicycle", "unknown")
CALL_TYPES = ("song", "call", "alarm", "drumming", "unknown")
COUNT_QUALIFIERS = ("exact", "minimum", "approximate", "plural-unspecified")
EVIDENCE_KINDS = ("visual", "auditory", "nest", "specimen")

# --- Model-provided observation detail (prompts/observation_extraction.md) ---
# The model emits these enum values directly; the mapper only checks membership
# (normalize_enum) and never infers them from prose.
OCCURRENCE_STATUS = ("present", "absent")
SEXES = ("male", "female", "mixed")
LIFE_STAGES = ("adult", "juvenile", "pullus", "immature", "egg", "mixed")
BREEDING_EVIDENCE = ("confirmed", "probable", "possible")      # atlas-style categories
VITALITY = ("alive", "dead")
MOVEMENT_KINDS = ("migrating", "passing-over", "arriving", "departing", "resting", "roosting")
TAXON_RANKS = ("species", "subspecies", "genus", "family", "group", "unknown")
PLACE_KINDS = ("settlement", "locality", "region", "route", "unknown")
ENTRY_KINDS = ("field-day", "species-digest", "retrospective", "correspondence", "other")
TIME_OF_DAY = ("morning", "forenoon", "noon", "afternoon", "evening", "night")
DAYLIGHT_PHASE = ("dawn", "day", "dusk", "night")
SPATIAL_CONFIDENCE = ("high", "medium", "low", "inferred")


def normalize_enum(raw: object, vocabulary: tuple[str, ...]) -> Optional[str]:
    """Strict membership check for model-emitted enum values (case-insensitive,
    '_'/' ' folded to '-'); anything else -> None. No cue guessing."""
    if raw is None or isinstance(raw, bool):
        return None
    value = str(raw).strip().lower().replace("_", "-").replace(" ", "-")
    return value if value in vocabulary else None

# Diary phrasing → evidence kind. Order matters: nest/specimen beat generic sound.
AUDITORY_CUES = (
    "ruft", "rufen", "ruf ", "gesang", "singt", "singen", "sang", "schlägt",
    "schlagen", "schrei", "schreien", "schwirrt", "schnarren", "trommelt",
    "trommeln", "gehört", "hört", "locken", "lockt", "pfeift", "pfiff",
)
NEST_CUES = ("nest", "brut", "gelege", "eier", "horst", "junge")
SPECIMEN_CUES = ("erlegt", "geschossen", "gesammelt", "eingesandt", "präpar", "balg", "sammlung")

SONG_CUES = ("gesang", "singt", "singen", "sang", "schlägt", "schlagen", "schwirrt")
DRUMMING_CUES = ("trommelt", "trommeln")

# Diary phrasing → transport mode, for when the LLM answers in German instead of
# the vocabulary term. Order matters: "kraftwagen" must hit car before "wagen"
# hits carriage.
TRANSPORT_MODE_CUES = (
    ("train", ("bahn", "zug", "eisenbahn", "d-zug", "lokal", "express")),
    ("boat", ("dampfer", "boot", "schiff", "kahn", "fähre", "floß")),
    ("bicycle", ("fahrrad", "rad", "velo")),
    ("car", ("auto", "kraftwagen", "automobil")),
    ("carriage", ("kutsche", "droschke", "fuhrwerk", "chaise", "wagen")),
    ("foot", ("fuß", "fuss", "gegangen", "gelaufen", "marsch", "wander", "spazier")),
)


def normalize_transport_mode(raw: object) -> str:
    """Map an LLM-supplied transport mode onto the SHACL vocabulary."""
    if not raw:
        return "unknown"
    value = str(raw).strip().lower()
    if value in TRANSPORT_MODES:
        return value
    for mode, cues in TRANSPORT_MODE_CUES:
        if any(cue in value for cue in cues):
            return mode
    return "unknown"

# Approximate / plural quantity cues (no exact integer available).
PLURAL_CUES = (
    "einige", "mehrere", "viele", "zahlreiche", "etliche", "manche",
    "einzelne", "verschiedene", "diverse", "wenige", "einigen", "vielen",
)
APPROX_CUES = ("etwa", "ungefähr", "ca.", "circa", "gegen", "an die", "rund")

GERMAN_NUMBER_WORDS = {
    "ein": 1, "eine": 1, "einen": 1, "einem": 1, "einer": 1, "eines": 1,
    "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7,
    "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "ein paar": 2,
    "zwanzig": 20, "dreißig": 30, "hundert": 100,
}


def is_valid(term: str, vocabulary: tuple[str, ...]) -> bool:
    return term in vocabulary


RECORD_TYPES = ("field-observation", "third-party-report", "literature-record")
PRECIPITATION_TYPES = ("rain", "snow", "sleet", "hail", "drizzle", "fog",
                       "thunderstorm", "none")
SKY_CONDITIONS = ("clear", "partly-cloudy", "overcast", "variable")
TEMPERATURE_UNITS = ("C", "R", "F")

# LLM answers in German/prose → record type. Order matters: literature cues win.
RECORD_TYPE_CUES = (
    ("literature-record", ("liter", "zitat", "publik", "citation", "karte", "digest")),
    ("third-party-report", ("third", "bericht", "meldung", "mitteilung", "report", "fremd",
                            "brief", "schriftlich", "schreibt")),
    ("field-observation", ("field", "feld", "eigen", "first", "own")),
)

# Cue order is load-bearing: "Schneeregen" must hit sleet before snow/rain.
PRECIPITATION_CUES = (
    ("sleet", ("schneeregen", "graupel")),
    ("snow", ("schnee", "schneit")),
    ("hail", ("hagel",)),
    ("thunderstorm", ("gewitter",)),
    ("drizzle", ("niesel", "sprüh")),
    ("fog", ("nebel", "dunst")),
    ("rain", ("regen", "regnet", "regner")),
    ("none", ("trocken", "niederschlagsfrei")),
)

# "kein Regen" names the precipitation only to negate it. The negation must sit
# directly before the precipitation word ("kein Regen", "ohne Schnee"); a
# negation elsewhere in the phrase ("Regen, kein Wind") does not negate it.
PRECIPITATION_NEGATION_CUES = ("kein", "keine", "keinerlei", "ohne", "nicht")

SKY_CUES = (
    ("variable", ("wechselnd", "veränderlich", "unbeständig")),
    ("overcast", ("trüb", "trueb", "bedeckt", "grau", "düster", "bezogen")),
    ("partly-cloudy", ("wolkig", "bewölkt", "bewoelkt")),
    ("clear", ("klar", "heiter", "sonnig", "wolkenlos", "schön", "schoen")),
)


def _fold(raw: object, vocabulary: tuple[str, ...], cues) -> Optional[str]:
    if not raw:
        return None
    value = str(raw).strip().lower()
    if value in vocabulary:
        return value
    for term, term_cues in cues:
        if any(cue in value for cue in term_cues):
            return term
    return None


def normalize_record_type(raw: object) -> Optional[str]:
    """Fold onto RECORD_TYPES; None = no usable signal (mapper derives default)."""
    return _fold(raw, RECORD_TYPES, RECORD_TYPE_CUES)


def normalize_precipitation(raw: object) -> Optional[str]:
    result = _fold(raw, PRECIPITATION_TYPES, PRECIPITATION_CUES)
    if result is not None and result != "none":
        value = str(raw).strip().lower()
        if value in PRECIPITATION_TYPES:
            return result                       # enum value: nothing to negate
        precip_cues = tuple(cue for term, cues in PRECIPITATION_CUES
                            if term != "none" for cue in cues)
        for neg in PRECIPITATION_NEGATION_CUES:
            for cue in precip_cues:
                # negation immediately (up to one filler word) before the cue
                if re.search(rf"\b{neg}\b(?:\s+\w+)?\s+\w*{re.escape(cue)}", value):
                    return "none"
    return result


def normalize_sky(raw: object) -> Optional[str]:
    return _fold(raw, SKY_CONDITIONS, SKY_CUES)


def normalize_temperature_unit(raw: object) -> Optional[str]:
    """'°R'/'Réaumur'→'R', 'Celsius'/'°C'/'Zentigrad'→'C', '°F'→'F', else None."""
    if not raw:
        return None
    value = str(raw).strip().lstrip("°").strip().rstrip(".").casefold()
    if value.startswith("grad "):        # "Grad Réaumur" must not classify as "g…"
        value = value[len("grad "):].lstrip()
    if not value:
        return None
    if value.startswith(("c", "z")):
        return "C"
    if value.startswith(("r", "ré")):
        return "R"
    if value.startswith("f"):
        return "F"
    return None


def basis_of_record(record_type: Optional[str], evidence_kinds) -> str:
    """Darwin Core basisOfRecord. Literature wins: a cited record is a
    MaterialCitation even when it concerns a specimen; a specimen the diarist
    handled is a PreservedSpecimen; everything else (first- or second-hand
    sighting) is a HumanObservation."""
    if record_type == "literature-record":
        return "MaterialCitation"
    if any(k == "specimen" for k in evidence_kinds):
        return "PreservedSpecimen"
    return "HumanObservation"


# breeding-evidence categories that imply dwc:reproductiveCondition "breeding"
BREEDING_IMPLIES_BREEDING = ("confirmed", "probable")


def reproductive_condition(breeding_evidence: Optional[str], behaviours) -> Optional[str]:
    """Single Darwin Core reproductiveCondition for a record, shared by the RDF
    emitter and the DwC-A writer: atlas-style confirmed/probable breeding
    evidence -> "breeding"; otherwise the first behaviour that carries one
    (offline backend); None when nothing is stated."""
    if breeding_evidence in BREEDING_IMPLIES_BREEDING:
        return "breeding"
    for behaviour in behaviours:
        value = getattr(behaviour, "reproductive_condition", None)
        if value:
            return value
    return None
