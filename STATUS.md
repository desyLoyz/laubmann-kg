# STATUS

First end-to-end knowledge-graph build on a fixed sample. Numbers below are
**real**, from the Vol. 2 run — not projected. The full 34-volume build is
deferred until the deduplicated corpus is available (switching is a config path
change; see `INTERFACES.md`).

## Sample run (Vol. 2, offline rule-based extraction)

Command:

```bash
laubmann-kg export-all --config configs/sample.yaml --input-dir data/corpus --output-dir data/exports
# (= export-jsonld + export-dwca from one pipeline run)
```

| Metric | Value |
|---|---|
| Diary entries (all dated) | 233 |
| Entries yielding ≥1 observation | 211 (90.6%) |
| Observations | 1158 |
| Distinct taxa | 78 (all resolved to a scientific name via seed gazetteer) |
| Observations with a place | 1156 (99.8%) |
| Observations with an integer count | 474 |
| Observations with a count qualifier | 596 |
| Bird-call (auditory) evidence records | 309 |
| Nest evidence / breeding behaviour | 139 |
| Specimen evidence | 1 |
| Multimodal regions joined (DwC-A multimedia) | 15 |
| RDF triples | 16,965 |
| **SHACL** | **0 violations**, 22 warnings |
| DwC-A | event=233, occurrence=1158, measurementOrFact=2071, multimedia=15 — **valid** |

The 22 SHACL warnings are the 22 entries with no matched bird name (weather- or
travel-only text, or a species outside the seed gazetteer) — a recall limit of
the deterministic extractor, not a data error. All are `sh:Warning`, so the
graph conforms.

## Competency questions

| ID | Answerable? | Note |
|---|---|---|
| CQ1 species frequency | yes | |
| CQ2 observations by date | yes | 207 distinct dates in sample |
| CQ3 species at a place | yes | by locality label; coords partial |
| CQ4 auditory observations | yes | 309 bird-call records |
| CQ5 unresolved taxa | yes | returns 0 in sample (gazetteer covers all matches) |
| CQ6 provenance | yes | entry date + page per observation |
| Travel / route questions | blocked | travel extraction is future work |
| Cross-dataset taxon IRIs | blocked | needs `links_long` (see INTERFACES.md) |

## Ontology coverage (0.4.0)

Since 0.4.0 the ontology declares **only what the emitter produces**:
`tests/test_ontology_alignment.py` fails if a declared `lkg:` class/property is
never emitted, if the emitter uses an undeclared term, if a term has no SHACL
shape, or if the JSON-LD context misses an emitted predicate. Hence there is no
"not yet" row any more — every term below is populated by the full run;
`partial` marks conditional population.

### Classes (15 concrete + 3 grouping)

| Class | Group | Status |
|---|---|---|
| `lkg:DiaryVolume`, `lkg:DiaryPage`, `lkg:DiaryEntry`, `lkg:SourceRegion` | `lkg:ArchivalUnit` (⊑ rico:Record; not asserted in data) | populated; `dcterms:isPartOf` chain region → page → volume, entry → page |
| `lkg:Observation` (⊑ dwc:Occurrence), `lkg:TravelEvent`, `lkg:WeatherReport` | `lkg:EntryRecord` (⊑ prov:Entity; not asserted) | populated; `dcterms:isPartOf` + `prov:wasDerivedFrom` entry, `prov:wasGeneratedBy` run |
| `lkg:Vocalisation`, `lkg:TravelLeg` | `lkg:RecordDetail` (not asserted) | populated (vocalisation for auditory evidence with call detail) |
| `lkg:Taxon`, `lkg:Place`, `lkg:Person` | shared referents | populated (coords partial; persons via mention edges + `dwciri:recordedBy`) |
| habitat nodes | `skos:Concept` in `lkg:habitatScheme` (no class) | populated, shared across observations |

Removed in 0.4.0: `ObservationEvent` (→ Observation), `BirdCall` (→ Vocalisation),
`ObservationEvidence` (→ `lkg:evidenceKind` concepts), `BehaviourNote` (→
`dwc:behavior` literals), `Habitat` (→ skos:Concept), `Route`, `TimeEstimate`.

### Properties (47 `lkg:` + standard terms)

