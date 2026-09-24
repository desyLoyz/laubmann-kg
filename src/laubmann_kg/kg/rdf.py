"""Build and serialize the knowledge graph as RDF, conforming to laubmann.ttl 0.5.0.

Design notes
- The data contract is ``kg/model.py``; this module only maps it onto triples.
- Darwin-Core-first: where a dwc/dwciri, DCTERMS, PROV, SKOS, GeoSPARQL or
  schema.org term exists it is emitted alone; ``lkg:`` terms carry only
  project-specific meaning. Every ``lkg:`` class/property emitted here is
  declared in ontologies/laubmann.ttl (tests/test_ontology_alignment.py).
- Explicit partonomy: every child node gets ``dcterms:isPartOf`` (page→volume,
  entry→page|volume, region→page, observation/travel/weather→entry,
  leg→travel event, vocalisation→observation); the parent-side containment
  properties are sub-properties of ``dcterms:hasPart``.
- SHACL runs with ``inference="none"`` (see shacl_validate.py): the grouping
  superclasses (ArchivalUnit / EntryRecord / RecordDetail) are NOT asserted in
  the data; shapes target the concrete classes. Super-properties that shapes or
  consumers rely on are asserted next to the sub-property (mentionsPerson next
  to the role edge).
- Nothing is inferred from prose here: a value is emitted only when the
  extractor set it.
"""

from __future__ import annotations

import hashlib
import logging
import re
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS, XSD

from laubmann_kg.kg.model import (
    DATA_NS,
    DIARIST,
    DiaryEntry,
    DiaryPage,
    DiaryVolume,
    Evidence,
    Habitat,
    Observation,
    Person,
    Place,
    Taxon,
    TravelEvent,
)
from laubmann_kg.normalization import vocabularies as vocab
from laubmann_kg.normalization.vocabularies import basis_of_record, reproductive_condition

if TYPE_CHECKING:
    from laubmann_kg.pipeline import ExtractionResult

logger = logging.getLogger(__name__)

LKG = Namespace("https://w3id.org/laubmann-kg/ontology#")
DWC = Namespace("http://rs.tdwg.org/dwc/terms/")
DWCIRI = Namespace("http://rs.tdwg.org/dwc/iri/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
GSP = Namespace("http://www.opengis.net/ont/geosparql#")
SCHEMA = Namespace("https://schema.org/")
DATA = Namespace(DATA_NS)
DE = "de"

# Evidence kinds map 1:1 onto the SKOS concepts in controlled_vocabularies.ttl.
_EVIDENCE_CONCEPTS = {kind: LKG[f"evidence_{kind}"] for kind in vocab.EVIDENCE_KINDS}
# Person.role -> role-specific mention property (all ⊑ lkg:mentionsPerson).
_MENTION_PROPS = {
    "companion": LKG.mentionsCompanion,
    "source": LKG.mentionsSource,
    "collector": LKG.mentionsCollector,
    "cited-author": LKG.mentionsCitedAuthor,
    "other": LKG.mentionsOther,
}
# GBIF rank name -> Darwin Core term (dwc:class is spelled "class").
_RANK_TERMS = {rank: DWC[rank] for rank in ("kingdom", "phylum", "class", "order", "family", "genus")}


def _uri(uid: str) -> URIRef:
    return DATA[uid]


def _bind(graph: Graph) -> None:
    graph.bind("lkg", LKG)
    graph.bind("dwc", DWC)
    graph.bind("dwciri", DWCIRI)
    # rdflib pre-binds "geo" to GeoSPARQL; force it onto WGS84 so the Turtle
    # reads "geo:lat", not "geo1:lat", and bind GeoSPARQL as "gsp".
    graph.bind("geo", GEO, override=True, replace=True)
    graph.bind("gsp", GSP, override=True, replace=True)
    graph.bind("data", DATA)
    graph.bind("skos", SKOS)
    graph.bind("owl", OWL)
    graph.bind("prov", PROV)
    graph.bind("dcterms", DCTERMS)
    graph.bind("schema", SCHEMA)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)


