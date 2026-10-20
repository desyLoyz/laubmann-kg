# Laubmann KG Ontology – Einreichung bei BiodivPortal (NFDI4Biodiversity)

Entwurf zur internen Prüfung. Noch **nicht eingereicht**; Platzhalter (`TODO`) sind
bewusst stehen geblieben.

- Portal: <https://biodivportal.gfbio.org/> (OntoPortal-Instanz; REST-API <https://data.biodivportal.gfbio.org/>)
- Registry-Eintrag: <https://kghub.org/kg-registry/resource/biodivportal/biodivportal.html>
- Metadatenschema: MOD 2.0 / OntoPortal – <https://ontoportal.github.io/documentation/user_guide/metadata_schema/EcoPortal>
- Quelle des Stands: Repository `laubmann-kg-che`, Branch `main`, Commit `c8d4954` (Ontologie 0.7.1, 2026-10-06)

## 1. Dateien

| Datei | Zweck | Wohin im Portal |
|---|---|---|
| `ontologies/laubmann.ttl` | Projektontologie (OWL, Turtle), Version 0.7.1 | **Hauptdatei** der Einreichung (Upload oder „Load from URL“) |
| `ontologies/controlled_vocabularies.ttl` | SKOS-Konzeptschemata der kontrollierten Werte und der Authority-Schemata | zweites Artefakt (Sprache SKOS), optional; die Ontologie verweist per `rdfs:seeAlso` darauf |
| `ontologies/shacl_shapes.ttl` | SHACL-Validierungsshapes | nicht ins Portal (kein OWL/SKOS); nur als Referenz / Review-Anlage |
| `docs/competency_questions.md` | Kompetenzfragen CQ1–CQ11 mit Anleitung zum Testen | Inhalt geht in das Feld *competencyQuestion* (Abschnitt 3) |
| `LICENSE` | CC-BY-4.0 (Volltext) | Feld *hasLicense*; Review-Anlage |
| `docs/ontology/index.html` | pyLODE-Dokumentation der Ontologie (am 2026-10-20 mit den neuen Metadaten neu erzeugt) | Feld *documentation* (sobald unter einer festen URL erreichbar) |
| `docs/biodivportal/submission_metadata.md` | dieses Dokument | nur Review |

Nicht einzureichen: `ontologies/*.code.turtle` (veraltete, nicht versionierte Kopien), Daten- und Exportdateien (`output/`, `data/`).

## 2. Metadaten (OntoPortal-Felder)

Pflichtfelder laut API von BiodivPortal: `acronym`, `name`, `administeredBy`, `status`,
`hasOntologyLanguage`, `description`, `released`, `contact`, `URI`.

### Pflichtfelder

| Feld | Wert | Quelle / Anmerkung |
|---|---|---|
| acronym | `LAUBMANN-KG` (Vorschlag; Alternative `LKG`) | im Portal später nicht änderbar; Eindeutigkeit prüfen |
| name | Laubmann Knowledge Graph Ontology | `dcterms:title@en` |
| administeredBy | TODO – registrierter BiodivPortal-Account (Alois Wieshuber und/oder Tobias Perschl) | Account muss vorher angelegt sein |
| hasOntologyLanguage | OWL | Serialisierung Turtle |
| URI | `https://w3id.org/laubmann-kg/ontology` | **w3id-Eintrag ist noch nicht beantragt** (`w3id/laubmann-kg/`, PR ausstehend), IRI ist daher noch nicht auflösbar |
| version | `0.7.1` | `owl:versionInfo` (aktueller Stand im Repo; nicht 0.5 – 0.5.0 war der Stand vom 2026-09-15) |
| status | `beta` (Vorschlag; Werte: alpha / beta / production / retired) | Ontologie ist funktionsvollständig, wird aber noch weiterentwickelt |
| released | 2026-10-06 (TODO: Datum der tatsächlichen Einreichung) | Datum von 0.7.1 |
| description | siehe Abschnitt 4 | `dcterms:description`; das Portal empfiehlt einen Satz, den langen Text als *abstract* |
| contact | Tobias Perschl, Tobias.Perschl@uni-passau.de; Alois Wieshuber, alois.wieshuber@gda.bayern.de | beide als Ansprechpartner; im Portal Name + E-Mail je Kontakt |
| viewingRestriction | public | |

