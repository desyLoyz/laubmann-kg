"""Build Darwin Core Occurrence extension rows (one per observation)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from laubmann_kg.dwca.event import dumps_properties, event_date
from laubmann_kg.normalization.vocabularies import basis_of_record, reproductive_condition

if TYPE_CHECKING:
    from laubmann_kg.pipeline import ExtractionResult

FIELDS = [
    "eventID", "occurrenceID", "basisOfRecord",
    "kingdom", "class", "order", "family", "scientificName", "taxonRank", "vernacularName", "taxonID",
    "individualCount", "organismQuantity", "organismQuantityType",
    "occurrenceStatus", "sex", "lifeStage", "reproductiveCondition", "vitality",
    "behavior", "identificationQualifier", "identificationRemarks", "verbatimIdentification",
    "locality", "locationID", "verbatimLocality", "coordinateUncertaintyInMeters",
    "eventDate", "eventTime", "habitat", "samplingProtocol",
    "occurrenceRemarks", "recordedBy", "associatedMedia", "associatedReferences",
    "dynamicProperties",
]

DEFAULT_RECORDED_BY = "Alfred Laubmann"

# taxon.rank values that mean "the diarist named a group, not a species"
_SUPRASPECIFIC_RANKS = ("genus", "family", "group")


def _basis_of_record(obs) -> str:
    return basis_of_record(obs.record_type, (e.kind for e in obs.evidence))


def _recorded_by(obs) -> str:
    if obs.observer is not None:
        return obs.observer.name
    if obs.record_type == "field-observation":
        return DEFAULT_RECORDED_BY          # == model.DIARIST.name
    return ""   # unattributed third-party/literature record: claim nothing


def _identification_remarks(taxon) -> str:
    if taxon.rank in _SUPRASPECIFIC_RANKS:
        return f"Bestimmung auf {taxon.rank}-Niveau"
    if taxon.scientific_name:
        return ""
    return "Art nicht sicher bestimmt; nur Trivialname"


def _reproductive_condition(obs) -> str:
    return reproductive_condition(obs.breeding_evidence, obs.behaviour) or ""


def _higher(taxon, rank: str) -> str:
    """GBIF classification of the linked taxon (kingdom/class/order/family)."""
    getter = getattr(taxon, "higher_rank", None)
    return (getter(rank) if getter else None) or ""


def _kingdom(taxon) -> str:
    # GBIF value when linked; the model's is_bird judgement as fallback
    return _higher(taxon, "kingdom") or ("Animalia" if taxon.is_bird is not False else "")


def _class(taxon) -> str:
    return _higher(taxon, "class") or ("Aves" if taxon.is_bird is True else "")


def _organism_quantity(obs) -> tuple[str, str]:
    if obs.count_min is not None and obs.count_max is not None:
        return f"{obs.count_min}-{obs.count_max}", "individuals (range)"
    return "", ""


def _dynamic_properties(obs) -> str:
    return dumps_properties({
        "movementKind": obs.movement_kind,
        "flightDirection": obs.flight_direction,
        "countMin": obs.count_min,
        "countMax": obs.count_max,
        "breedingEvidence": obs.breeding_evidence,
        "recordType": obs.record_type,
        "timeOfDay": obs.time_of_day,
        "daylightPhase": obs.daylight_phase,
        "spatialContext": obs.spatial_context,
        "microhabitat": obs.microhabitat,
        "relativeElevation": obs.relative_elevation,
        "spatialConfidence": obs.spatial_confidence,
        "observationRadiusMeters": obs.estimated_radius_m,
        "observationDurationMinutes": obs.observation_duration_minutes,
    })


def _coordinate_uncertainty(obs) -> str:
    if obs.estimated_radius_m is not None:
        return str(obs.estimated_radius_m)
    return ""


def _taxon_id(taxon) -> str:
    if taxon.gbif_key and taxon.gbif_match_type != "HIGHERRANK":
        return f"https://www.gbif.org/species/{taxon.gbif_key}"
    return ""


def build_occurrences(result: "ExtractionResult", media_by_entry: dict | None = None) -> list[dict]:
    media_by_entry = media_by_entry or {}
    rows = []
    for entry in result.entries:
        if not entry.entry_date:
            continue
        media = ";".join(media_by_entry.get(entry.entry_uid, []))
        entry_date = event_date(entry)
        for obs in entry.observations:
            taxon = obs.taxon
            quantity, quantity_type = _organism_quantity(obs)
            rows.append({
                "eventID": entry.entry_uid,
                "occurrenceID": obs.uid,
                "basisOfRecord": _basis_of_record(obs),
                "kingdom": _kingdom(taxon),
                "class": _class(taxon),
                "order": _higher(taxon, "order"),
                "family": _higher(taxon, "family"),
                "scientificName": taxon.scientific_name or "",
                "taxonRank": taxon.rank or "",
                "vernacularName": taxon.vernacular_de,
                "taxonID": _taxon_id(taxon),
                # 0 is a real value (absence record), so test against None
                "individualCount": ("" if obs.individual_count is None
                                    else str(obs.individual_count)),
                "organismQuantity": quantity,
                "organismQuantityType": quantity_type,
                "occurrenceStatus": obs.occurrence_status or "present",
                "sex": obs.sex or "",
                "lifeStage": obs.life_stage or "",
                "reproductiveCondition": _reproductive_condition(obs),
                "vitality": obs.vitality or "",
                "behavior": "; ".join(b.label for b in obs.behaviour),
                "identificationQualifier": obs.identification_qualifier or "",
                "identificationRemarks": _identification_remarks(taxon),
                "verbatimIdentification": obs.taxon_verbatim or "",
                "locality": obs.place.name if obs.place is not None else "",
                "locationID": f"https://sws.geonames.org/{obs.place.geonames_id}/" if obs.place is not None and getattr(obs.place, "geonames_id", None) else "",
                "verbatimLocality": obs.locality.verbatim if obs.locality is not None else "",
                "coordinateUncertaintyInMeters": _coordinate_uncertainty(obs),
                # a record without its own date inherits the event's date (or
                # multi-day interval)
                "eventDate": obs.event_date or entry_date,
                "eventTime": obs.event_time or "",
                "habitat": obs.habitat.label if obs.habitat is not None else "",
                "samplingProtocol": obs.sampling_protocol or "",
                "occurrenceRemarks": obs.verbatim_notes,
                "recordedBy": _recorded_by(obs),
                "associatedMedia": media,
                "associatedReferences": (obs.literature_citation or "").replace("\t", " ").replace("\n", " "),
                "dynamicProperties": _dynamic_properties(obs),
            })
    return rows
