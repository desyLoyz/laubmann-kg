"""Ontology <-> emitter <-> SHACL <-> JSON-LD alignment guard (ontology 0.7.0).

The ontology TTL is the single source of truth for the project vocabulary.
This module enforces, in both directions, that

(a) every ``lkg:`` class / predicate / concept the emitter puts into a graph is
    declared (ontology or controlled vocabularies) and no grouping superclass
    is asserted as rdf:type,
(b) every declared ``lkg:`` class (except the grouping superclasses) and every
    declared ``lkg:`` property is actually emitted by the maximal test entry —
    no dead terms in the ontology,
(c) every declared class is targeted by a SHACL shape and every declared
    property is constrained by some property shape,
(d) every ``lkg:`` term in the JSON-LD context is declared and every predicate
    the emitter uses has a context term (compaction is complete),
(e) ontology, shapes, controlled vocabularies and CHANGELOG agree on the version.
"""

from __future__ import annotations

import json
from pathlib import Path

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, SH

from laubmann_kg.kg.rdf import LKG, build_graph
from laubmann_kg.pipeline import ExtractionResult

from test_rdf_emission import PROVENANCE, _full_entry

REPO_ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = REPO_ROOT / "ontologies" / "laubmann.ttl"
VOCABS = REPO_ROOT / "ontologies" / "controlled_vocabularies.ttl"
SHAPES = REPO_ROOT / "ontologies" / "shacl_shapes.ttl"
CONTEXT = REPO_ROOT / "schemas" / "jsonld_context.json"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "lkg_full.ttl"
LKG_NS = str(LKG)
ONTO_IRI = URIRef("https://w3id.org/laubmann-kg/ontology")
SHAPES_IRI = URIRef("https://w3id.org/laubmann-kg/shapes")
# grouping classes: declared for the hierarchy, never asserted in the data
ABSTRACT = {LKG.ArchivalUnit, LKG.EntryRecord}


def _lkg(iris) -> set[URIRef]:
    return {i for i in iris if isinstance(i, URIRef) and str(i).startswith(LKG_NS)}


def _declared() -> tuple[set[URIRef], set[URIRef], set[URIRef]]:
    onto = Graph().parse(str(ONTOLOGY), format="turtle")
    classes = _lkg(onto.subjects(RDF.type, OWL.Class))
    props = _lkg(onto.subjects(RDF.type, OWL.ObjectProperty)) | _lkg(onto.subjects(RDF.type, OWL.DatatypeProperty))
    vocab = Graph().parse(str(VOCABS), format="turtle")
    concepts = _lkg(vocab.subjects(RDF.type, None))          # concept schemes + concepts
    return classes, props, concepts


def _emitted(graph: Graph) -> tuple[set[URIRef], set[URIRef], set[URIRef]]:
    types = _lkg(graph.objects(None, RDF.type))
    preds = _lkg(graph.predicates())
    objects = _lkg(o for p, o in graph.predicate_objects() if p != RDF.type)
    return types, preds, objects


def _coverage_graph() -> Graph:
    """The maximal single-entry graph from test_rdf_emission (every model field set)."""
    return build_graph(ExtractionResult(entries=[_full_entry()], provenance=PROVENANCE,
                                        volume_spans={3: ("1919-09", "1923-06")}))


def test_emitted_terms_are_declared() -> None:
    classes, props, concepts = _declared()
    for name, graph in (("emitter", _coverage_graph()),
                        ("fixture", Graph().parse(str(FIXTURE), format="turtle"))):
        types, preds, objects = _emitted(graph)
        assert types <= classes, f"{name}: undeclared classes {types - classes}"
        assert not (types & ABSTRACT), f"{name}: grouping classes asserted {types & ABSTRACT}"
        assert preds <= props, f"{name}: undeclared predicates {preds - props}"
        assert objects <= concepts | classes, f"{name}: undeclared lkg objects {objects - concepts - classes}"


def test_declared_terms_are_emitted() -> None:
    classes, props, _ = _declared()
    types, preds, _ = _emitted(_coverage_graph())
    assert (classes - ABSTRACT) <= types, f"declared but never emitted classes: {(classes - ABSTRACT) - types}"
    assert props <= preds, f"declared but never emitted properties: {props - preds}"


def test_shapes_cover_every_declared_term() -> None:
    classes, props, _ = _declared()
    shapes = Graph().parse(str(SHAPES), format="turtle")
    targeted = _lkg(shapes.objects(None, SH.targetClass))
    assert (classes - ABSTRACT) <= targeted, f"classes without a shape: {(classes - ABSTRACT) - targeted}"
    assert not (targeted & ABSTRACT), "shapes must not target grouping classes (inference=none)"
    assert not (targeted - classes), f"shapes target undeclared classes: {targeted - classes}"
    constrained = _lkg(shapes.objects(None, SH.path))
    assert props <= constrained, f"properties without a property shape: {props - constrained}"
    assert not (constrained - props), f"shapes constrain undeclared lkg properties: {constrained - props}"