| Group | Terms | Status |
|---|---|---|
| Partonomy | `containsObservation`, `containsTravelEvent`, `hasWeather`, `hasLeg`, `hasVocalisation` (all ⊑ `dcterms:hasPart`), `hasSourceRegion`; `dcterms:isPartOf` on every child | populated |
| Entry | `entryPlace`, `entryKind`, `datePlausible`; `dwc:eventDate`, `dwc:verbatimEventDate`, `dwc:fieldNotes`, `skos:note`, `dcterms:identifier` | populated |
| Mentions | `mentionsPerson` ⊑ schema:mentions + `mentionsCompanion/Source/Collector/CitedAuthor/Other` | populated (role edge only when the model gave a role) |
| Observation | `observedTaxon`, `observedAt`, `hasLocality`, `recordType`, `evidenceKind`, `countQualifier`, `individualCountMin/Max`, `breedingEvidence`, `movementKind`, `flightDirection`, `verbatimNotes`; `dwc:occurrenceStatus/individualCount/sex/lifeStage/vitality/reproductiveCondition/behavior/habitat/identificationQualifier/eventDate/eventTime/verbatimLocality/occurrenceRemarks/basisOfRecord/associatedReferences`, `dwciri:habitat`, `dwciri:recordedBy` | populated (each only when stated) |
| Vocalisation | `callType`, `callTranscription` | populated (transcription only when written) |
| Travel | `departurePlace`, `arrivalPlace`, `viaPlace`, `departureTime`, `arrivalTime`, `transportMode` | populated |
| Weather | `weatherVerbatim`, `temperatureValue`, `temperatureUnit`, `precipitation`, `wind`, `skyCondition` | populated (one report per entry today; several allowed) |
| Place | `placeKind`; `dwc:verbatimLocality`, `geo:lat/long`, `dwc:decimalLatitude/Longitude`, `dwc:geodeticDatum`, `gsp:asWKT` | partial (coordinates only for gazetteer/georeferenced places) |
| Taxon | `isBird`, `matchMethod`, `matchConfidence`, `gbifMatchType`; `dwc:vernacularName`, `dwc:scientificName`, `dwc:taxonRank`, `dwc:taxonID`, `dwc:kingdom…genus`, `skos:exactMatch/closeMatch/broadMatch`, `owl:sameAs` | populated (classification only for GBIF-linked taxa) |
| PROV | `backend`; `prov:startedAtTime`, `prov:wasAssociatedWith`, `prov:used` | populated |

## Dedup toolchain (integrated 2026-08-10)

The corpus/dedup add-ons now live in `HistOrniGraph_addons/` in this repo
(corpus builder + duplicate detector + review GUI + non-destructive apply;
13 unit tests, all passing). `apply_dedup.py` regenerates `entries.csv` with
the same segmentation and `entry_uid`/`page_uid`/`region_uid` derivation as
the builder, so the deduped corpus drops straight into the KG stage
(`--input-dir corpus_*_dedup`). Verified locally end-to-end on a synthetic
corpus: build → detect → decisions → apply → `export-jsonld` (SHACL: 0/0).

Remaining human step: adjudicate `review.html` for the full corpus and export
`dedup_decisions.json` (see `notebooks/07_full_workflow_colab.ipynb`, stage B).

## Current state (2026-09-16)

- **Cache-only replay** (`configs/full_replay.yaml`, `extraction.cache_only`, frozen prompt `prompts/replay/observation_extraction.md`): local `export-all` against `data/corpus/dedup` + `data/cache/llm` with `linking.offline: true`, no Gemini. Writes `output/html/graph.json` (9,523 entries, 74,567 observations, 0 Ziel-1 / ontology-0.5.0 fields; SHACL 0 violations). Live 0.5.0 extraction is unchanged if you keep `--config configs/full_llm.yaml` (or `sample_range.yaml`).
- **Caveat — do not mix `data/cache/llm`.** That directory is the frozen August 0.4.x Gemini cache (key = `sha256(model, rendered prompt)`). A live 0.5.0 run with unset `extraction.cache_dir` defaults to the same folder: the new prompt misses every key and Gemini is called, but new JSON is written next to the August files and the snapshot is no longer a clean 0.4.x replay source. Point a 0.5.0 full run at a **new** `cache_dir` (same split as `llm_cache/` vs `llm_cache_v2/`). Sample-range already isolates to `data/cache/llm_sample`.

## Previous state (2026-08-19)

