"""Validation UI decisions: reviewed identities (review/identities.csv), readings
(review/text_corrections.csv) and mention-level value corrections."""

from __future__ import annotations

import csv
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import SKOS

from laubmann_kg.kg.model import DiaryEntry, Habitat, Observation, Person, Place, Taxon
from laubmann_kg.kg.rdf import DATA, build_graph
from laubmann_kg.linking.cache import JsonCache
from laubmann_kg.linking.persons import link_persons
from laubmann_kg.linking.taxa import link_taxa
from laubmann_kg.normalization.corrections import Correction, apply_corrections, apply_identity_removals
from laubmann_kg.pipeline import ExtractionResult, run_pipeline
from laubmann_kg.resolution.common import Decisions
from laubmann_kg.resolution.persons import merge_persons
from laubmann_kg.resolution.places import merge_places
from laubmann_kg.resolution.taxa import merge_taxa
from laubmann_kg.review.identities import IDENTITY_FIELDS, Identities, apply_mappings
from laubmann_kg.review.readings import READING_FIELDS, Reading, apply_readings

NO = Decisions()


def _write(path: Path, fields, rows) -> Path:
    with path.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def _ids(tmp_path: Path, *rows) -> Identities:
    return Identities.load(_write(tmp_path / "identities.csv", IDENTITY_FIELDS, rows))


def _entry(uid: str, persons=(), observations=(), place=None, text="t") -> DiaryEntry:
    e = DiaryEntry(entry_uid=uid, entry_id="L02-" + uid, volume=2, page_uid="p", page_id="doc_0001_L", region_uid=None,
                   scan=None, entry_date="1950-05-08", verbatim_event_date="8. Mai 1950", location_raw="München", text_clean=text)
    e.persons = list(persons); e.observations = list(observations); e.place = place
    for o in e.observations:
        o.entry_uid = uid
    return e


def _obs(taxon, i=0, observer=None, habitat=None, locality=None, place=None) -> Observation:
    return Observation(entry_uid="", taxon=taxon, verbatim_notes="n", index=i, observer=observer, habitat=habitat,
                       locality=locality, place=place)


# ----------------------------------------------------------------- identities file

def test_identities_load_and_lookup(tmp_path: Path) -> None:
    ids = _ids(tmp_path,
               {"section": "taxa", "name_form": "Dompfaff", "decision": "same", "target": "Gimpel",
                "authority": "gbif:2494543", "scientific_name": "Pyrrhula pyrrhula", "rank": "species"},
               {"section": "persons", "name_form": "Walter Wüst", "decision": "link", "target": "Walter Wüst",
                "authority": "wd:Q2546836 gnd:107753448"},
               {"section": "places", "name_form": "Englischer Garten", "decision": "link", "authority": "wd:Q131589",
                "lat": "48.1642", "lon": "11.6056", "uncertainty_m": "1000"},
               {"section": "taxa", "name_form": "x", "decision": "merge"},          # invalid decision: skipped
               {"section": "insects", "name_form": "y", "decision": "same"})        # invalid section: skipped
    d = ids.form("taxa", "DOMPFAFF")
    assert d.decision == "same" and d.gbif_key == 2494543 and d.scientific_name == "Pyrrhula pyrrhula"
    w = ids.link("persons", "walter wüst")
    assert w.auth("wd") == "Q2546836" and w.auth("gnd") == "107753448"
    g = ids.link("places", "Englischer Garten")
    assert (g.lat, g.lon, g.uncertainty_m) == (48.1642, 11.6056, 1000)
    assert ids.form("taxa", "x") is None and bool(ids)
    assert not Identities.load(tmp_path / "missing.csv")


