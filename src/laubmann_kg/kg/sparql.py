"""Competency-question SPARQL queries over the graph (checked against ontology 0.7.1).

The queries use the Darwin-Core-first vocabulary of the emitted graph:
``dwc:vernacularName`` / ``dwc:scientificName`` on taxa, ``dwc:eventDate`` on
entries, ``dcterms:isPartOf`` for the partonomy, ``lkg:evidenceKind`` values
and ``lkg:callType`` / ``lkg:callTranscription`` for how the bird was detected.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from rdflib import Graph

logger = logging.getLogger(__name__)

PREFIXES = """
PREFIX lkg:     <https://w3id.org/laubmann-kg/ontology#>
PREFIX dwc:     <http://rs.tdwg.org/dwc/terms/>
PREFIX dwciri:  <http://rs.tdwg.org/dwc/iri/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
"""

# Keyed by the competency-question id in docs/competency_questions.md.
QUERIES: dict[str, str] = {
    "CQ1_species_frequency": PREFIXES + """
        SELECT ?vernacular (COUNT(?obs) AS ?n) WHERE {
            ?obs a lkg:Observation ; lkg:observedTaxon ?t .
            ?t dwc:vernacularName ?vernacular .
        } GROUP BY ?vernacular ORDER BY DESC(?n)
    """,
    # dwc:eventDate is xsd:date for single-day entries and a "start/end" string
    # for multi-day entries; STR() keeps both sortable in one column.
    "CQ2_observations_by_date": PREFIXES + """
        SELECT ?date (COUNT(?obs) AS ?n) WHERE {
            ?entry a lkg:DiaryEntry ; dwc:eventDate ?d ;
                   lkg:containsObservation ?obs .
            BIND(STR(?d) AS ?date)
        } GROUP BY ?date ORDER BY ?date
    """,
    "CQ3_observations_at_place": PREFIXES + """
        SELECT ?place ?vernacular WHERE {
            ?obs a lkg:Observation ; lkg:observedAt ?p ;
                 lkg:observedTaxon ?t .
            ?p rdfs:label ?place .
            ?t dwc:vernacularName ?vernacular .
        } ORDER BY ?place
    """,
    # Auditory records: evidence kind, call type and transcription all sit on
    # the observation itself (ontology 0.6.0).
    "CQ4_auditory_observations": PREFIXES + """
        SELECT ?vernacular ?callType ?transcription WHERE {
            ?obs a lkg:Observation ; lkg:observedTaxon ?t ;
                 lkg:evidenceKind "auditory" .
            OPTIONAL { ?obs lkg:callType ?callType }
            OPTIONAL { ?obs lkg:callTranscription ?transcription }
            ?t dwc:vernacularName ?vernacular .
        }
    """,
    "CQ5_unresolved_taxa": PREFIXES + """
        SELECT DISTINCT ?vernacular WHERE {
            ?t a lkg:Taxon ; dwc:vernacularName ?vernacular .
            FILTER NOT EXISTS { ?t dwc:scientificName ?s }
        } ORDER BY ?vernacular
    """,
    # Provenance chain: observation -> entry (part of) -> page -> volume, run.
    "CQ6_provenance": PREFIXES + """
        SELECT ?obs ?entryDate ?page ?volume ?run WHERE {
            ?obs a lkg:Observation ; dcterms:isPartOf ?entry .
            ?entry a lkg:DiaryEntry ; dwc:eventDate ?entryDate .
            OPTIONAL { ?entry dcterms:isPartOf ?page . ?page a lkg:DiaryPage .
                       OPTIONAL { ?page dcterms:isPartOf ?volume } }
            OPTIONAL { ?obs prov:wasGeneratedBy ?run }
        } LIMIT 25
    """,
    # Records that state their OWN locality (lkg:hasLocality) vs. records that
    # inherit the entry place: ?ownLocality is bound only for the former.
    "CQ7_own_locality_vs_entry_place": PREFIXES + """
        SELECT ?vernacular ?effectivePlace ?ownLocality ?entryPlace WHERE {
            ?obs a lkg:Observation ; lkg:observedTaxon ?t ;
                 dcterms:isPartOf ?entry .
            ?t dwc:vernacularName ?vernacular .
            OPTIONAL { ?obs lkg:observedAt ?p . ?p rdfs:label ?effectivePlace }
            OPTIONAL { ?obs lkg:hasLocality ?l . ?l rdfs:label ?ownLocality }
            OPTIONAL { ?entry lkg:entryPlace ?ep . ?ep rdfs:label ?entryPlace }
        } ORDER BY ?vernacular
    """,
    # Explicit absence records ("keine Störche mehr"): occurrenceStatus absent.
    "CQ8_absence_records": PREFIXES + """
        SELECT ?vernacular ?entryDate ?place ?notes WHERE {
            ?obs a lkg:Observation ; dwc:occurrenceStatus "absent" ;
                 lkg:observedTaxon ?t ; dcterms:isPartOf ?entry .
            ?t dwc:vernacularName ?vernacular .
            ?entry dwc:eventDate ?entryDate .
            OPTIONAL { ?obs lkg:observedAt ?p . ?p rdfs:label ?place }
            OPTIONAL { ?obs lkg:verbatimNotes ?notes }
        } ORDER BY ?entryDate ?vernacular
    """,
    # Higher taxonomy from the GBIF link: records per family.
    "CQ9_observations_by_family": PREFIXES + """
        SELECT ?family (COUNT(?obs) AS ?n) WHERE {
            ?obs a lkg:Observation ; lkg:observedTaxon ?t .
            ?t dwc:family ?family .
        } GROUP BY ?family ORDER BY DESC(?n)
    """,
    # Habitats as shared concepts: which taxa were noted in which habitat.
    "CQ10_taxa_by_habitat": PREFIXES + """
        SELECT ?habitat (GROUP_CONCAT(DISTINCT ?vernacular; separator=", ") AS ?taxa) (COUNT(?obs) AS ?n) WHERE {
            ?obs a lkg:Observation ; dwciri:habitat ?h ; lkg:observedTaxon ?t .
            ?h skos:prefLabel ?habitat .
            ?t dwc:vernacularName ?vernacular .
        } GROUP BY ?habitat ORDER BY DESC(?n)
    """,
    # Persons by role on the mention edge (companion, source, collector, ...).
    "CQ11_persons_by_role": PREFIXES + """
        SELECT ?person ?role (COUNT(DISTINCT ?entry) AS ?entries) WHERE {
            { ?entry lkg:mentionsCompanion ?p . BIND(lkg:mentionsCompanion AS ?role) }
            UNION { ?entry lkg:mentionsSource ?p . BIND(lkg:mentionsSource AS ?role) }
            UNION { ?entry lkg:mentionsCollector ?p . BIND(lkg:mentionsCollector AS ?role) }
            UNION { ?entry lkg:mentionsCitedAuthor ?p . BIND(lkg:mentionsCitedAuthor AS ?role) }
            UNION { ?entry lkg:mentionsOther ?p . BIND(lkg:mentionsOther AS ?role) }
            ?p a lkg:Person ; rdfs:label ?person .
        } GROUP BY ?person ?role ORDER BY DESC(?entries)
    """,
}


def run_query(graph: Graph, key: str) -> list[dict]:
    result = graph.query(QUERIES[key])
    rows = []
    for row in result:
        rows.append({str(var): (row[var].toPython() if row[var] is not None else None)
                     for var in result.vars})
    return rows


def run_all(graph: Graph, keys: Iterable[str] | None = None) -> dict[str, list[dict]]:
    return {key: run_query(graph, key) for key in (keys or QUERIES.keys())}


def load_graph(ttl_path: Path) -> Graph:
    graph = Graph()
    graph.parse(str(ttl_path), format="turtle")
    return graph