def _decimal(value: float) -> Literal:
    return Literal(Decimal(str(value)), datatype=XSD.decimal)


def _iri_slug(value: str) -> str:
    """Readable, IRI-safe local-name fragment (model names like 'gemini-2.5-flash')."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-.")
    return slug or "unknown"


def _wkt_point(lat: float, long: float) -> Literal:
    # GeoSPARQL/WKT axis order is longitude latitude.
    return Literal(f"POINT({Decimal(str(long))} {Decimal(str(lat))})", datatype=GSP.wktLiteral)


# --------------------------------------------------------------------------
# Shared referents: taxon, place, person, habitat concept
# --------------------------------------------------------------------------

def _add_taxon(graph: Graph, taxon: Taxon) -> URIRef:
    node = _uri(taxon.uid)
    if (node, RDF.type, LKG.Taxon) in graph:
        return node
    graph.add((node, RDF.type, LKG.Taxon))
    graph.add((node, RDFS.label, Literal(taxon.vernacular_de, lang=DE)))
    graph.add((node, DWC.vernacularName, Literal(taxon.vernacular_de, lang=DE)))
    for alt in taxon.alt_names:                    # merged spellings (entity resolution)
        graph.add((node, SKOS.altLabel, Literal(alt, lang=DE)))
    if taxon.scientific_name:
        graph.add((node, DWC.scientificName, Literal(taxon.scientific_name)))
    else:
        note = taxon.note or "wissenschaftlicher Name nicht aufgelöst"
        graph.add((node, SKOS.note, Literal(note, lang=DE)))
    if taxon.rank:
        graph.add((node, DWC.taxonRank, Literal(taxon.rank)))
    if taxon.is_bird is not None:
        graph.add((node, LKG.isBird, Literal(bool(taxon.is_bird), datatype=XSD.boolean)))
    # GBIF backbone classification of the linked taxon (only ranks GBIF returned)
    for rank, name in taxon.higher_taxonomy:
        term = _RANK_TERMS.get(rank)
        if term is not None:
            graph.add((node, term, Literal(name)))
    # match provenance (how the vernacular was resolved)
    graph.add((node, LKG.matchMethod, Literal(taxon.match_method)))
    if taxon.confidence is not None:
        graph.add((node, LKG.matchConfidence, _decimal(taxon.confidence)))
    if taxon.gbif_match_type:
        graph.add((node, LKG.gbifMatchType, Literal(taxon.gbif_match_type)))
    if taxon.taxon_iri:
        graph.add((node, OWL.sameAs, URIRef(taxon.taxon_iri)))
    if taxon.gbif_key:
        gbif = URIRef(f"https://www.gbif.org/species/{taxon.gbif_key}")
        if taxon.gbif_match_type == "HIGHERRANK":
            pred = SKOS.broadMatch          # genus anchor is broader, not equal
        elif taxon.match_method == "llm+gbif" or taxon.gbif_match_type == "FUZZY":
            pred = SKOS.closeMatch          # LLM-mediated or fuzzy: weaker claim
        else:
            pred = SKOS.exactMatch
        graph.add((node, pred, gbif))
        if taxon.gbif_match_type != "HIGHERRANK":
            graph.add((node, DWC.taxonID, Literal(str(gbif))))
    return node


def _add_place(graph: Graph, place: Place) -> URIRef:
    node = _uri(place.uid)
    if (node, RDF.type, LKG.Place) not in graph:
        graph.add((node, RDF.type, LKG.Place))
        graph.add((node, RDFS.label, Literal(place.name, lang=DE)))
        graph.add((node, DWC.verbatimLocality, Literal(place.verbatim)))
        for alt in place.alt_names:
            graph.add((node, SKOS.altLabel, Literal(alt, lang=DE)))
        if place.kind:
            graph.add((node, LKG.placeKind, Literal(place.kind)))
        if place.lat is not None and place.long is not None:
            graph.add((node, GEO.lat, _decimal(place.lat)))
            graph.add((node, GEO.long, _decimal(place.long)))
            graph.add((node, DWC.decimalLatitude, _decimal(place.lat)))
            graph.add((node, DWC.decimalLongitude, _decimal(place.long)))
            graph.add((node, DWC.geodeticDatum, Literal("WGS84")))
            graph.add((node, GSP.asWKT, _wkt_point(place.lat, place.long)))
            if place.coordinate_uncertainty_m:
                graph.add((node, DWC.coordinateUncertaintyInMeters, Literal(int(place.coordinate_uncertainty_m), datatype=XSD.integer)))
            if place.georef_source:
                graph.add((node, DWC.georeferenceSources, Literal(_GEOREF_SOURCES.get(place.georef_source, place.georef_source))))
        # gazetteer identity (linking/places.py): GeoNames feature, Wikidata item
        if place.geonames_id:
            graph.add((node, OWL.sameAs, URIRef(f"https://sws.geonames.org/{int(place.geonames_id)}/")))
        if place.wikidata_iri:
            graph.add((node, OWL.sameAs, URIRef(place.wikidata_iri)))
    return node


_GEOREF_SOURCES = {
    "gazetteer": "built-in gazetteer (normalization/places.py)",
    "osm+geonames": "OpenStreetMap/Nominatim name match, confirmed by GeoNames (point = GeoNames feature)",
    "osm": "OpenStreetMap/Nominatim name match",
    "geonames": "GeoNames name match (unique in home region)",
    "reviewed": "reviewed place_link_review.csv",
}


def _add_person(graph: Graph, person: Person) -> URIRef:
    node = _uri(person.uid)
    if (node, RDF.type, LKG.Person) not in graph:
        graph.add((node, RDF.type, LKG.Person))
        graph.add((node, RDFS.label, Literal(person.name)))
        graph.add((node, SCHEMA.name, Literal(person.name)))
    for alt in person.alt_names:                   # merged name variants (entity resolution)
        graph.add((node, SKOS.altLabel, Literal(alt)))
    # Outside the type guard: an enriched Person instance may arrive after a
    # bare one; rdflib set semantics dedupes the repeated add. The role is NOT
    # a property of the shared person node — it sits on the mention edge.
    if person.wikidata_iri:
        graph.add((node, OWL.sameAs, URIRef(person.wikidata_iri)))
    if person.gnd_iri:
        graph.add((node, OWL.sameAs, URIRef(person.gnd_iri)))
    return node


def _add_habitat_concept(graph: Graph, habitat: Habitat) -> URIRef:
    """Shared habitat concept: one skos:Concept per label in lkg:habitatScheme,
    reused by every observation that names it (habitats connect species)."""
    node = _uri(habitat.uid)
    if (node, RDF.type, SKOS.Concept) not in graph:
        graph.add((node, RDF.type, SKOS.Concept))
        graph.add((node, RDFS.label, Literal(habitat.label, lang=DE)))
        graph.add((node, SKOS.prefLabel, Literal(habitat.label, lang=DE)))
        graph.add((node, SKOS.inScheme, LKG.habitatScheme))
        for alt in habitat.alt_labels:
            graph.add((node, SKOS.altLabel, Literal(alt, lang=DE)))
        graph.add((LKG.habitatScheme, RDF.type, SKOS.ConceptScheme))
        if habitat.eunis_uri and habitat.eunis_code:
            _add_eunis_link(graph, node, habitat)
    return node


_EUNIS_MATCH = {"exact": SKOS.exactMatch, "close": SKOS.closeMatch, "broad": SKOS.broadMatch}
EUNIS_SCHEME = URIRef("http://eunis.eea.europa.eu/eunishabitats/")
# The EUNIS web application is retired (the concept URIs are identifiers, not
# pages); these two are maintained: the Eionet Data Dictionary concept view
# (label, definition, hierarchy) and the BISE hierarchical view of the 2012
# classification (searchable by code).
EUNIS_DD_PAGE = "https://dd.eionet.europa.eu/vocabulary/biodiversity/eunishabitats/{code}"
EUNIS_BISE_PAGE = "https://biodiversity.europa.eu/resources/search-habitat/eunis-habitat-types-hierarchical-view-2012?searchTerm={code}"


def _add_eunis_concept(graph: Graph, code: str, label: str, uri: str) -> URIRef:
    """A EUNIS habitat class as an external skos:Concept (Eionet vocabulary
    URI), with its label and notation cached in the graph and rdfs:seeAlso
    links to the maintained pages."""
    node = URIRef(uri)
    if (node, RDF.type, SKOS.Concept) not in graph:
        graph.add((node, RDF.type, SKOS.Concept))
        graph.add((node, SKOS.prefLabel, Literal(label, lang="en")))
        graph.add((node, RDFS.label, Literal(f"{code} {label}", lang="en")))
        graph.add((node, SKOS.notation, Literal(code)))
        graph.add((node, SKOS.inScheme, EUNIS_SCHEME))
        graph.add((node, RDFS.seeAlso, URIRef(EUNIS_DD_PAGE.format(code=code))))
        graph.add((node, RDFS.seeAlso, URIRef(EUNIS_BISE_PAGE.format(code=code))))
        graph.add((EUNIS_SCHEME, RDF.type, SKOS.ConceptScheme))
    return node


def _add_eunis_link(graph: Graph, habitat_node: URIRef, habitat: Habitat) -> None:
    """habitat concept -> skos:{exact,close,broad}Match -> EUNIS class, plus the
    class's broader chain (so "all woodland" = skos:broader* G)."""
    target = _add_eunis_concept(graph, habitat.eunis_code, habitat.eunis_label or habitat.eunis_code, habitat.eunis_uri)
    graph.add((habitat_node, _EUNIS_MATCH.get(habitat.eunis_match or "close", SKOS.closeMatch), target))
    child = target
    for code, label, uri in habitat.eunis_parents:
        parent = _add_eunis_concept(graph, code, label, uri)
        graph.add((child, SKOS.broader, parent))
        child = parent