def test_apply_mappings_same_own_absent_and_cycle(tmp_path: Path) -> None:
    ids = _ids(tmp_path,
               {"section": "places", "name_form": "Mairinger See", "decision": "same", "target": "Maisinger See"},
               {"section": "places", "name_form": "Hagenau", "decision": "own"},
               {"section": "places", "name_form": "Wörth", "decision": "same", "target": "Nirgendwo"},
               {"section": "places", "name_form": "Maisinger See", "decision": "same", "target": "Mairinger See"})
    mapping = {"Hagenau": "Hagnau", "Maisinger See": "Mairinger See"}
    names = ["Mairinger See", "Maisinger See", "Hagenau", "Hagnau", "Wörth"]
    apply_mappings(mapping, names, "places", ids)
    assert "Hagenau" not in mapping                      # own: out of every merge
    assert "Wörth" not in mapping                        # target absent: skipped
    # the two "same" rows point at each other: the second one would close a cycle
    assert sorted(mapping.items()) in ([("Mairinger See", "Maisinger See")], [("Maisinger See", "Mairinger See")])


# ----------------------------------------------------------------- readings

def test_readings_fix_text_and_header_before_extraction() -> None:
    e = _entry("e1", text="8. Mai 1950. München. Auch heute nur noch Kameradeneingänge gehört.")
    f = _entry("e2", text="Nichts.")
    flags = apply_readings([e, f], [Reading("Kameradeneingänge", "Hausrotschwänzchen", entry_uid="e1"),
                                     Reading("8. Mai", "9. Mai", entry_uid="e1"),
                                     Reading("Tirol", "Pirol", entry_uid="e2"),
                                     Reading("a", "b", entry_uid="gone")])
    assert "Hausrotschwänzchen gehört" in e.text_clean and e.text_clean.startswith("9. Mai 1950")
    assert e.verbatim_event_date == "9. Mai 1950" and e.entry_date == "1950-05-09"
    assert len(e.reading_notes) == 2 and f.text_clean == "Nichts."
    assert [x.reason for x in flags].count("reading_corrected") == 2
    assert [x.reason for x in flags].count("reading_unmatched") == 2
    g = build_graph(ExtractionResult(entries=[e]))
    assert Literal(e.reading_notes[0], lang="de") in set(g.objects(DATA[e.uid], SKOS.note))


def test_pipeline_applies_readings_and_identities(sample_config, tmp_path: Path) -> None:
    readings = _write(tmp_path / "text_corrections.csv", READING_FIELDS,
                      [{"entry_uid": "e_test0002", "old_text": "Grünspecht", "new_text": "Schwarzspecht"}])
    ids = tmp_path / "identities.csv"
    _write(ids, IDENTITY_FIELDS, [{"section": "taxa", "name_form": "Storch", "decision": "none", "reason": "misread"}])
    sample_config["review"] = {"text_corrections": str(readings), "identities": str(ids)}
    result = run_pipeline(sample_config)
    e2 = next(e for e in result.entries if e.entry_uid == "e_test0002")
    assert "Schwarzspecht" in e2.text_clean and e2.reading_notes
    assert not any(o.taxon.vernacular_de == "Storch" for e in result.entries for o in e.observations)
    reasons = {f.reason for f in result.qa_flags}
    assert {"reading_corrected", "review_not_taxon"} <= reasons


# ----------------------------------------------------------------- mention-level corrections

def test_mention_drop_with_occurrence_and_person_habitat_place() -> None:
    tirol = Taxon("Tirol", scientific_name="Pyrrhula pyrrhula")
    wiese = Place(verbatim="Ruinenwiese", kind="locality")
    e = _entry("e1", persons=[Person("Vormittags"), Person("W. Wüst")],
               observations=[_obs(tirol, 0, observer=Person("Vormittags")), _obs(tirol, 1),
                             _obs(Taxon("Star"), 2, habitat=Habitat("Garten"), locality=wiese, place=wiese)],
               place=Place(verbatim="München"))
    n, flags = apply_corrections([e], [
        Correction("taxon", "Tirol", action="drop", occurrence=1, entry_uid="e1", reason="place"),
        Correction("taxon", "tirol", "Pirol", entry_uid="e1", occurrence=0, scientific_name="Oriolus oriolus", gbif_key=2488949),
        Correction("person", "Vormittags", action="drop", entry_uid="e1"),
        Correction("person", "W. Wüst", "Walter Wüst", entry_uid="e1"),
        Correction("habitat", "Garten", action="drop", entry_uid="e1"),
        Correction("place", "Ruinenwiese", action="drop", entry_uid="e1")])
    assert [o.taxon.vernacular_de for o in e.observations] == ["Pirol", "Star"]
    assert e.observations[0].taxon.gbif_key == 2488949 and e.observations[0].observer is None
    assert [p.name for p in e.persons] == ["Walter Wüst"]
    star = e.observations[1]
    assert star.habitat is None and star.locality is None and star.place is e.place
    assert {f.reason for f in flags} == {"value_dropped", "value_corrected"}


