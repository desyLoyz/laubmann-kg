"""RDF emission of the full kg/model.py contract (ontology v0.4.0).

Builds one entry with every field populated, emits the graph, checks the
predicates/datatypes (Darwin-Core-first, explicit partonomy, flattened
evidence/behaviour, shared habitat concepts, role edges), and validates the
Turtle against the SHACL shapes with inference="none".
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS, XSD

from laubmann_kg.kg.jsonld import DEFAULT_CONTEXT, write_jsonld
from laubmann_kg.kg.model import (
    Behaviour,
    DiaryEntry,
    Evidence,
    Habitat,
    Observation,
    Person,
    Place,
    Taxon,
    TravelEvent,
    TravelLeg,
    WeatherReport,
)
from laubmann_kg.kg.rdf import DATA, DWC, DWCIRI, GEO, GSP, LKG, SCHEMA, build_graph, run_uid, serialize_turtle
from laubmann_kg.kg.shacl_validate import run_shacl_validation
from laubmann_kg.kg.sparql import QUERIES, run_all
from laubmann_kg.pipeline import ExtractionResult

REPO_ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = REPO_ROOT / "ontologies" / "laubmann.ttl"
SHAPES = REPO_ROOT / "ontologies" / "shacl_shapes.ttl"

PROVENANCE = {
    "backend": "google", "provider": "google", "model": "gemini-2.5-flash",
    "prompt": "observation_extraction", "prompt_sha256": "ab" * 32,
    "temperature": 0.0, "thinking_level": None,
    "started_at": "2026-08-17T10:00:00+00:00",
    "method": "LLM extraction from diary text (gemini-2.5-flash)",
}


def _full_entry() -> DiaryEntry:
    entry_place = Place("Erlangen", canonical="Erlangen", lat=49.5897, long=11.0039,
                        kind="settlement")
    own = Place("Dechsendorfer Weiher", canonical="Dechsendorfer Weiher", kind="locality")
    stork = Taxon("Storch", scientific_name="Ciconia ciconia", match_method="gazetteer",
                  confidence=0.98, rank="species", is_bird=True,
                  gbif_key=2480962, gbif_match_type="EXACT",
                  higher_taxonomy=(("kingdom", "Animalia"), ("phylum", "Chordata"),
                                   ("class", "Aves"), ("order", "Ciconiiformes"),
                                   ("family", "Ciconiidae"), ("genus", "Ciconia")))
    warblers = Taxon("Rohrsänger", rank="group", is_bird=True)
    entry = DiaryEntry(
        entry_uid="e_rdf1", entry_id="L03-e0001", volume=3, page_uid="p_rdf1",
        page_id="L03-p012", region_uid="r_rdf1", scan="0012",
        entry_date="1919-04-12", verbatim_event_date="12. IV. 1919",
        location_raw="Erlangen", text_clean="Text.",
        place=entry_place, entry_kind="field-day", entry_date_end="1919-04-13",
        date_plausible=True, date_note="Datum aus Kontext korrigiert",
        header_date="1919-04-11",
    )
    absence = Observation(
        entry_uid="e_rdf1", taxon=stork, verbatim_notes="Keine Störche mehr am Weiher",
        place=own, locality=own, individual_count=0, occurrence_status="absent",
        index=0, event_date="1919-04-13", event_time="07:30",
        sex="mixed", life_stage="adult", breeding_evidence="probable",
        vitality="alive", movement_kind="departing", flight_direction="NO→SW",
        identification_qualifier="wohl", count_min=3, count_max=4,
        spatial_context="vom Ufer des Weihers",
        microhabitat="Teichufer",
        relative_elevation="in mäßiger Höhe",
        altitude_m=280.0,
        time_of_day="morning",
        daylight_phase="day",
        sampling_protocol="Ansitz",
        estimated_radius_m=300,
        spatial_confidence="medium",
        observation_duration_minutes=45,
        evidence=[Evidence("auditory", "Lautäußerung", is_call=True, call_type="call"),
                  Evidence("visual", "Sichtbeobachtung")],
        behaviour=[Behaviour("balzend")],
        habitat=Habitat("Weiher / Schilf"),
    )
    plain = Observation(entry_uid="e_rdf1", taxon=warblers, verbatim_notes="Rohrsänger singen",
                        place=entry_place, index=1)   # no evidence, inherits entry place
    heard = Observation(entry_uid="e_rdf1", taxon=warblers, verbatim_notes="Rohrsänger singen zirr zirr",
                        place=entry_place, index=2, count_qualifier="plural-unspecified",
                        evidence=[Evidence("auditory", "Lautäußerung", is_call=True,
                                           call_type="song", call_transcription="zirr zirr")])
    entry.observations = [absence, plain, heard]
    entry.persons = [Person("Kiefer", role="companion"), Person("Naumann", role="cited-author"),
                     Person("Unbekannt"),                       # no role -> generic edge only
                     Person("Wüst", role="source"), Person("Kiel", role="collector"),
                     Person("Frau Laubmann", role="other")]
    entry.weather = WeatherReport("trüb, leichter Regen, schwacher Westwind", temperature_value=8.0,
                                  temperature_unit="C", precipitation="rain", wind="schwacher Westwind",
                                  sky="overcast")
    entry.travel_events = [TravelEvent("e_rdf1", legs=[
        TravelLeg(entry_place, own, transport_mode="foot",
                  via_places=(Place("Kosbach", canonical="Kosbach", kind="settlement"),),
                  departure_time="1919-04-12T06:00:00", arrival_time="1919-04-12T07:15:00",
                  verbatim="zu Fuß über Kosbach")])]
    return entry


def _graph(provenance=PROVENANCE) -> tuple[Graph, DiaryEntry]:
    entry = _full_entry()
    return build_graph(ExtractionResult(entries=[entry], provenance=provenance)), entry


def test_observation_detail_predicates() -> None:
    graph, entry = _graph()
    absence, plain = entry.observations[:2]
    node = DATA[absence.uid]

    # class + partonomy/provenance links to the entry
    assert (node, RDF.type, LKG.Observation) in graph
    assert (node, RDF.type, LKG.ObservationEvent) not in graph
    assert graph.value(node, DCTERMS.isPartOf) == DATA[entry.uid]
    assert graph.value(node, PROV.wasDerivedFrom) == DATA[entry.uid]
    assert (DATA[entry.uid], LKG.containsObservation, node) in graph
    assert graph.value(node, LKG.derivedFromEntry) is None

    # status/counts: DwC term only (no lkg twin)
    assert graph.value(node, DWC.occurrenceStatus) == Literal("absent")
    assert graph.value(node, DWC.individualCount) == Literal(0, datatype=XSD.integer)  # 0 allowed for absences
    assert graph.value(node, LKG.individualCount) is None
    assert graph.value(node, LKG.individualCountMin) == Literal(3, datatype=XSD.integer)
    assert graph.value(node, LKG.individualCountMax) == Literal(4, datatype=XSD.integer)

    # demography / hedge / movement
    assert graph.value(node, DWC.sex) == Literal("mixed")
    assert graph.value(node, DWC.lifeStage) == Literal("adult")
    assert graph.value(node, DWC.vitality) == Literal("alive")
    assert graph.value(node, DWC.identificationQualifier) == Literal("wohl")
    assert graph.value(node, LKG.breedingEvidence) == Literal("probable")
    assert graph.value(node, DWC.reproductiveCondition) == Literal("breeding")
    assert graph.value(node, LKG.movementKind) == Literal("departing")
    assert graph.value(node, LKG.flightDirection) == Literal("NO→SW", lang="de")

    # own date/time vs. inherited entry date
    assert graph.value(node, DWC.eventDate) == Literal("1919-04-13", datatype=XSD.date)
    assert graph.value(node, DWC.eventTime) == Literal("07:30")
    assert graph.value(node, LKG.timeOfDay) == Literal("morning")
    assert graph.value(node, LKG.daylightPhase) == Literal("day")
    assert graph.value(node, LKG.spatialContext) == Literal("vom Ufer des Weihers", lang="de")
    assert graph.value(node, LKG.microhabitat) == Literal("Teichufer", lang="de")
    assert graph.value(node, LKG.relativeElevation) == Literal("in mäßiger Höhe", lang="de")
    assert graph.value(node, LKG.altitudeM).toPython() == Decimal("280.0")
    assert graph.value(node, LKG.observationRadiusMeters) == Literal(300, datatype=XSD.integer)
    assert graph.value(node, DWC.coordinateUncertaintyInMeters) == Literal(300, datatype=XSD.integer)
    assert graph.value(node, LKG.spatialConfidence) == Literal("medium")
    assert graph.value(node, DWC.samplingProtocol) == Literal("Ansitz", lang="de")
    assert graph.value(node, LKG.observationDurationMinutes) == Literal(45, datatype=XSD.integer)
    assert graph.value(DATA[plain.uid], DWC.eventDate) == Literal("1919-04-12", datatype=XSD.date)
    assert graph.value(DATA[plain.uid], DWC.eventTime) is None

    # own locality vs. inherited entry place
    own = DATA[absence.locality.uid]
    assert graph.value(node, LKG.hasLocality) == own
    assert graph.value(node, LKG.observedAt) == own
    assert graph.value(node, DWC.verbatimLocality) == Literal("Dechsendorfer Weiher")
    assert graph.value(DATA[plain.uid], LKG.hasLocality) is None
    assert graph.value(DATA[plain.uid], LKG.observedAt) == DATA[entry.place.uid]

    # attribution: dwciri:recordedBy only (lkg:observedBy is gone)
    diarist = graph.value(node, DWCIRI.recordedBy)
    assert graph.value(diarist, SCHEMA.name) == Literal("Alfred Laubmann")
    assert graph.value(node, LKG.observedBy) is None

    # behaviour flattened to dwc:behavior literals (no BehaviourNote node)
    assert graph.value(node, DWC.behavior) == Literal("balzend", lang="de")
    assert list(graph.subjects(RDF.type, LKG.BehaviourNote)) == []
    assert graph.value(node, LKG.hasBehaviour) is None

    # no evidence stated -> no evidenceKind, no vocalisation at all
    assert list(graph.objects(DATA[plain.uid], LKG.evidenceKind)) == []
    assert list(graph.objects(DATA[plain.uid], LKG.hasVocalisation)) == []


def test_evidence_vocalisation_and_habitat() -> None:
    graph, entry = _graph()
    absence = entry.observations[0]
    node = DATA[absence.uid]
    # evidence kinds are concept links on the observation itself
    assert set(graph.objects(node, LKG.evidenceKind)) == {LKG.evidence_auditory, LKG.evidence_visual}
    assert list(graph.subjects(RDF.type, LKG.ObservationEvidence)) == []
    assert list(graph.subjects(RDF.type, LKG.BirdCall)) == []
    # the call becomes a Vocalisation node, part of the observation
    calls = list(graph.objects(node, LKG.hasVocalisation))
    assert len(calls) == 1
    call = calls[0]
    assert call == DATA[absence.evidence[0].vocalisation_uid(absence.uid, 0)]
    assert (call, RDF.type, LKG.Vocalisation) in graph
    assert graph.value(call, DCTERMS.isPartOf) == node
    assert graph.value(call, LKG.callType) == Literal("call")
    assert graph.value(call, LKG.callTranscription) is None       # no "Ruf" placeholder
    assert Literal("Ruf") not in set(graph.objects(None, None))

    # habitat: shared skos:Concept via dwciri:habitat (+ dwc:habitat literal), no lkg:Habitat class
    habitat = graph.value(node, DWCIRI.habitat)
    assert habitat == DATA[absence.habitat.uid]
    assert (habitat, RDF.type, SKOS.Concept) in graph
    assert (habitat, RDF.type, LKG.Habitat) not in graph
    assert (habitat, RDF.type, LKG.Place) not in graph             # a habitat is NOT a Place
    assert graph.value(habitat, SKOS.prefLabel) == Literal("Weiher / Schilf", lang="de")
    assert graph.value(habitat, SKOS.inScheme) == LKG.habitatScheme
    assert graph.value(habitat, DWC.habitat) is None               # literal sits on the observation
    assert graph.value(node, DWC.habitat) == Literal("Weiher / Schilf", lang="de")
    assert graph.value(node, LKG.hasHabitat) is None


def test_taxon_place_entry_page_predicates() -> None:
    graph, entry = _graph()
    stork = DATA[entry.observations[0].taxon.uid]
    assert graph.value(stork, RDFS.label) == Literal("Storch", lang="de")
    assert graph.value(stork, DWC.vernacularName) == Literal("Storch", lang="de")
    assert graph.value(stork, DWC.scientificName) == Literal("Ciconia ciconia")
    assert graph.value(stork, LKG.vernacularNameDE) is None        # lkg twins gone
    assert graph.value(stork, LKG.scientificName) is None
    assert graph.value(stork, DWC.taxonRank) == Literal("species")
    assert graph.value(stork, LKG.isBird) == Literal(True, datatype=XSD.boolean)
    assert graph.value(stork, LKG.matchMethod) == Literal("gazetteer")
    conf = graph.value(stork, LKG.matchConfidence)
    assert conf.datatype == XSD.decimal and conf.toPython() == Decimal("0.98")
    assert graph.value(stork, LKG.gbifMatchType) == Literal("EXACT")
    assert (stork, SKOS.exactMatch, URIRef("https://www.gbif.org/species/2480962")) in graph
    # GBIF higher classification
    assert graph.value(stork, DWC.kingdom) == Literal("Animalia")
    assert graph.value(stork, DWC["class"]) == Literal("Aves")
    assert graph.value(stork, DWC.order) == Literal("Ciconiiformes")
    assert graph.value(stork, DWC.family) == Literal("Ciconiidae")
    assert graph.value(stork, DWC.genus) == Literal("Ciconia")
    unresolved = DATA[entry.observations[1].taxon.uid]
    assert graph.value(unresolved, DWC.taxonRank) == Literal("group")
    assert graph.value(unresolved, SKOS.note) is not None          # still flags uncertainty
    assert graph.value(unresolved, DWC.family) is None             # unlinked: no classification

    place = DATA[entry.place.uid]
    assert graph.value(place, LKG.placeKind) == Literal("settlement")
    assert graph.value(place, DWC.verbatimLocality) == Literal("Erlangen")
    assert graph.value(place, LKG.verbatimLocality) is None
    lat = graph.value(place, GEO.lat)
    assert lat.datatype == XSD.decimal and lat.toPython() == Decimal("49.5897")
    assert graph.value(place, DWC.decimalLatitude) == lat
    assert graph.value(place, DWC.decimalLongitude) == graph.value(place, GEO.long)
    assert graph.value(place, DWC.geodeticDatum) == Literal("WGS84")
    wkt = graph.value(place, GSP.asWKT)
    assert wkt.datatype == GSP.wktLiteral and str(wkt) == "POINT(11.0039 49.5897)"   # lon lat
    own = DATA[entry.observations[0].locality.uid]
    assert graph.value(own, GSP.asWKT) is None                     # no coordinates -> no WKT

    node = DATA[entry.uid]
    assert graph.value(node, DCTERMS.identifier) == Literal("L03-e0001")
    assert graph.value(node, LKG.entryPlace) == place
    assert graph.value(node, LKG.entryKind) == Literal("field-day")
    # dates: dwc:eventDate only (interval string for multi-day entries)
    assert graph.value(node, DWC.eventDate) == Literal("1919-04-12/1919-04-13")
    assert graph.value(node, LKG.entryDate) is None
    assert graph.value(node, LKG.entryDateEnd) is None
    assert graph.value(node, DWC.verbatimEventDate) == Literal("12. IV. 1919")
    assert graph.value(node, LKG.datePlausible) == Literal(True, datatype=XSD.boolean)
    assert graph.value(node, SKOS.note) == Literal("Datum aus Kontext korrigiert", lang="de")
    assert graph.value(node, LKG.dateNote) is None
    assert graph.value(node, DWC.fieldNotes) == Literal("Text.")
    assert graph.value(node, LKG.rawText) is None

    # partonomy: entry -> page -> volume, region -> page
    page = graph.value(node, DCTERMS.isPartOf)
    assert (page, RDF.type, LKG.DiaryPage) in graph
    assert graph.value(page, DCTERMS.identifier) == Literal("L03-p012")
    volume = graph.value(page, DCTERMS.isPartOf)
    assert (volume, RDF.type, LKG.DiaryVolume) in graph
    # 0.4.2: the volume states its title-page span when the coverage table is known
    graph3 = build_graph(ExtractionResult(entries=[_full_entry()], volume_spans={3: ("1919-09", "1923-06")}))
    assert graph3.value(volume, DCTERMS.temporal) == Literal("1919-09/1923-06")
    assert graph.value(volume, DCTERMS.temporal) is None
    assert graph.value(node, LKG.hasPage) is None and graph.value(node, LKG.hasVolume) is None
    region = graph.value(node, LKG.hasSourceRegion)
    assert region == DATA["region_r_rdf1"]
    assert (region, RDF.type, LKG.SourceRegion) in graph
    assert (region, RDF.type, URIRef("http://www.w3.org/ns/oa#Annotation")) not in graph
    assert graph.value(region, DCTERMS.isPartOf) == page
    assert graph.value(region, RDFS.label) is not None

    # persons: role on the mention edge, generic edge always, no note on the node
    kiefer, naumann, unknown = (DATA[p.uid] for p in entry.persons[:3])
    mentioned = set(graph.objects(node, LKG.mentionsPerson))
    assert mentioned == {DATA[p.uid] for p in entry.persons}
    assert (node, LKG.mentionsCompanion, kiefer) in graph
    assert (node, LKG.mentionsCitedAuthor, naumann) in graph
    assert not any((node, p, unknown) in graph for p in
                   (LKG.mentionsCompanion, LKG.mentionsSource, LKG.mentionsCollector,
                    LKG.mentionsCitedAuthor, LKG.mentionsOther))
    assert graph.value(kiefer, SCHEMA.name) == Literal("Kiefer")
    assert graph.value(kiefer, SKOS.note) is None

    # travel event / weather: entry records with partonomy + provenance
    travel = DATA[entry.travel_events[0].uid]
    assert graph.value(travel, DCTERMS.isPartOf) == node
    assert graph.value(travel, PROV.wasDerivedFrom) == node
    weather = DATA[entry.weather.uid(entry.entry_uid)]
    assert graph.value(weather, DCTERMS.isPartOf) == node
    assert graph.value(weather, PROV.wasDerivedFrom) == node
    assert (node, LKG.hasWeather, weather) in graph


def test_prov_run_skeleton() -> None:
    graph, entry = _graph()
    run = DATA[run_uid(PROVENANCE)]
    assert (run, RDF.type, PROV.Activity) in graph
    assert graph.value(run, RDFS.label) is not None
    started = graph.value(run, PROV.startedAtTime)
    assert started.datatype == XSD.dateTime and str(started) == "2026-08-17T10:00:00+00:00"
    agent = graph.value(run, PROV.wasAssociatedWith)
    assert agent == DATA["agent_gemini-2.5-flash"]
    assert (agent, RDF.type, PROV.SoftwareAgent) in graph
    assert graph.value(agent, RDFS.label) == Literal("gemini-2.5-flash")
    assert graph.value(agent, LKG.backend) == Literal("google")
    prompt = graph.value(run, PROV.used)
    assert prompt == DATA["prompt_" + "ab" * 6]
    assert (prompt, RDF.type, PROV.Entity) in graph
    assert graph.value(prompt, RDFS.label) == Literal("observation_extraction")
    assert graph.value(prompt, DCTERMS.identifier) == Literal("ab" * 32)
    # every observation, travel event and weather report points at the run
    for obs in entry.observations:
        assert graph.value(DATA[obs.uid], PROV.wasGeneratedBy) == run
    for event in entry.travel_events:
        assert graph.value(DATA[event.uid], PROV.wasGeneratedBy) == run
    assert graph.value(DATA[entry.weather.uid(entry.entry_uid)], PROV.wasGeneratedBy) == run
    # stable id: same provenance -> same run IRI
    assert run_uid(dict(PROVENANCE)) == run_uid(PROVENANCE)


def test_empty_provenance_emits_no_run() -> None:
    graph, entry = _graph(provenance={})
    assert list(graph.subjects(RDF.type, PROV.Activity)) == []
    assert list(graph.subjects(PROV.wasGeneratedBy, None)) == []
    assert run_uid({}) is None
    # also when built without the keyword at all (hand-built test results)
    graph2 = build_graph(ExtractionResult(entries=[_full_entry()]))
    assert list(graph2.subjects(RDF.type, PROV.Activity)) == []


def test_offline_pipeline_provenance_without_prompt(sample_config, tmp_path) -> None:
    from laubmann_kg.pipeline import run_pipeline
    result = run_pipeline(sample_config, None)
    assert result.provenance.get("backend") == "offline"
    graph = build_graph(result)
    runs = list(graph.subjects(RDF.type, PROV.Activity))
    assert len(runs) == 1
    assert graph.value(runs[0], PROV.used) is None            # no prompt hash offline
    agent = graph.value(runs[0], PROV.wasAssociatedWith)
    assert graph.value(agent, LKG.backend) == Literal("offline")


def test_turtle_prefixes_and_shacl_conformance(tmp_path) -> None:
    graph, _ = _graph()
    ttl = tmp_path / "full.ttl"
    serialize_turtle(graph, ttl)
    text = ttl.read_text(encoding="utf-8")
    assert "@prefix geo: <http://www.w3.org/2003/01/geo/wgs84_pos#> ." in text
    assert "geo1:" not in text
    for prefix in ("dwciri:", "prov:", "dcterms:", "schema:", "rdfs:"):
        assert f"@prefix {prefix}" in text
    assert run_shacl_validation(data_path=str(ttl), ontology_path=str(ONTOLOGY),
                                shapes_path=str(SHAPES))
    # round-trip: the Turtle re-parses to the same triple count
    reparsed = Graph().parse(str(ttl), format="turtle")
    assert len(reparsed) == len(graph)


def test_jsonld_default_context_is_repo_relative(tmp_path, monkeypatch) -> None:
    assert DEFAULT_CONTEXT.is_absolute() and DEFAULT_CONTEXT.exists()
    monkeypatch.chdir(tmp_path)                        # cwd elsewhere must not matter
    graph, entry = _graph()
    out = write_jsonld(graph, tmp_path / "g.jsonld")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["@context"]["@version"] == 1.1
    nodes = {n["@id"]: n for n in doc["@graph"]}
    obs = nodes["data:" + entry.observations[0].uid]
    assert obs["occurrenceStatus"] == "absent"
    assert obs["hasLocality"] == "data:" + entry.observations[0].locality.uid
    assert obs["wasGeneratedBy"].startswith("data:run_")


def test_competency_queries_run() -> None:
    graph, _ = _graph()
    rows = run_all(graph)
    assert set(rows) == set(QUERIES)
    own = [r for r in rows["CQ7_own_locality_vs_entry_place"] if r["ownLocality"]]
    inherited = [r for r in rows["CQ7_own_locality_vs_entry_place"] if not r["ownLocality"]]
    assert len(own) == 1 and len(inherited) == 2
    assert own[0]["entryPlace"] == "Erlangen" and own[0]["ownLocality"] == "Dechsendorfer Weiher"
    absent = rows["CQ8_absence_records"]
    assert len(absent) == 1 and absent[0]["vernacular"] == "Storch"
    auditory = rows["CQ4_auditory_observations"]
    assert len(auditory) == 2 and {r["callType"] for r in auditory} == {"call", "song"}
    assert {r["transcription"] for r in auditory} == {None, "zirr zirr"}     # optional
    assert rows["CQ9_observations_by_family"][0]["family"] == "Ciconiidae"
    assert rows["CQ10_taxa_by_habitat"][0]["habitat"] == "Weiher / Schilf"
    roles = {(r["person"], str(r["role"]).rsplit("#", 1)[-1]) for r in rows["CQ11_persons_by_role"]}
    assert roles == {("Kiefer", "mentionsCompanion"), ("Naumann", "mentionsCitedAuthor"),
                     ("Wüst", "mentionsSource"), ("Kiel", "mentionsCollector"), ("Frau Laubmann", "mentionsOther")}
    assert rows["CQ6_provenance"][0]["volume"] is not None
    assert all(rows[k] for k in ("CQ1_species_frequency", "CQ2_observations_by_date",
                                 "CQ3_observations_at_place", "CQ5_unresolved_taxa"))


def test_hand_written_fixture_conforms() -> None:
    fixture = REPO_ROOT / "tests" / "fixtures" / "lkg_full.ttl"
    assert run_shacl_validation(data_path=str(fixture), ontology_path=str(ONTOLOGY),
                                shapes_path=str(SHAPES))
    g = Graph().parse(str(fixture), format="turtle")
    assert (None, RDF.type, LKG.Observation) in g
    assert (None, RDF.type, LKG.Vocalisation) in g


def test_ontology_axioms_and_vocabularies_parse() -> None:
    onto = Graph().parse(str(ONTOLOGY), format="turtle")
    onto_iri = URIRef("https://w3id.org/laubmann-kg/ontology")
    assert onto.value(onto_iri, OWL.versionInfo) == Literal("0.5.0")
    # grouping hierarchy
    RICO = URIRef("https://www.ica.org/standards/RiC/ontology#Record")
    assert (LKG.ArchivalUnit, RDFS.subClassOf, RICO) in onto
    assert (LKG.EntryRecord, RDFS.subClassOf, PROV.Entity) in onto
    for cls in ("DiaryVolume", "DiaryPage", "DiaryEntry", "SourceRegion"):
        assert (LKG[cls], RDFS.subClassOf, LKG.ArchivalUnit) in onto, cls
    for cls in ("Observation", "TravelEvent", "WeatherReport"):
        assert (LKG[cls], RDFS.subClassOf, LKG.EntryRecord) in onto, cls
    for cls in ("Vocalisation", "TravelLeg"):
        assert (LKG[cls], RDFS.subClassOf, LKG.RecordDetail) in onto, cls
    assert (LKG.Observation, RDFS.subClassOf, DWC.Occurrence) in onto
    assert (LKG.DiaryEntry, RDFS.subClassOf, DWC.Event) in onto
    assert (LKG.observedTaxon, RDFS.subPropertyOf, DWCIRI.toTaxon) in onto
    assert (LKG.observedAt, RDFS.subPropertyOf, DWCIRI.inDescribedPlace) not in onto
    # partonomy: containment properties are sub-properties of dcterms:hasPart
    for prop in ("containsObservation", "containsTravelEvent", "hasWeather", "hasLeg", "hasVocalisation"):
        assert (LKG[prop], RDFS.subPropertyOf, DCTERMS.hasPart) in onto, prop
    # role edges
    for prop in ("mentionsCompanion", "mentionsSource", "mentionsCollector",
                 "mentionsCitedAuthor", "mentionsOther"):
        assert (LKG[prop], RDFS.subPropertyOf, LKG.mentionsPerson) in onto, prop
    # dropped classes / properties (renamed, flattened, DwC twins, never emitted)
    for name in ("ObservationEvent", "BirdCall", "ObservationEvidence", "BehaviourNote", "Habitat",
                 "Route", "TimeEstimate", "hasEvidence", "hasBehaviour", "hasHabitat",
                 "derivedFromEntry", "hasVolume", "hasPage", "entryDate", "entryDateEnd",
                 "rawText", "dateNote", "vernacularNameDE", "scientificName", "individualCount",
                 "verbatimLocality", "observedBy", "hasRoute", "routePoint", "routeOrder",
                 "hasTimeEstimate", "observedDuring", "hasAnnotation", "placeName"):
        assert (LKG[name], None, None) not in onto, name
    # the habitat scheme is declared in controlled_vocabularies.ttl (see below), not in the ontology
    assert (LKG.habitatScheme, RDF.type, SKOS.ConceptScheme) not in onto
    for prop in ("entryPlace", "hasLocality", "entryKind", "datePlausible",
                 "individualCountMin", "individualCountMax", "breedingEvidence", "movementKind",
                 "flightDirection", "evidenceKind", "hasVocalisation", "callType", "callTranscription",
                 "matchMethod", "matchConfidence", "gbifMatchType", "isBird", "placeKind",
                 "recordType", "backend", "spatialContext", "microhabitat", "relativeElevation",
                 "observationRadiusMeters", "spatialConfidence", "timeOfDay", "daylightPhase",
                 "observationDurationMinutes", "altitudeM"):
        assert (LKG[prop], RDFS.label, None) in onto, prop

    from laubmann_kg.normalization import vocabularies as vocab
    vocabs = Graph().parse(str(REPO_ROOT / "ontologies" / "controlled_vocabularies.ttl"),
                           format="turtle")

    def _values(scheme: URIRef) -> set[str]:
        return {str(label) for concept in vocabs.subjects(SKOS.inScheme, scheme)
                for label in vocabs.objects(concept, SKOS.prefLabel) if label.language == "en"}

    assert _values(LKG.occurrenceStatusScheme) == set(vocab.OCCURRENCE_STATUS)
    assert _values(LKG.sexScheme) == set(vocab.SEXES)
    assert _values(LKG.lifeStageScheme) == set(vocab.LIFE_STAGES)
    assert _values(LKG.breedingEvidenceScheme) == set(vocab.BREEDING_EVIDENCE)
    assert _values(LKG.vitalityScheme) == set(vocab.VITALITY)
    assert _values(LKG.movementKindScheme) == set(vocab.MOVEMENT_KINDS)
    assert _values(LKG.taxonRankScheme) == set(vocab.TAXON_RANKS)
    assert _values(LKG.placeKindScheme) == set(vocab.PLACE_KINDS)
    assert _values(LKG.entryKindScheme) == set(vocab.ENTRY_KINDS)
    assert _values(LKG.evidenceKindScheme) == set(vocab.EVIDENCE_KINDS)
    assert (LKG.habitatScheme, RDF.type, SKOS.ConceptScheme) in vocabs


def test_shapes_encode_relaxed_constraints() -> None:
    # Warning-severity regressions would not fail run_shacl_validation, so pin
    # the load-bearing shape changes on the shapes graph itself.
    from rdflib.namespace import SH
    shapes = Graph().parse(str(SHAPES), format="turtle")
    assert shapes.value(URIRef("https://w3id.org/laubmann-kg/shapes"), OWL.versionInfo) == Literal("0.5.0")
    call = next(shapes.subjects(SH.path, LKG.callTranscription))
    assert shapes.value(call, SH.minCount) is None                # optional transcription
    assert shapes.value(call, SH.maxCount).toPython() == 1
    count = next(p for p in shapes.subjects(SH.path, DWC.individualCount)
                 if shapes.value(p, SH.minInclusive) is not None)
    assert shapes.value(count, SH.minInclusive).toPython() == 0    # absences may carry 0
    evidence = next(shapes.subjects(SH.path, LKG.evidenceKind))
    assert shapes.value(evidence, SH.maxCount).toPython() == 4
    assert shapes.value(evidence, SH.minCount) is None
    # DwC-first paths are constrained on the Observation shape
    obs_paths = {shapes.value(p, SH.path)
                 for p in shapes.objects(LKG.ObservationShape, SH.property)}
    assert {DWC.occurrenceStatus, DWC.sex, DWC.lifeStage, DWC.vitality, LKG.breedingEvidence,
            LKG.movementKind, LKG.hasLocality, LKG.individualCountMin, DWC.eventDate,
            DWC.eventTime, LKG.countQualifier, DWCIRI.habitat, DWCIRI.recordedBy,
            LKG.hasVocalisation, DWC.behavior, LKG.spatialContext, LKG.microhabitat,
            LKG.relativeElevation, LKG.timeOfDay, LKG.daylightPhase,
            LKG.observationRadiusMeters, LKG.spatialConfidence,
            LKG.observationDurationMinutes, LKG.altitudeM} <= obs_paths
    # weather: several reports per entry allowed (no maxCount on hasWeather)
    weather = next(shapes.subjects(SH.path, LKG.hasWeather))
    assert shapes.value(weather, SH.maxCount) is None
    # partonomy is a Violation-level requirement for every entry record
    assert {LKG.Observation, LKG.TravelEvent, LKG.WeatherReport} <= \
        set(shapes.objects(LKG.EntryRecordShape, SH.targetClass))
    part = next(p for p in shapes.objects(LKG.EntryRecordShape, SH.property)
                if shapes.value(p, SH.path) == DCTERMS.isPartOf)
    assert shapes.value(part, SH.minCount).toPython() == 1 and shapes.value(part, SH.severity) == SH.Violation
    # habitat concepts are addressed as objects of dwciri:habitat (no class shape)
    assert (LKG.HabitatConceptShape, SH.targetObjectsOf, DWCIRI.habitat) in shapes
    for old in ("ObservationEventShape", "HabitatShape", "BirdCallShape", "ObservationEvidenceShape",
                "BehaviourNoteShape", "RouteShape", "TimeEstimateShape", "NoOrphanObservationShape"):
        assert (LKG[old], None, None) not in shapes, old