# --------------------------------------------------------------------------
# Entry records and their details
# --------------------------------------------------------------------------

def _add_record_links(graph: Graph, node: URIRef, entry_node: URIRef,
                      run: Optional[URIRef]) -> None:
    """Common EntryRecord triples: part of + derived from the entry, generated
    by the run (Observation, TravelEvent, WeatherReport)."""
    graph.add((node, DCTERMS.isPartOf, entry_node))
    graph.add((node, PROV.wasDerivedFrom, entry_node))
    if run is not None:
        graph.add((node, PROV.wasGeneratedBy, run))


def _add_travel_event(graph: Graph, entry_node: URIRef, event: TravelEvent,
                      run: Optional[URIRef] = None) -> None:
    ev = _uri(event.uid)
    graph.add((ev, RDF.type, LKG.TravelEvent))
    graph.add((ev, RDFS.label,
               Literal(f"Reise · {len(event.legs)} Etappe(n)", lang=DE)))
    graph.add((entry_node, LKG.containsTravelEvent, ev))
    _add_record_links(graph, ev, entry_node, run)
    for i, leg in enumerate(event.legs):
        node = _uri(leg.uid(event.uid, i))
        graph.add((node, RDF.type, LKG.TravelLeg))
        graph.add((ev, LKG.hasLeg, node))
        graph.add((node, DCTERMS.isPartOf, ev))
        graph.add((node, LKG.departurePlace, _add_place(graph, leg.departure_place)))
        graph.add((node, LKG.arrivalPlace, _add_place(graph, leg.arrival_place)))
        for via in leg.via_places:
            graph.add((node, LKG.viaPlace, _add_place(graph, via)))
        graph.add((node, LKG.transportMode, Literal(leg.transport_mode)))
        if leg.departure_time:
            graph.add((node, LKG.departureTime,
                       Literal(leg.departure_time, datatype=XSD.dateTime)))
        if leg.arrival_time:
            graph.add((node, LKG.arrivalTime,
                       Literal(leg.arrival_time, datatype=XSD.dateTime)))
        if leg.verbatim:
            # skos:note, NOT lkg:verbatimNotes — that property's rdfs:domain is
            # Observation and would re-type the leg under RDFS inference.
            graph.add((node, SKOS.note, Literal(leg.verbatim, lang=DE)))