def test_identity_removals_are_name_level(tmp_path: Path) -> None:
    ids = _ids(tmp_path, {"section": "taxa", "name_form": "Trink", "decision": "none", "reason": "misread"},
               {"section": "places", "name_form": "Forst", "decision": "none"})
    a = _entry("a", observations=[_obs(Taxon("Trink")), _obs(Taxon("Amsel"), 1)], place=Place(verbatim="Forst"))
    b = _entry("b", observations=[_obs(Taxon("trink"))])
    flags = apply_identity_removals([a, b], ids)
    assert [o.taxon.vernacular_de for o in a.observations] == ["Amsel"] and not b.observations
    assert a.place is None and a.observations[0].place is None
    assert sorted(f.reason for f in flags) == ["review_not_place", "review_not_taxon", "review_not_taxon"]


# ----------------------------------------------------------------- linking

def _gbif(monkeypatch, by_name):
    def fake(url, params, timeout=30.0):
        return by_name.get(params["name"].lower())
    monkeypatch.setattr("laubmann_kg.linking.http.get_json", fake)


def test_linked_name_fills_missing_scientific_names(tmp_path: Path, monkeypatch) -> None:
    # the model gave a scientific name for one Rohrweihe but not the other: both
    # observations must carry it, or the node loses dwc:scientificName
    _gbif(monkeypatch, {"circus aeruginosus": {"usageKey": 2480482, "matchType": "EXACT", "confidence": 99,
                                               "rank": "SPECIES", "canonicalName": "Circus aeruginosus"}})
    e = _entry("e1", observations=[_obs(Taxon("Rohrweihe")), _obs(Taxon("Rohrweihe", scientific_name="Circus aeruginosus"), 1)])
    link_taxa(ExtractionResult(entries=[e]), {"llm": {"enabled": False}}, JsonCache(tmp_path / "g.json"), offline=False)
    assert [(o.taxon.scientific_name, o.taxon.gbif_key) for o in e.observations] == [("Circus aeruginosus", 2480482)] * 2


def test_reviewed_taxon_identity_wins_and_merges(tmp_path: Path, monkeypatch) -> None:
    _gbif(monkeypatch, {"pyrrhula pyrrhula": {"usageKey": 2494543, "matchType": "EXACT", "confidence": 99,
                                              "rank": "SPECIES", "canonicalName": "Pyrrhula pyrrhula"}})
    ids = _ids(tmp_path,
               {"section": "taxa", "name_form": "Kameradeneingang", "decision": "same", "target": "Hausrotschwanz",
                "authority": "gbif:5739315", "scientific_name": "Phoenicurus ochruros", "rank": "species"},
               {"section": "taxa", "name_form": "Boßvogel", "decision": "own"})
    e = _entry("e1", observations=[_obs(Taxon("Kameradeneingang", scientific_name="Pyrrhula pyrrhula")),
                                   _obs(Taxon("Boßvogel", scientific_name="Pyrrhula pyrrhula"), 1),
                                   _obs(Taxon("Hausrotschwanz", scientific_name="Phoenicurus ochruros", gbif_key=5739315,
                                              gbif_match_type="EXACT", rank="species"), 2)])
    result = ExtractionResult(entries=[e], identities=ids)
    link_taxa(result, {"llm": {"enabled": False}}, JsonCache(tmp_path / "g.json"), offline=False)
    k, b = e.observations[0].taxon, e.observations[1].taxon
    assert (k.gbif_key, k.scientific_name, k.match_method) == (5739315, "Phoenicurus ochruros", "review")
    assert b.gbif_key is None and b.scientific_name is None
    merge_taxa(result, {}, NO)
    assert e.observations[0].taxon.vernacular_de == "Hausrotschwanz" and e.observations[0].taxon_verbatim == "Kameradeneingang"
    assert e.observations[1].taxon.vernacular_de == "Boßvogel"


