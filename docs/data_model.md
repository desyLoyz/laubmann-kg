# Data Model

The knowledge graph conforms to `ontologies/laubmann.ttl` (v0.5.0, namespace
`https://w3id.org/laubmann-kg/ontology#`, prefix `lkg:`). Instances live under
`https://w3id.org/laubmann-kg/data/` (prefix `data:`). The Python contract is
`src/laubmann_kg/kg/model.py`; `kg/rdf.py` maps it onto triples and
`ontologies/shacl_shapes.ttl` validates the result **without inference** (shapes
target the concrete classes; the grouping superclasses are not asserted in the
data). Enumerated values are defined once in `normalization/vocabularies.py` and
mirrored as SKOS concept schemes in `ontologies/controlled_vocabularies.ttl`.
`tests/test_ontology_alignment.py` enforces, in both directions, that the
emitter, the ontology, the shapes and the JSON-LD context use the same terms.

Extraction is LLM-based (`extraction/llm_observations.py`; prompt in
`prompts/observation_extraction.md`); the offline rule-based backend is a
network-free test double. Nothing is inferred from prose in the emitter: a
value appears in the graph only when the extractor set it.

Diagrams (Mermaid, render with any Mermaid tool or paste into Mermaid Chart):
`docs/kg_structure.mmd` (classes, datatype properties, predicates as emitted)
and `docs/pipeline.mmd` (stages and where each decision is made).
Human-readable ontology docs: `docs/ontology/index.html` (pyLODE).

## Design principles (0.4.0, extended in 0.5.0)

- **Darwin-Core-first.** Wherever a `dwc:`/`dwciri:`, DCTERMS, PROV-O, SKOS,
  GeoSPARQL or schema.org term exists, the graph uses that term alone;
  `lkg:` carries only project-specific meaning (record type, count qualifier and
  ranges, breeding evidence, movement, evidence kind, entry kind, weather,
  travel, mention roles). No `lkg:` twin of a standard term is emitted.
- **Three grouping superclasses** structure the hierarchy (declared, never
  asserted as `rdf:type` in the data):
  `lkg:ArchivalUnit` ⊑ rico:Record — DiaryVolume, DiaryPage, DiaryEntry, SourceRegion;
  `lkg:EntryRecord` ⊑ prov:Entity — Observation, TravelEvent, WeatherReport (what the
  model reads out of one entry); `lkg:RecordDetail` — Vocalisation, TravelLeg.
  Taxon, Place and Person are shared referents; habitats are `skos:Concept`s.
- **Explicit partonomy.** Containment properties (`lkg:containsObservation`,
  `lkg:containsTravelEvent`, `lkg:hasWeather`, `lkg:hasLeg`, `lkg:hasVocalisation`)
  are sub-properties of `dcterms:hasPart`; every child node carries
  `dcterms:isPartOf`.
- **Flat where a node adds nothing.** Behaviour = `dwc:behavior` literals;
  evidence kinds = `lkg:evidenceKind` concept links on the observation;
  only vocalisations, weather reports and travel legs stay nodes.
- **Ziel 1 (0.5.0) — time and space on the observation.** The named site stays
  a `lkg:Place` (`lkg:hasLocality` when it differs from `lkg:entryPlace`);
  vantage wording, microhabitat and relative height are literals
  (`lkg:spatialContext`, `lkg:microhabitat`, `lkg:relativeElevation`). Clock
  time is `dwc:eventTime` (`HH:MM`); the qualitative slot is `lkg:timeOfDay`
  / `lkg:daylightPhase`. An estimated viewing radius
  (`lkg:observationRadiusMeters`) is mirrored as
  `dwc:coordinateUncertaintyInMeters` on the occurrence, with
  `dwc:samplingProtocol` and `lkg:spatialConfidence`. Nothing is inferred in
  the emitter — values appear only when the extractor set them.
- **One node per real-world entity.** The entity-resolution stage
  (`resolution/`, after linking) merges spellings that denote the same taxon
  (same accepted GBIF key at species level, or same scientific name), person
  (title-stripped/folded key, Wikidata item, unique initial/surname, dominant
  usage) or place/habitat (orthographic variants; similar strings only after
  review). The canonical spelling is the most-used one; merged spellings are
  `skos:altLabel`, and an observation whose written taxon name was merged keeps
  it as `dwc:verbatimIdentification`. Observation IRIs never change (they hash
  the name as written). Every merge is a row in `review/*_merges.csv`
  (`decision` column: `auto` rows apply unless rejected, `candidate` rows only
  when accepted).