- **Volume coverage + date repair** (`configs/volume_coverage.yaml` from the
  34 title pages, `normalization/coverage.py`, config `qa.coverage`): misfiled
  scans re-homed (14 Vol-1 pages in the Vol-15 set), isolated OCR years repaired
  from the page neighbours (209 entries, e.g. 1901 → 1951), off-span
  off-span entries inside the diary period kept and flagged (158 entries), entries outside it dated by position (10), non-entries outside
  the diaries excluded (the 1875 obituary; plus 2 duplicates of re-homed pages). `tools/build_volume_coverage.py` re-derives
  the table from `corpus.json` and checks it against the entry dates.
- **Entity resolution** (`resolution/`, config `resolution`, after linking):
  taxa 1,064 spellings → 1,182 taxa (same accepted GBIF species key: EXACT/FUZZY, never HIGHERRANK, or same scientific name; written name kept as `dwc:verbatimIdentification` on 6,350 observations); persons 880 name variants → 4,259 persons (840 rule-based rows, 367 cluster-level candidates of which 40 accepted, 12 reviewer-added OCR variants of Walter Wüst); places 689 spellings → 9,669 places (103 orthographic + 586 accepted of 1,048 similar-spelling candidates); habitats 197 labels → 1,480 concepts (9 orthographic + 188 accepted of 292 candidates). Every merge is a `skos:altLabel` on the surviving node; observation/entry IRIs do not change. Decisions for the ambiguous candidates (adjudicated 2026-08-19)
  live in `data/review/*_merges.csv` and are applied via `reviewed_csv`.
- Ontology **0.4.1**: `skos:altLabel` for merged spellings,
  `dwc:verbatimIdentification` on merged observations; **0.4.2**: `dcterms:temporal`
  (title-page span) on every `lkg:DiaryVolume`; **0.4.3**: EUNIS matches on habitat concepts, GeoNames/Wikidata
  `owl:sameAs` + `dwc:coordinateUncertaintyInMeters` on places; no new `lkg:` terms.
- **Coverage v2** (after review of the first 2026-08-19 export): the year repair applies to
  every entry kind; entries outside the diary period (1917-04 … 1965-12, the union of the
  volume spans) that cannot be repaired are dated by their position in the volume
  (`date_from_position`; a pre-diary written date passes to the observations as their own
  eventDate); re-homed entries carry a `skos:note` naming the scan set. No entry is dated
  before April 1917 or after December 1965 any more.
- **External linking of habitats and places (ontology 0.4.3)**: `linking/habitats.py`
  maps every resolved habitat label to a EUNIS class via the LLM (cached, batched,
  `skos:exactMatch/closeMatch/broadMatch` to the Eionet EUNIS vocabulary, class nodes
  with notation/label/broader chain, eMoF row in the DwC-A, `review/habitat_link_review.csv`);
  `linking/places.py` georeferences places from a pre-warmed Nominatim cache
  (`tools/prewarm_nominatim.py`), the GeoNames country dumps and Wikidata — coordinates,
  `owl:sameAs` GeoNames feature + Wikidata item, `dwc:coordinateUncertaintyInMeters`,
  `dwc:georeferenceSources`, DwC-A `locationID`; `review/place_link_review.csv`. Result of the 2026-08-19 export: 2,872 of 9,669 places georeferenced (was 215), 2,067 with a GeoNames feature and 2,070 with a Wikidata item — 2694 of 8063 geocodable labels linked (OSM+GeoNames 1935, OSM 610, GeoNames 149), 1015 labels for review, 4354 without a gazetteer entry; 1,375 of 1,481 habitat concepts linked to a EUNIS class (10730 observations; exact 323, close 701, broad 351; 74 review, 32 no match).
- **Current export: Drive `kg_exports_2026-08-19/`** — 9,523 entries (4 excluded by QA + coverage), 74,584 observations, 15,297 vocalisations, 1,735,142 triples, SHACL 0 violations / 409 warnings (empty entries), 1,182 taxa (616 on GBIF), 4,259 persons (300 on Wikidata), 9,669 places (2,872 georeferenced, 2,067 on GeoNames, 2,070 on Wikidata), 1,481 habitat concepts (1,375 linked to EUNIS classes); DwC-A valid (event 9,523 · occurrence 74,584 · eMoF 113,109 (incl. the EUNIS habitat rows) · multimedia 141); `review/` = qa_flags (2,281 rows) + link reviews (taxon, person, place 8,063 labels, habitat 1,481 labels) + the four merge CSVs (3,723 rows); `html/` explorer v7 + workflow page; local run = notebook 07 C1+C3 (`export-all`) against the Drive caches (2 live Gemini calls for the truncated digest entries; EUNIS classification and GBIF/Wikidata/Nominatim from the Drive caches)

## Previous state (2026-08-18)