def test_initials_never_auto_link_and_reviewed_links_win(tmp_path: Path, monkeypatch) -> None:
    calls = []
    def fake(url, params, timeout=30.0):
        calls.append(params.get("search") or params.get("ids"))
        if params.get("action") == "wbsearchentities":
            return {"search": [{"id": "Q71631", "label": "Walther Wüst", "description": "Indogermanist",
                                "match": {"type": "alias", "text": params["search"]}}]}
        return {"entities": {"Q71631": {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]}}}}
    monkeypatch.setattr("laubmann_kg.linking.http.get_json", fake)
    ids = _ids(tmp_path, {"section": "persons", "name_form": "Walter Wüst", "decision": "link", "authority": "wd:Q2546836"})
    e = [_entry("e1", persons=[Person("W. Wüst")]), _entry("e2", persons=[Person("Walter Wüst")])]
    result = ExtractionResult(entries=e, identities=ids)
    link_persons(result, {}, JsonCache(tmp_path / "wd.json"), offline=False)
    assert e[0].persons[0].wikidata_iri is None                     # "W. Wüst": initials only, never auto-linked
    assert e[1].persons[0].wikidata_iri.endswith("Q2546836")        # reviewed
    assert not any(c == "W. Wüst" for c in calls)
    # an automatic link on a variant (as in the 2026-08-19 export) loses against the reviewed link
    e[0].persons = [Person("W. Wüst", wikidata_iri="http://www.wikidata.org/entity/Q71631")]
    merge_persons(result, {}, NO)
    assert {p.name for x in e for p in x.persons} == {"Walter Wüst"}
    assert all(p.wikidata_iri.endswith("Q2546836") for x in e for p in x.persons)


def test_reviewed_person_forms_move_and_stay_apart(tmp_path: Path) -> None:
    ids = _ids(tmp_path, {"section": "persons", "name_form": "Dr. Wüst", "decision": "own"},
               {"section": "persons", "name_form": "H. Wüst", "decision": "same", "target": "Hans Wüst"})
    e = [_entry("e1", persons=[Person("Walter Wüst"), Person("Dr. Wüst"), Person("H. Wüst"), Person("Hans Wüst")])]
    merge_persons(ExtractionResult(entries=e, identities=ids), {}, NO)
    assert [p.name for p in e[0].persons] == ["Walter Wüst", "Dr. Wüst", "Hans Wüst"]


def test_reviewed_place_identity_and_nolink(tmp_path: Path) -> None:
    ids = _ids(tmp_path, {"section": "places", "name_form": "Mairinger See", "decision": "same", "target": "Maisinger See"},
               {"section": "places", "name_form": "Neufinning", "decision": "own"})
    sees = [Place(verbatim="Maisinger See"), Place(verbatim="Mairinger See"), Place(verbatim="Neufinsing"), Place(verbatim="Neufinning")]
    e = [_entry(f"e{i}", place=p) for i, p in enumerate(sees)]
    rows_dec = Decisions(by_id={"places: Neufinning -> Neufinsing": "y"})     # an old machine decision
    merge_places(ExtractionResult(entries=e, identities=ids), {"similarity": 0.8}, rows_dec)
    assert e[1].place.name == "Maisinger See" and e[3].place.name == "Neufinning"


# ----------------------------------------------------------------- machine review layer

