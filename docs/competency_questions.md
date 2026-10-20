# Competency Questions

The knowledge graph is designed to answer the questions below. Each maps to a
SPARQL query in `src/laubmann_kg/kg/sparql.py` (`QUERIES[...]`), runnable over the
exported graph (ontology 0.7.1 vocabulary: `dwc:vernacularName`,
`dwc:eventDate`, `dcterms:isPartOf`, `lkg:evidenceKind` as a literal, …). All eleven
queries were run against the full export `output/jsonld/laubmann_kg.jsonld`
(ontology 0.7.1, 1,990,526 triples) on 2026-10-20: each returns rows, see
"Testing the questions" below.

| ID | Question | Query key | Status |
|---|---|---|---|
| CQ1 | Which species were observed, and how often? | `CQ1_species_frequency` | answerable |
| CQ2 | How many observations fall on each date? | `CQ2_observations_by_date` | answerable |
| CQ3 | Which species were seen at a given place? | `CQ3_observations_at_place` | answerable |
| CQ4 | Which observations are auditory, and what call type / transcription was noted? | `CQ4_auditory_observations` | answerable |
| CQ5 | Which taxa remain unresolved to a scientific name? | `CQ5_unresolved_taxa` | answerable |
| CQ6 | What is the source (entry date, page, volume, extraction run) of each observation? | `CQ6_provenance` | answerable |
| CQ7 | Which records state their own locality, which inherit the entry place? | `CQ7_own_locality_vs_entry_place` | answerable |
| CQ8 | Which records are explicit absences ("keine Störche mehr")? | `CQ8_absence_records` | answerable |
| CQ9 | How many records per family (GBIF classification)? | `CQ9_observations_by_family` | answerable for linked taxa |
| CQ10 | Which taxa were noted in which habitat? | `CQ10_taxa_by_habitat` | answerable |
| CQ11 | Which persons appear in which role (companion, source, collector, cited author)? | `CQ11_persons_by_role` | answerable |

## Partial

- **Place coordinates** are partial: only gazetteer-seeded (and post-hoc
  georeferenced) localities carry `geo:lat`/`geo:long`/`gsp:asWKT`. CQ3 answers
  by locality label regardless.
- **Higher taxonomy** (CQ9) is only present for taxa linked to the GBIF backbone
  (EXACT/FUZZY/HIGHERRANK matches, or reviewed names whose match is cached).
- **Travel questions** ("which route on day X?") are answerable from
  `lkg:TravelEvent`/`lkg:TravelLeg` when the model extracted legs; no dedicated
  CQ is shipped yet.

## Running the queries

```python
from laubmann_kg.kg.sparql import load_graph, run_query
graph = load_graph("data/exports/rdf/laubmann_sample.ttl")
for row in run_query(graph, "CQ1_species_frequency"):
    print(row)
```

## Testing the questions against an ontology version

1. **Check the queries against the ontology** (no data needed; fast). Every
   `lkg:` term used in a query must be declared in `ontologies/laubmann.ttl` or
   `ontologies/controlled_vocabularies.ttl`:

   ```bash
   .venv/bin/python tools/run_competency_questions.py --check-terms
   .venv/bin/python -m pytest tests/test_ontology_alignment.py tests/test_rdf_emission.py -q
   ```

   `test_competency_queries_use_declared_terms` fails when a query uses a renamed
   or removed term; `test_rdf_emission.py` runs all queries on a small fixture
   graph and asserts concrete answers.

2. **Run the queries on a full export** built with that ontology version:

   ```bash
   .venv/bin/python tools/run_competency_questions.py output/jsonld/laubmann_kg.jsonld
   .venv/bin/python tools/run_competency_questions.py graph.ttl --only CQ1 CQ4 --limit 10
   ```

   Output per question: `OK` (rows), `EMPTY` (0 rows: the pattern is missing in the
   data or the query is out of date with the ontology), `ERROR`. Loading the
   131 MB JSON-LD takes about 35 s, all eleven queries about 1 min together.

3. **Interpret EMPTY / unexpected results:** compare the predicates in the query
   with the ontology changelog in the header of `ontologies/laubmann.ttl` (e.g.
   0.6.0: `lkg:evidenceKind`, `lkg:callType` are literals, `lkg:Vocalisation` is
   gone; 0.7.0: `observationRadiusMeters`, `spatialConfidence` removed). Adapt the
   query in `src/laubmann_kg/kg/sparql.py`, then update this document and the
   ontology version note.

4. **Single query in Python / on another triple store:**

   ```python
   from laubmann_kg.kg.sparql import QUERIES, load_graph, run_query
   g = load_graph("data/exports/.../rdf/laubmann_sample.ttl")
   print(run_query(g, "CQ4_auditory_observations")[:5])
   print(QUERIES["CQ1_species_frequency"])      # paste into Fuseki / GraphDB / Blazegraph
   ```

5. **Per release:** after a new ontology version rerun step 1 and step 2 on the
   new export and record the date and row counts here.

Result of 2026-10-20 (export of ontology 0.7.1; row counts): CQ1 613 species, CQ2 8,483
dates, CQ3 84,970 place/species pairs, CQ4 18,581 auditory records, CQ5 43 unresolved taxa,
CQ6 25 (provenance query returns a sample), CQ7 85,896 records, CQ8 1,189 absences, CQ9 80
families, CQ10 1,879 habitat/taxon groups, CQ11 4,359 person/role pairs.