- **Ontology 0.4.0** (see CHANGELOG 2026-08-18): Darwin-Core-first (no lkg
  twins of standard terms), three grouping superclasses + explicit
  `dcterms:isPartOf` partonomy, `ObservationEvent → lkg:Observation`,
  `BirdCall → lkg:Vocalisation`, evidence/behaviour flattened, habitats as shared
  skos:Concepts, person roles on the mention edge, GBIF higher taxonomy, WKT.
  **Current export: Drive `kg_exports_2026-08-18/`** (0.4.0; C3+C4 run
  locally 2026-08-18 against the Drive caches — 37 live Gemini calls for the
  previously truncated entries and new folk names): 9,526 entries (0 failed),
  74,600 observations, 15,298 vocalisations, 1,675 habitat concepts,
  1,722,388 triples (0.3.0 export: 1,845,457), SHACL 0 violations / 409
  warnings (empty entries), taxa 2,247 (1,678 GBIF-linked), persons 5,115 (344
  Wikidata), DwC-A valid (event 9,526 · occurrence 74,600 · eMoF 102,406 ·
  multimedia 141 from the cleaned catalogue); RDF and DwC-A now consistent.
  `html/` in the export folder holds the rebuilt explorer + workflow pages.
  The 0.3.0 export `kg_exports_2026-08-17` can be deleted. Two-way alignment
  guard: `tests/test_ontology_alignment.py`.
- Extraction is **model-driven, heuristics removed** (see CHANGELOG 2026-08-17):
  the LLM reads entry date/place/kind and every observation detail (locality,
  rank, absence, counts/ranges, sex, life stage, breeding evidence, vitality,
  movement, hedges, own date/time, provenance); code checks form only. QA is
  threshold-based on model signals. PROV run node, OBIS eMoF in the DwC-A.
  Structure diagrams: `docs/kg_structure.mmd`, `docs/pipeline.mmd`.
- Full 34-volume rerun: run `notebooks/07_full_workflow_colab.ipynb` (v2:
  Drive-resident caches for LLM + linking + review CSVs, smoke-test cell,
  fresh `kg_exports_<tag>` per run). The prompt changed, so the run is fully
  live (~2–3 h extraction + linking); the old `llm_cache/` is dead.
- Offline replay of the 9,527 cached 2026-08-12 responses through the new
  mapper → RDF → SHACL → DwC-A: 0 mapper errors, 68,990 observations, ~1.95 M
  triples, SHACL conformant.

## Deferred / not done

- Person/taxon variant merging inside the pipeline (today post hoc via
  `HistOrniGraph_addons/kg_enrich/dedup_entities.py`); Nominatim georeferencing
  as a `linking/places.py` stage (today post hoc `georef_places.py`).
- w3id: namespace migrated in the repo (2026-08-18); the perma-id PR is pending until the ontology is final (`w3id/laubmann-kg/`). Existing exports: `tools/migrate_namespace.py`. Ontology docs: `docs/ontology/` (pyLODE).
- Gemini structured output (`response_json_schema`) — would retire json-repair;
  needs a live A/B on ~50 entries.
- Travel legs in the DwC-A (`parentEventID` sub-events); linking observations
  to the travel leg they occurred during (dropped from the ontology in 0.4.0
  until the extraction can supply it); several weather reports per entry
  (allowed by ontology/SHACL, needs the next prompt change).
- Avibase alignment (needs `links_long`).
- `preprocess` / `detect-layout` / `transcribe` stages remain stubs (handled
  upstream by HistOrniGraph, per the task brief).
- LLM extraction backend: **wired**. A Gemini provider adapter and an
  LLM extractor are connected via `extraction.backend: llm`
  (`configs/sample_llm.yaml`); calls are cached and run at temperature 0. The
  wiring/mapping is tested offline with a fake client; live runs need an API key
  (`pip install -e ".[llm]"`, set `GOOGLE_API_KEY`). OpenAI/Anthropic adapters
  are not yet added. No formal LLM-vs-gold evaluation harness yet
  (`evaluation/` modules remain stubs) — quality is currently judged by review.
- Live Gemini run on Vol. 2 (Colab, 2026-08): 233 entries → 1,573 observations,
  28,298 triples. The 6 `callTranscription` SHACL violations seen in that run
  came from an export made before da5739f (evidence URIs without the index
  suffix); since da5739f evidence URIs are unique, and since 2026-08-17
  `callTranscription` is optional (no placeholder), so re-exports validate clean.