def test_machine_identities_fill_only_unreviewed_forms_above_thresholds(tmp_path: Path) -> None:
    human = _write(tmp_path / "identities.csv", IDENTITY_FIELDS, [
        {"section": "taxa", "name_form": "Dompfaff", "decision": "same", "target": "Gimpel", "authority": "gbif:2494543"}])
    machine = _write(tmp_path / "identities_machine.csv", IDENTITY_FIELDS + ["confidence", "agreement"], [
        # same form as the human row: the human decision wins even at full confidence
        {"section": "taxa", "name_form": "dompfaff", "decision": "none", "confidence": "1.0", "agreement": "3"},
        # clears both thresholds: taken over
        {"section": "taxa", "name_form": "Wildente", "decision": "same", "target": "Stockente", "authority": "gbif:9761484",
         "scientific_name": "Anas platyrhynchos", "rank": "species", "confidence": "0.95", "agreement": "2"},
        # below the agreement threshold
        {"section": "taxa", "name_form": "Türkenlämmer", "decision": "none", "confidence": "0.95", "agreement": "1"},
        # below the confidence threshold
        {"section": "persons", "name_form": "Adolf Müller", "decision": "link", "authority": "wd:Q1", "confidence": "0.6", "agreement": "2"},
        # a link row that clears both
        {"section": "places", "name_form": "Süddamm", "decision": "link", "authority": "osm:way/1 wd:Q2", "lat": "48.2", "lon": "11.7",
         "uncertainty_m": "500", "confidence": "0.9", "agreement": "2"}])
    ids = Identities.load_layers(human, machine, min_confidence=0.9, min_agreement=2)
    assert ids.form("taxa", "Dompfaff").decision == "same" and ids.form("taxa", "Dompfaff").target == "Gimpel"
    assert ids.form("taxa", "Wildente").gbif_key == 9761484
    assert ids.form("taxa", "Türkenlämmer") is None
    assert ids.link("persons", "Adolf Müller") is None
    assert ids.link("places", "Süddamm").auth("osm") == "way/1" and ids.link("places", "Süddamm").uncertainty_m == 500
    # without a machine file the human decisions are all there is
    assert not Identities.load_layers(human, None).form("taxa", "Wildente")


def test_machine_corrections_filtered_by_confidence(tmp_path: Path) -> None:
    from laubmann_kg.normalization.corrections import FIELDS, load_corrections
    path = _write(tmp_path / "value_corrections_machine.csv", FIELDS + ["confidence"], [
        {"kind": "taxon", "entry_uid": "e_1", "old_value": "Tirol", "occurrence": "0", "action": "replace", "new_value": "Pirol",
         "scientific_name": "Oriolus oriolus", "gbif_key": "2483000", "confidence": "0.95"},
        {"kind": "taxon", "entry_uid": "e_1", "old_value": "Stam", "action": "drop", "confidence": "0.7"},
        {"kind": "place", "entry_uid": "e_2", "old_value": "Rauchschwalben", "action": "drop"}])          # no confidence column value: passes
    rows = load_corrections(path, min_confidence=0.9)
    assert [(c.old, c.action) for c in rows] == [("Tirol", "replace"), ("Rauchschwalben", "drop")]
    assert len(load_corrections(path)) == 3


def test_earlier_machine_layer_wins_over_later(tmp_path: Path) -> None:
    """The georeference check is listed before identities_machine.csv and wins for the same place."""
    cols = IDENTITY_FIELDS + ["confidence", "agreement"]
    georef = _write(tmp_path / "georef_machine.csv", cols, [
        {"section": "places", "name_form": "Kalamos", "decision": "link", "authority": "gn:261565", "lat": "38.628",
         "lon": "20.909", "confidence": "0.9", "agreement": "2"},
        {"section": "places", "name_form": "Tietzing", "decision": "nolink", "confidence": "0.9", "agreement": "2"}])
    machine = _write(tmp_path / "identities_machine.csv", cols, [
        {"section": "places", "name_form": "Kalamos", "decision": "link", "authority": "gn:261571", "lat": "38.284",
         "lon": "23.863", "confidence": "0.95", "agreement": "2"}])
    ids = Identities.load_layers(None, [georef, machine])
    assert ids.link("places", "Kalamos").geonames_id == 261565
    assert ids.link("places", "Tietzing").decision == "nolink"
    assert Identities.load_layers(None, [None, machine]).link("places", "Kalamos").geonames_id == 261571