- **Habitats linked to EUNIS.** After resolution, `linking/habitats.py` asks
  the LLM (cached, batched) for the EUNIS habitat class (2012 classification,
  Eionet vocabulary `http://eunis.eea.europa.eu/eunishabitats/<code>`) of every
  distinct habitat label and how it relates to it: the habitat concept gets at
  most one `skos:exactMatch` / `skos:closeMatch` / `skos:broadMatch`; the EUNIS
  class is a `skos:Concept` with `skos:notation`, `skos:prefLabel`@en and its
  `skos:broader` chain up to the level-1 group, so "everything in woodland" is
  `skos:broader* G`. The class URIs are identifiers (the eunis.eea.europa.eu
  web application is retired); each class node carries `rdfs:seeAlso` to its
  Eionet Data Dictionary page and to the BISE hierarchical view of the 2012
  classification. Confidence ≥ 0.7 is applied, the rest waits in
  `review/habitat_link_review.csv` (`y`/`n` decisions → `reviewed_csv`). The
  DwC-A carries the class as an eMoF row (`habitat type (EUNIS 2012)`,
  `measurementValueID` = EUNIS URI); `dwc:habitat` stays verbatim.
- **Places georeferenced with an identity.** `linking/places.py` combines a
  pre-warmed Nominatim cache (OSM: name-matched hit of an acceptable type),
  the GeoNames country dumps (a record with the same name within 10 km of the
  OSM point, or unique in Bavaria) and Wikidata (QID from the OSM tag or
  GeoNames P1566): `geo:lat/long`, `gsp:asWKT`, `owl:sameAs
  https://sws.geonames.org/<id>/` and `owl:sameAs wd:Q…`,
  `dwc:coordinateUncertaintyInMeters` (centroid radius by feature type: town
  2 km, lake 1 km, peak 300 m …) and `dwc:georeferenceSources`; DwC-A
  `locationID` (GeoNames URI), `coordinateUncertaintyInMeters`,
  `georeferenceSources/Protocol` on the event. Labels that cannot be gazetteer
  entries (prepositional fragments, generic nouns, micro-localities) are never
  tried; everything else lands in `review/place_link_review.csv`
  (linked | review | no_match, decision column).