def _add_weather(graph: Graph, entry_node: URIRef, entry: DiaryEntry,
                 run: Optional[URIRef] = None) -> None:
    w = entry.weather
    node = _uri(w.uid(entry.entry_uid))
    graph.add((node, RDF.type, LKG.WeatherReport))
    graph.add((node, RDFS.label, Literal(f"Wetter {entry.entry_date}", lang=DE)))
    graph.add((node, LKG.weatherVerbatim, Literal(w.verbatim, lang=DE)))
    if w.temperature_value is not None:
        graph.add((node, LKG.temperatureValue, _decimal(w.temperature_value)))
        if w.temperature_unit:
            graph.add((node, LKG.temperatureUnit, Literal(w.temperature_unit)))
    if w.precipitation:
        graph.add((node, LKG.precipitation, Literal(w.precipitation)))
    if w.wind:
        graph.add((node, LKG.wind, Literal(w.wind, lang=DE)))
    if w.sky:
        graph.add((node, LKG.skyCondition, Literal(w.sky)))
    graph.add((entry_node, LKG.hasWeather, node))
    _add_record_links(graph, node, entry_node, run)


def _add_vocalisation(graph: Graph, obs_node: URIRef, obs_uid: str,
                      evidence: Evidence, index: int) -> URIRef:
    node = _uri(evidence.vocalisation_uid(obs_uid, index))
    graph.add((node, RDF.type, LKG.Vocalisation))
    graph.add((node, DCTERMS.isPartOf, obs_node))
    graph.add((node, LKG.callType, Literal(evidence.call_type or "unknown")))
    # No placeholder transcription: only what the diary actually wrote.
    if evidence.call_transcription:
        graph.add((node, LKG.callTranscription, Literal(evidence.call_transcription)))
    graph.add((obs_node, LKG.hasVocalisation, node))
    return node