### Empfohlene Felder

| Feld | Wert |
|---|---|
| hasLicense | `https://creativecommons.org/licenses/by/4.0/` (CC-BY-4.0) |
| hasCreator | Tobias Perschl (ORCID [0009-0008-7070-8705](https://orcid.org/0009-0008-7070-8705)); Alois Wieshuber (ORCID [0009-0001-7010-7968](https://orcid.org/0009-0001-7010-7968)); Personen, keine Organisationen |
| fundedBy | NFDI4Biodiversity (<https://www.nfdi4biodiversity.org/>); das Projekt HistOrniGraph wurde von der NFDI4Biodiversity gefördert |
| publisher | HistOrniGraph / Laubmann KG Project (TODO: ggf. Universität Passau / Generaldirektion der Staatlichen Archive Bayerns) |
| rights holder | TODO klären (Universität Passau und/oder GDA Bayern) |
| homepage | <https://github.com/Maelkolb/laubmann-kg_TP> |
| repository | <https://github.com/Maelkolb/laubmann-kg_TP> |
| documentation | TODO: feste URL der pyLODE-Seite (`docs/ontology/index.html`, nach Freischaltung von GitHub Pages bzw. w3id) |
| publication | TODO: keine Publikation vorhanden |
| bugDatabase | <https://github.com/Maelkolb/laubmann-kg_TP/issues> |
| naturalLanguage | en, de |
| versionIRI | `https://w3id.org/laubmann-kg/ontology/0.7.1` |
| prior version | `https://w3id.org/laubmann-kg/ontology/0.7.0` |
| preferred namespace | prefix `lkg`, URI `https://w3id.org/laubmann-kg/ontology#` |
| creationDate / issued | 2026-07-22 |
| modificationDate | 2026-10-06 |
| designedForOntologyTask | Strukturierung und Veröffentlichung von Beobachtungsdaten aus handschriftlichen ornithologischen Feldtagebüchern (Darwin-Core-Export) |
| coverage | Bayern, 1917–1965 |
| Kategorie (hasDomain) | im Portalformular zu wählen, z. B. Biodiversität / Ökologie (TODO) |
| Gruppe | TODO: NFDI4Biodiversity-Gruppe, falls im Portal vorhanden |
| keywords | ornithology; field diaries; biodiversity data; Darwin Core; historical bird observations; Bavaria; knowledge graph; Alfred Louis Laubmann (<https://d-nb.info/gnd/1012394506>) |
| Wiederverwendete Vokabulare | Darwin Core (dwc, dwciri), DCTERMS, SKOS, PROV-O, GeoSPARQL, schema.org, RiC-O, FOAF, W3C Basic Geo |
| Verknüpfte Autoritäten | GBIF, EUNIS, GeoNames, Wikidata, GND |

Hinweis zu den Schlüsselwörtern: Die OntoPortal-Dokumentation verlangt Schlüsselwörter möglichst
aus kontrollierten Vokabularen mit URI. Prüfbare Kandidaten: Ornithologie = Wikidata
[Q44703](https://www.wikidata.org/wiki/Q44703), Darwin Core = [Q5225953](https://www.wikidata.org/wiki/Q5225953),
Biodiversitätsinformatik = [Q864269](https://www.wikidata.org/wiki/Q864269), Bayern = [Q980](https://www.wikidata.org/wiki/Q980),
Alfred Louis Laubmann = GND 1012394506. Das Schlüsselwort „Adolf“ kommt nicht mehr vor.

### Abgleich mit dem Repo (Stand dieser Änderung)

In `ontologies/laubmann.ttl` ergänzt oder korrigiert:

- `dcterms:creator` und `dcat:contactPoint`: Tobias Perschl und Alois Wieshuber (E-Mail, Affiliation); der Platzhalter „Laubmann KG Project“ als Autor entfällt.
- `foaf:fundedBy`: NFDI4Biodiversity; Förderhinweis im `dcterms:description`.
- `dcterms:description` und `rdfs:comment`: Ornithologe **Alfred Louis Laubmann** (GND <https://d-nb.info/gnd/1012394506>).
- `dcterms:subject`: GND-IRI Laubmanns ergänzt; `dcterms:modified` auf 2026-10-06.
- Lizenz bereits `dcterms:license <https://creativecommons.org/licenses/by/4.0/>` (CC-BY-4.0).

## 3. Kompetenzfragen (Feld *competencyQuestion*)

Übernommen aus `docs/competency_questions.md`; jede Frage hat eine SPARQL-Abfrage in
`src/laubmann_kg/kg/sparql.py` (`QUERIES[...]`).

1. Which species were observed, and how often?
2. How many observations fall on each date?
3. Which species were seen at a given place?
4. Which observations are auditory, and what call type / transcription was noted?
5. Which taxa remain unresolved to a scientific name?
6. What is the source (entry date, page, volume, extraction run) of each observation?
7. Which records state their own locality, which inherit the entry place?
8. Which records are explicit absences ("keine Störche mehr")?
9. How many records per family (GBIF classification)?
10. Which taxa were noted in which habitat?
11. Which persons appear in which role (companion, source, collector, cited author)?

## 4. Beschreibungstexte

**Kurzbeschreibung (description, ein Satz)**

> Project ontology for a knowledge graph of bird observations extracted from the handwritten field diaries (1917–1965, 34 volumes) of the ornithologist Alfred Louis Laubmann, aligned with Darwin Core.

**Abstract (abstract)**: `dcterms:description` der Ontologie in `ontologies/laubmann.ttl` (englisch, ausführlich).

**Förderhinweis**

> The HistOrniGraph project was funded by NFDI4Biodiversity.

**Autoren**

| Name | E-Mail | ORCID | Affiliation |
|---|---|---|---|
| Tobias Perschl | Tobias.Perschl@uni-passau.de | 0009-0008-7070-8705 | Lehrstuhl für Computational Humanities, Universität Passau |
| Alois Wieshuber | alois.wieshuber@gda.bayern.de | 0009-0001-7010-7968 | Generaldirektion der Staatlichen Archive Bayerns |

## 5. Offene Punkte vor der Einreichung

1. **w3id-Namespace registrieren** (PR bei <https://github.com/perma-id/w3id.org>, Vorlage in `w3id/laubmann-kg/`); `w3id/laubmann-kg/README.md` nennt noch `Maelkolb` als Kontakt und `0.4.0` als aktuelle Version.
2. **Dokumentations-URL** festlegen (GitHub Pages für `docs/` oder w3id); die Seite selbst ist aktuell (`docs/ontology/index.html`, 0.7.1).
3. **Rechteinhaber/Publisher** klären (steht in `LICENSE` und `dcterms:publisher` als „HistOrniGraph / Laubmann KG Project“).
4. **Account und Gruppe** im BiodivPortal anlegen (`administeredBy`).
5. **Publikation** (Feld *publication*) – noch keine vorhanden.
6. Keywords mit URIs (Wikidata/GND, siehe oben) im Portalformular eintragen.

Erledigt am 2026-10-20: ORCIDs (`schema:identifier` / `schema:sameAs` an den Autoren), `LICENSE`,
pyLODE-Dokumentation neu erzeugt, Kompetenzfragen gegen 0.7.1 getestet
(Anleitung: `docs/competency_questions.md`), Beschreibung in `ontologies/shacl_shapes.ttl` auf 0.7.1.