- **Dates checked against the volume span.** `configs/volume_coverage.yaml`
  (title pages; each `lkg:DiaryVolume` states its span as `dcterms:temporal
  "YYYY-MM/YYYY-MM"`) drives `normalization/coverage.py`: misfiled scans go
  back to their document's volume (a `skos:note` names the scan set they were
  digitised in; the corpus id in `dcterms:identifier` is kept), isolated OCR
  years are repaired from the sequence neighbours for every entry kind (`1901`
  → `1951`; recorded as `skos:note`, the raw date stays
  `dwc:verbatimEventDate`), an entry dated outside the diary period
  (April 1917 – December 1965) that cannot be repaired is dated by its position
  in the volume (an interval between the neighbouring in-span entries; a
  pre-diary written date whose records the model read as historic — own
  event dates, literature records, specimens — is a record date and passes to
  the entry's observations as their own `dwc:eventDate`), non-entries (`other`) outside the
  period are excluded, off-span entries inside the period are kept and flagged
  (QA reasons `volume_reassigned`, `date_year_corrected`, `date_from_position`,
  `date_out_of_coverage`, `date_out_of_span`, `duplicate_entry`). No entry is
  dated before the first or after the last title page.

## Node types and keys

| Class | IRI | Key |
|---|---|---|
| `lkg:DiaryVolume` (⊑ ArchivalUnit; `dcterms:temporal` title-page span) | `data:volume_NN` | corpus |
| `lkg:DiaryPage` (⊑ ArchivalUnit; `dcterms:isPartOf` volume) | `data:page_<page_uid>` | corpus |
| `lkg:DiaryEntry` (⊑ ArchivalUnit, dwc:Event; `dcterms:isPartOf` page or volume) | `data:entry_<entry_uid>` | corpus `entry_uid` |
| `lkg:SourceRegion` (⊑ ArchivalUnit; `dcterms:isPartOf` page) | `data:region_<region_uid>` | corpus |
| `lkg:Observation` (⊑ EntryRecord, dwc:Occurrence) | `data:obs_<sha1(entry_uid|vernacular|index)>` | derived |
| `lkg:TravelEvent` (⊑ EntryRecord, dwc:Event) / `lkg:TravelLeg` (⊑ RecordDetail) | `data:travel_<entry>_<i>` / `data:leg_…` | per entry |
| `lkg:WeatherReport` (⊑ EntryRecord) | `data:weather_<entry_uid>` | one per entry today (several allowed) |
| `lkg:Vocalisation` (⊑ RecordDetail; `dcterms:isPartOf` observation) | `data:vocalisation_<obs>_<i>` | per call |
| `lkg:Taxon` (⊑ dwc:Taxon) | `data:taxon_<sha1(vernacular lower)>` | German vernacular as written |
| `lkg:Place` (⊑ geo:SpatialThing, dcterms:Location) | `data:place_<sha1(canonical or verbatim)>` | place name |
| habitat `skos:Concept` in `lkg:habitatScheme` (**not** a class, **not** a Place) | `data:habitat_<sha1(label)>` | habitat label, shared across observations |
| `lkg:Person` (⊑ schema:Person) | `data:person_<sha1(name lower)>` | name; the diarist is `person_c6b2ff6250e5` |
| `prov:Activity` (run) / `prov:SoftwareAgent` / `prov:Entity` (prompt) | `data:run_<sha1(model|prompt_sha|started)>` / `data:agent_<model>` / `data:prompt_<sha[:12]>` | `ExtractionResult.provenance` |

## Provenance / partonomy chain

```
Observation  (dwc:Occurrence)
  ├─ dcterms:isPartOf + prov:wasDerivedFrom → DiaryEntry   (dwc:Event; lkg:containsObservation back)
  │     ├─ dcterms:isPartOf → DiaryPage ─ dcterms:isPartOf → DiaryVolume   (page unknown: entry → volume)
  │     ├─ lkg:hasSourceRegion → SourceRegion ─ dcterms:isPartOf → DiaryPage
  │     ├─ lkg:entryPlace → Place            (entry's main locality)
  │     ├─ dwc:eventDate (xsd:date | "start/end"), dwc:verbatimEventDate, dwc:fieldNotes (entry text)
  │     ├─ lkg:entryKind, lkg:datePlausible, skos:note (date note), dcterms:identifier
  │     ├─ lkg:mentionsPerson → Person  + role edge lkg:mentionsCompanion|Source|Collector|CitedAuthor|Other
  │     ├─ lkg:hasWeather → WeatherReport   (dcterms:isPartOf + prov:wasDerivedFrom the entry)
  │     └─ lkg:containsTravelEvent → TravelEvent ─ lkg:hasLeg → TravelLeg (dcterms:isPartOf the event)
  ├─ lkg:observedTaxon (⊑ dwciri:toTaxon) → Taxon
  ├─ lkg:observedAt → Place                  (EFFECTIVE place: own locality, else entry place)
  ├─ lkg:hasLocality → Place                 (only when the record states its OWN locality; + dwc:verbatimLocality)
  ├─ lkg:evidenceKind → lkg:evidence_visual|auditory|nest|specimen   (0–4 concepts)
  ├─ lkg:hasVocalisation → Vocalisation      (lkg:callType, lkg:callTranscription; dcterms:isPartOf back)
  ├─ dwc:behavior "…"@de                     (literals, no node)
  ├─ dwciri:habitat → habitat concept        (+ dwc:habitat literal)
  ├─ dwciri:recordedBy → Person              (diarist by default; never fabricated for 3rd-party records)
  └─ prov:wasGeneratedBy → run (prov:Activity ─ prov:wasAssociatedWith → SoftwareAgent, prov:used → prompt)
```

When `ExtractionResult.provenance` is empty (hand-built results) no run node
and no `wasGeneratedBy` are emitted.

## Observation detail (all optional unless noted)

| model.py field | Predicate(s) | Notes |
|---|---|---|
| `verbatim_notes` (required) | `lkg:verbatimNotes`@de | source passage |
| `occurrence_status` | `dwc:occurrenceStatus` present\|absent | |
| `individual_count` | `dwc:individualCount` (xsd:integer ≥ 0) | 0 only with `absent` |
| `count_min` / `count_max` | `lkg:individualCountMin` / `Max` | ranges ("3-4") |
| `count_qualifier` | `lkg:countQualifier` | exact\|minimum\|approximate\|plural-unspecified |
| `sex`, `life_stage`, `vitality` | `dwc:sex`, `dwc:lifeStage`, `dwc:vitality` | vocab values |
| `breeding_evidence` | `lkg:breedingEvidence` (+ `dwc:reproductiveCondition "breeding"` for confirmed/probable, via `vocabularies.reproductive_condition`) | atlas categories |
| `movement_kind`, `flight_direction` | `lkg:movementKind`, `lkg:flightDirection`@de | direction as written |
| `identification_qualifier` | `dwc:identificationQualifier` | the diarist's hedge as written |
| `event_date`, `event_time` | `dwc:eventDate` (xsd:date; falls back to the entry date), `dwc:eventTime` "HH:MM" | |
| `record_type`, `observer`, `literature_citation` | `lkg:recordType`, derived `dwc:basisOfRecord`, `dwciri:recordedBy`, `dwc:associatedReferences` | see ontology comment on recordType |
| `evidence[]` | `lkg:evidenceKind` concept per kind; calls additionally a `lkg:Vocalisation` node (`lkg:callType` always, `lkg:callTranscription` only when written) | no placeholder |
| `taxon_verbatim` | `dwc:verbatimIdentification` | the name as written, when resolution merged it into a canonical taxon |
| `behaviour[]` | `dwc:behavior`@de literals | |
| `habitat` | `dwciri:habitat` → shared concept + `dwc:habitat` literal | |
| `flags` | not emitted (QA only) | |

Taxon: `rdfs:label` + `dwc:vernacularName`@de (+ `skos:altLabel` for merged spellings), `dwc:scientificName` or
`skos:note` (unresolved), `dwc:taxonRank`, `lkg:isBird`, GBIF classification
`dwc:kingdom/phylum/class/order/family/genus` (from the cached `species/match`
response, `Taxon.higher_taxonomy`), match provenance (`lkg:matchMethod`,
`lkg:matchConfidence`, `lkg:gbifMatchType`) and the GBIF link as
`skos:exactMatch` / `closeMatch` (fuzzy or LLM-mediated) / `broadMatch`
(HIGHERRANK) plus `dwc:taxonID` (not for broad matches).

Place: `rdfs:label`@de (canonical; merged spellings as `skos:altLabel`), `dwc:verbatimLocality`, `lkg:placeKind`,
`geo:lat`/`geo:long` co-emitted as `dwc:decimalLatitude`/`Longitude` +
`dwc:geodeticDatum "WGS84"` + `gsp:asWKT "POINT(lon lat)"^^gsp:wktLiteral`.

Person: `rdfs:label`, `schema:name`, `skos:altLabel` (merged name variants),
`owl:sameAs` (Wikidata). The role is on the mention edge of each entry, not on
the shared node.

## Corpus → ontology mapping

| Corpus field (entries.csv) | KG target |
|---|---|
| `entry_uid`, `entry_id` | `data:entry_<uid>`, `dcterms:identifier` |
| `date_norm` / `date_raw` | `dwc:eventDate` (`xsd:date`, model-corrected; multi-day → `"start/end"`), `dwc:verbatimEventDate` |
| `volume`, `page_uid`, `page_id`, `scan`, `region_uid` | `dcterms:isPartOf` page → volume (+ `dcterms:identifier` on the page), `lkg:hasSourceRegion` |
| `location_raw` | fallback for `lkg:entryPlace` (LLM backend replaces it with the model's reading) |
| `text_clean` | `dwc:fieldNotes`; extraction input |

Linked images join by `entry_uid`: a `multimodal` region with
`entry_uid == observation's entry` becomes a DwC-A multimedia record for that
entry's event.

## Ontology → Darwin Core Archive mapping

Event-core sampling-event archive (`configs/dwca.yaml`), joined by `eventID`:

| DwC-A file | rowType | Source |
|---|---|---|
| `event.txt` (core) | Event | one row per dated `DiaryEntry`; `eventID = entry_uid`; locality/coordinates from the model-read entry place, `verbatimLocality` = header, weather in `eventRemarks`/`dynamicProperties` |
| `occurrence.txt` | Occurrence | one row per `Observation`; `occurrenceID = obs uid`; kingdom/class/order/family (GBIF classification, is_bird fallback), taxonRank/taxonID, `individualCount` (0 for absences), `organismQuantity(+Type)` for ranges, `occurrenceStatus`, sex/lifeStage/reproductiveCondition/vitality/behavior, identificationQualifier, own locality + eventDate/eventTime, habitat, provenance-aware `recordedBy` |
| `measurementorfact.txt` | ExtendedMeasurementOrFact (OBIS eMoF, keyed on `occurrenceID`) | evidence kind, call type, count qualifier, breeding evidence, movement kind per observation; `measurementTypeID`/`measurementValueID` point at the SKOS schemes/concepts; `measurementMethod` from run provenance |
| `multimedia.txt` | Multimedia (GBIF Simple Multimedia) | one row per `multimodal` region joined on `entry_uid` |

## Competency queries

`kg/sparql.py` ships CQ1–CQ11 (species frequency, by date, by place, auditory
incl. vocalisation detail, unresolved taxa, provenance chain incl. page/volume/run,
own locality vs. entry place, absence records, observations by family, taxa by
habitat, persons by role).