def _add_observation(graph: Graph, obs: Observation, entry_node: URIRef,
                     entry_date: Optional[str] = None,
                     run: Optional[URIRef] = None) -> Optional[URIRef]:
    if obs.taxon.vernacular_de is None:
        return None
    node = _uri(obs.uid)
    graph.add((node, RDF.type, LKG.Observation))
    label = f"Beobachtung {obs.taxon.vernacular_de}"
    graph.add((node, RDFS.label, Literal(label, lang=DE)))
    graph.add((node, LKG.observedTaxon, _add_taxon(graph, obs.taxon)))
    if obs.taxon_verbatim and obs.taxon_verbatim != obs.taxon.vernacular_de:
        # the name as written, when resolution merged it into a canonical taxon
        graph.add((node, DWC.verbatimIdentification, Literal(obs.taxon_verbatim, lang=DE)))
    _add_record_links(graph, node, entry_node, run)
    graph.add((node, LKG.verbatimNotes, Literal(obs.verbatim_notes, lang=DE)))

    # --- where: effective place (own locality, else inherited entry place) ---
    if obs.place is not None:
        graph.add((node, LKG.observedAt, _add_place(graph, obs.place)))
    if obs.locality is not None:
        # Own locality stated in the record: consumers can tell it apart from
        # the inherited entry place via hasLocality / dwc:verbatimLocality.
        graph.add((node, LKG.hasLocality, _add_place(graph, obs.locality)))
        graph.add((node, DWC.verbatimLocality, Literal(obs.locality.verbatim)))

    # --- when: the record's own date/time, else the entry date -----------
    event_date = obs.event_date or entry_date
    if event_date:
        graph.add((node, DWC.eventDate, Literal(event_date, datatype=XSD.date)))
    if obs.event_time:
        graph.add((node, DWC.eventTime, Literal(obs.event_time)))
    if obs.time_of_day:
        graph.add((node, LKG.timeOfDay, Literal(obs.time_of_day)))
    if obs.daylight_phase:
        graph.add((node, LKG.daylightPhase, Literal(obs.daylight_phase)))

    # --- Ziel 1: vantage, microhabitat, radius / uncertainty ---------------
    if obs.spatial_context:
        graph.add((node, LKG.spatialContext, Literal(obs.spatial_context, lang=DE)))
    if obs.microhabitat:
        graph.add((node, LKG.microhabitat, Literal(obs.microhabitat, lang=DE)))
    if obs.relative_elevation:
        graph.add((node, LKG.relativeElevation, Literal(obs.relative_elevation, lang=DE)))
    if obs.altitude_m is not None:
        graph.add((node, LKG.altitudeM, _decimal(obs.altitude_m)))
    if obs.estimated_radius_m is not None:
        radius = Literal(int(obs.estimated_radius_m), datatype=XSD.integer)
        graph.add((node, LKG.observationRadiusMeters, radius))
        graph.add((node, DWC.coordinateUncertaintyInMeters, radius))
    if obs.spatial_confidence:
        graph.add((node, LKG.spatialConfidence, Literal(obs.spatial_confidence)))
    if obs.sampling_protocol:
        graph.add((node, DWC.samplingProtocol, Literal(obs.sampling_protocol, lang=DE)))
    if obs.observation_duration_minutes is not None:
        graph.add((node, LKG.observationDurationMinutes,
                   Literal(int(obs.observation_duration_minutes), datatype=XSD.integer)))

    # --- what: status, counts, demography ---------------------------------
    graph.add((node, DWC.occurrenceStatus, Literal(obs.occurrence_status)))
    if obs.individual_count is not None:
        graph.add((node, DWC.individualCount, Literal(int(obs.individual_count), datatype=XSD.integer)))
    if obs.count_min is not None:
        graph.add((node, LKG.individualCountMin, Literal(int(obs.count_min), datatype=XSD.integer)))
    if obs.count_max is not None:
        graph.add((node, LKG.individualCountMax, Literal(int(obs.count_max), datatype=XSD.integer)))
    if obs.count_qualifier:
        graph.add((node, LKG.countQualifier, Literal(obs.count_qualifier)))
    if obs.sex:
        graph.add((node, DWC.sex, Literal(obs.sex)))
    if obs.life_stage:
        graph.add((node, DWC.lifeStage, Literal(obs.life_stage)))
    if obs.vitality:
        graph.add((node, DWC.vitality, Literal(obs.vitality)))
    if obs.identification_qualifier:
        graph.add((node, DWC.identificationQualifier, Literal(obs.identification_qualifier)))
    if obs.breeding_evidence:
        graph.add((node, LKG.breedingEvidence, Literal(obs.breeding_evidence)))
    condition = reproductive_condition(obs.breeding_evidence, obs.behaviour)
    if condition:
        graph.add((node, DWC.reproductiveCondition, Literal(condition)))
    if obs.movement_kind:
        graph.add((node, LKG.movementKind, Literal(obs.movement_kind)))
    if obs.flight_direction:
        graph.add((node, LKG.flightDirection, Literal(obs.flight_direction, lang=DE)))
    if obs.occurrence_remarks:
        graph.add((node, DWC.occurrenceRemarks, Literal(obs.occurrence_remarks, lang=DE)))

    # --- record provenance ------------------------------------------------
    graph.add((node, LKG.recordType, Literal(obs.record_type)))
    graph.add((node, DWC.basisOfRecord,
               Literal(basis_of_record(obs.record_type, (e.kind for e in obs.evidence)))))
    # Unattributed third-party/literature records get NO recordedBy — never
    # fabricate attribution.
    observer = obs.observer or (DIARIST if obs.record_type == "field-observation" else None)
    if observer is not None:
        graph.add((node, DWCIRI.recordedBy, _add_person(graph, observer)))
    if obs.literature_citation:
        graph.add((node, DWC.associatedReferences, Literal(obs.literature_citation, lang=DE)))

    # --- how: evidence kinds, vocalisations, behaviour, habitat -------------
    call_index = 0
    for evidence in obs.evidence:
        concept = _EVIDENCE_CONCEPTS.get(evidence.kind)
        if concept is not None:
            graph.add((node, LKG.evidenceKind, concept))
        if evidence.is_call:
            _add_vocalisation(graph, node, obs.uid, evidence, call_index)
            call_index += 1
    for behaviour in obs.behaviour:
        graph.add((node, DWC.behavior, Literal(behaviour.label, lang=DE)))
    if obs.habitat is not None:
        graph.add((node, DWCIRI.habitat, _add_habitat_concept(graph, obs.habitat)))
        graph.add((node, DWC.habitat, Literal(obs.habitat.label, lang=DE)))
    return node