def test_jsonld_context_matches_ontology_and_emitter() -> None:
    classes, props, _ = _declared()
    ctx = json.loads(CONTEXT.read_text(encoding="utf-8"))["@context"]
    prefixes = {k: v for k, v in ctx.items() if isinstance(v, str) and not k.startswith("@") and v.startswith("http")}

    def expand(value: str) -> URIRef | None:
        pre, _, local = value.partition(":")
        return URIRef(prefixes[pre] + local) if pre in prefixes else None

    context_terms: dict[URIRef, str] = {}
    for term, value in ctx.items():
        if term.startswith("@") or term in prefixes:
            continue
        iri = expand(value if isinstance(value, str) else value["@id"])
        if iri is not None:
            context_terms[iri] = term
    lkg_terms = _lkg(context_terms)
    assert lkg_terms <= props | classes, f"context maps undeclared lkg terms: {lkg_terms - props - classes}"
    # every predicate the emitter uses compacts to a term (RDF.type is @type)
    graph = _coverage_graph()
    used = {p for p in graph.predicates() if p != RDF.type}
    missing = {p for p in used if p not in context_terms}
    assert not missing, f"emitted predicates without a JSON-LD context term: {missing}"


def test_jsonld_context_0_7_0_terms() -> None:
    ctx = json.loads(CONTEXT.read_text(encoding="utf-8"))["@context"]
    for gone in ("altitudeM", "observationRadiusMeters", "spatialConfidence", "observationDurationMinutes",
                 "daylightPhase", "matchConfidence", "samplingProtocol", "toTaxon", "type"):
        assert gone not in ctx, gone
    assert ctx["dcType"] == {"@id": "dcterms:type", "@type": "@id"}       # "type" clashed with @type aliases
    assert ctx["hasGeometry"] == {"@id": "gsp:hasGeometry", "@type": "@id"}
    for term in ("minimumElevationInMeters", "maximumElevationInMeters"):
        assert ctx[term] == {"@id": f"dwc:{term}", "@type": "xsd:decimal"}


def test_versions_agree() -> None:
    onto = Graph().parse(str(ONTOLOGY), format="turtle")
    shapes = Graph().parse(str(SHAPES), format="turtle")
    version = str(onto.value(ONTO_IRI, OWL.versionInfo))
    assert version == "0.7.1"
    assert str(shapes.value(SHAPES_IRI, OWL.versionInfo)) == version
    vocab = Graph().parse(str(VOCABS), format="turtle")
    assert str(vocab.value(URIRef("https://w3id.org/laubmann-kg/vocabularies"), OWL.versionInfo)) == version
    assert onto.value(ONTO_IRI, OWL.versionIRI) == URIRef(f"https://w3id.org/laubmann-kg/ontology/{version}")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert version in changelog


def test_competency_queries_use_declared_terms() -> None:
    """Every lkg: term in the competency-question queries is declared (queries not stale)."""
    import re

    from laubmann_kg.kg.sparql import QUERIES

    declared = {str(s) for g in (Graph().parse(str(ONTOLOGY), format="turtle"),
                                 Graph().parse(str(VOCABS), format="turtle"))
                for s in g.subjects() if str(s).startswith(LKG_NS)}
    for key, query in QUERIES.items():
        used = {LKG_NS + m for m in re.findall(r"lkg:([A-Za-z0-9_]+)", query)}
        assert used <= declared, f"{key}: undeclared {sorted(used - declared)}"


def test_ontology_authors_contact_funding_licence() -> None:
    """Submission metadata (BiodivPortal): authors with ORCID, contacts, funder, licence."""
    from rdflib.namespace import DCTERMS, FOAF

    SCHEMA = Namespace("https://schema.org/")
    DCAT = Namespace("http://www.w3.org/ns/dcat#")
    onto = Graph().parse(str(ONTOLOGY), format="turtle")
    creators = {str(onto.value(c, FOAF.name)): str(onto.value(c, SCHEMA.identifier))
                for c in onto.objects(ONTO_IRI, DCTERMS.creator)}
    assert creators == {"Tobias Perschl": "https://orcid.org/0009-0008-7070-8705",
                        "Alois Wieshuber": "https://orcid.org/0009-0001-7010-7968"}
    assert len(list(onto.objects(ONTO_IRI, DCAT.contactPoint))) == 2
    assert [str(onto.value(f, FOAF.name)) for f in onto.objects(ONTO_IRI, FOAF.fundedBy)] == ["NFDI4Biodiversity"]
    assert onto.value(ONTO_IRI, DCTERMS.license) == URIRef("https://creativecommons.org/licenses/by/4.0/")
    text = " ".join(str(o) for o in onto.objects(ONTO_IRI, DCTERMS.description))
    assert "Alfred Louis Laubmann" in text and "Adolf" not in text