# --------------------------------------------------------------------------
# Archival units
# --------------------------------------------------------------------------

def _add_entry(graph: Graph, entry: DiaryEntry, run: Optional[URIRef] = None, volume_spans: Optional[dict] = None) -> None:
    node = _uri(entry.uid)
    graph.add((node, RDF.type, LKG.DiaryEntry))
    graph.add((node, RDFS.label, Literal(entry.label, lang=DE)))
    if entry.entry_id:
        graph.add((node, DCTERMS.identifier, Literal(entry.entry_id)))
    if entry.entry_date_end:
        # DwC interval notation for multi-day entries
        graph.add((node, DWC.eventDate, Literal(f"{entry.entry_date}/{entry.entry_date_end}")))
    else:
        graph.add((node, DWC.eventDate, Literal(entry.entry_date, datatype=XSD.date)))
    if entry.verbatim_event_date:
        graph.add((node, DWC.verbatimEventDate, Literal(entry.verbatim_event_date)))
    if entry.date_plausible is not None:
        graph.add((node, LKG.datePlausible,
                   Literal(bool(entry.date_plausible), datatype=XSD.boolean)))
    if entry.date_note:
        graph.add((node, SKOS.note, Literal(entry.date_note, lang=DE)))
    if entry.entry_kind:
        graph.add((node, LKG.entryKind, Literal(entry.entry_kind)))
    if entry.place is not None:
        graph.add((node, LKG.entryPlace, _add_place(graph, entry.place)))
    if entry.text_clean:
        graph.add((node, DWC.fieldNotes, Literal(entry.text_clean)))

    volume = DiaryVolume(entry.volume)
    volume_node = _uri(volume.uid)
    graph.add((volume_node, RDF.type, LKG.DiaryVolume))
    graph.add((volume_node, RDFS.label, Literal(volume.label, lang=DE)))
    span = (volume_spans or {}).get(int(entry.volume))
    if span:
        # the time span the volume covers according to its title page (YYYY-MM/YYYY-MM)
        graph.add((volume_node, DCTERMS.temporal, Literal(f"{span[0]}/{span[1]}")))
    page_node: Optional[URIRef] = None
    if entry.page_uid:
        page = DiaryPage(entry.page_uid, entry.volume, entry.page_id, entry.scan)
        page_node = _uri(page.uid)
        graph.add((page_node, RDF.type, LKG.DiaryPage))
        graph.add((page_node, RDFS.label, Literal(page.label)))
        if page.page_id:
            graph.add((page_node, DCTERMS.identifier, Literal(page.page_id)))
        graph.add((page_node, DCTERMS.isPartOf, volume_node))
    # entry → page (or straight to the volume when the page is unknown)
    graph.add((node, DCTERMS.isPartOf, page_node if page_node is not None else volume_node))
    if entry.region_uid:
        # The layout region on the scanned page whose text became this entry.
        region = _uri(f"region_{entry.region_uid}")
        graph.add((node, LKG.hasSourceRegion, region))
        graph.add((region, RDF.type, LKG.SourceRegion))
        graph.add((region, RDFS.label, Literal(f"Region {entry.region_uid}")))
        if page_node is not None:
            graph.add((region, DCTERMS.isPartOf, page_node))

    for obs in entry.observations:
        obs_node = _add_observation(graph, obs, node, entry.entry_date, run)
        if obs_node is not None:
            graph.add((node, LKG.containsObservation, obs_node))
    for event in entry.travel_events:
        _add_travel_event(graph, node, event, run)
    for person in entry.persons:
        person_node = _add_person(graph, person)
        graph.add((node, LKG.mentionsPerson, person_node))
        role_prop = _MENTION_PROPS.get(person.role or "")
        if role_prop is not None:
            graph.add((node, role_prop, person_node))
    if entry.weather is not None:
        _add_weather(graph, node, entry, run)


# --------------------------------------------------------------------------
# PROV skeleton
# --------------------------------------------------------------------------

def run_uid(provenance: dict) -> Optional[str]:
    """Stable local name of the extraction-run activity, or None when the result
    carries no provenance (e.g. hand-built test results)."""
    if not provenance:
        return None
    key = "|".join(str(provenance.get(k) or "")
                   for k in ("model", "prompt_sha256", "started_at"))
    return f"run_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"


def _add_provenance(graph: Graph, provenance: dict) -> Optional[URIRef]:
    uid = run_uid(provenance)
    if uid is None:
        return None
    run = _uri(uid)
    model = str(provenance.get("model") or "unknown")
    backend = provenance.get("backend")
    graph.add((run, RDF.type, PROV.Activity))
    graph.add((run, RDFS.label, Literal(f"Extraction run · {model}")))
    if provenance.get("method"):
        graph.add((run, RDFS.comment, Literal(str(provenance["method"]))))
    if provenance.get("started_at"):
        graph.add((run, PROV.startedAtTime,
                   Literal(str(provenance["started_at"]), datatype=XSD.dateTime)))
    agent = _uri(f"agent_{_iri_slug(model)}")
    graph.add((run, PROV.wasAssociatedWith, agent))
    graph.add((agent, RDF.type, PROV.SoftwareAgent))
    graph.add((agent, RDFS.label, Literal(model)))
    if backend:
        graph.add((agent, LKG.backend, Literal(str(backend))))
    sha = provenance.get("prompt_sha256")
    if sha:
        prompt = _uri(f"prompt_{str(sha)[:12]}")
        graph.add((run, PROV.used, prompt))
        graph.add((prompt, RDF.type, PROV.Entity))
        graph.add((prompt, RDFS.label, Literal(str(provenance.get("prompt") or "prompt"))))
        graph.add((prompt, DCTERMS.identifier, Literal(str(sha))))
    return run


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def build_graph(result: "ExtractionResult") -> Graph:
    """Build an rdflib Graph. Only dated entries are emitted (SHACL requires
    exactly one dwc:eventDate per entry); undated entries are skipped and logged."""
    graph = Graph()
    _bind(graph)
    run = _add_provenance(graph, getattr(result, "provenance", None) or {})
    skipped = 0
    for entry in result.entries:
        if not entry.entry_date:
            skipped += 1
            continue
        _add_entry(graph, entry, run, getattr(result, 'volume_spans', None))
    if skipped:
        logger.warning("skipped %d undated entries (SHACL dwc:eventDate requirement)", skipped)
    return graph


def serialize_turtle(graph: Graph, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(destination=str(path), format="turtle")
    logger.info("wrote %d triples to %s", len(graph), path)
    return path
