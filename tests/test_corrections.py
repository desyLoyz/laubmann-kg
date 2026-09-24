"""Reviewer value corrections (review/value_corrections.csv) applied before QA."""

from __future__ import annotations

import csv
from pathlib import Path

from laubmann_kg.kg.model import DiaryEntry, Observation, Place, Taxon, TravelEvent, TravelLeg
from laubmann_kg.normalization.corrections import FIELDS, Correction, apply_corrections, load_corrections
from laubmann_kg.pipeline import run_pipeline
from laubmann_kg.qa import run_qa

KAUFBEUREN = Place(verbatim="Kaufbeuren", canonical="Kaufbeuren", lat=47.88, long=10.62, kind="settlement")


def _entry(uid: str, observations=(), place=None, location_raw=None) -> DiaryEntry:
    e = DiaryEntry(entry_uid=uid, entry_id="L01-" + uid, volume=1, page_uid="p", page_id="doc_0007_L", region_uid=None,
                   scan=None, entry_date="1917-05-02", verbatim_event_date=None, location_raw=location_raw, text_clean="t")
    e.observations = list(observations); e.place = place
    for o in e.observations:
        o.entry_uid = uid
    return e


def _obs(taxon: Taxon, place=None, i=0) -> Observation:
    return Observation(entry_uid="", taxon=taxon, verbatim_notes="n", place=place, index=i)


def test_misread_non_bird_is_corrected_and_survives_qa() -> None:
    reh = Taxon("Reh", scientific_name="Capreolus capreolus", is_bird=False)
    e = _entry("e14", [_obs(reh), _obs(reh, i=1)])
    n, flags = apply_corrections([e], [Correction("taxon", "Reh", "Birkhenne", entry_uid="e14",
                                                  scientific_name="Lyrurus tetrix")])
    assert n == 2
    assert all(o.taxon.vernacular_de == "Birkhenne" and o.taxon.is_bird for o in e.observations)
    assert e.observations[0].taxon.scientific_name == "Lyrurus tetrix"
    assert e.observations[0].taxon.rank == "species"
    assert "„Reh“ → „Birkhenne“" in e.observations[0].occurrence_remarks
    assert [f.reason for f in flags] == ["value_corrected"]
    kept, qa = run_qa([e], {})
    assert len(kept[0].observations) == 2
    assert not [f for f in qa if f.reason in ("non_bird", "empty")]


def test_entry_scope_leaves_other_entries_alone_and_reuses_known_taxon() -> None:
    known = Taxon("Birkhenne", scientific_name="Lyrurus tetrix", is_bird=True, rank="species", confidence=0.9)
    reh = Taxon("Reh", is_bird=False)
    a, b, c = _entry("a", [_obs(reh)]), _entry("b", [_obs(reh)]), _entry("c", [_obs(known)])
    apply_corrections([a, b, c], [Correction("taxon", "reh", "Birkhenne", entry_uid="a")])
    assert a.observations[0].taxon is known          # reused: carries the model's resolution
    assert b.observations[0].taxon is reh


def test_matches_verbatim_name_only_in_the_given_entry() -> None:
    star = Taxon("Star", scientific_name="Sturnus vulgaris")
    o = _obs(star); o.taxon_verbatim = "Stam"
    a, b = _entry("a", [o]), _entry("b", [_obs(Taxon("Stam"))])
    n, _ = apply_corrections([a, b], [Correction("taxon", "Stam", "Staar", entry_uid="a")])
    assert n == 1 and o.taxon.vernacular_de == "Staar" and o.taxon_verbatim is None
    assert b.observations[0].taxon.vernacular_de == "Stam"


def test_misread_heading_becomes_entry_place() -> None:
    other = _entry("x", [_obs(Taxon("Amsel"), place=KAUFBEUREN)], place=KAUFBEUREN)
    e = _entry("e24", [_obs(Taxon("Dohle")), _obs(Taxon("Amsel"), i=1)], place=None, location_raw="Rauchschwalben")
    _, qa_before = run_qa([_entry("tmp", [_obs(Taxon("Dohle"))], location_raw="Rauchschwalben")], {})
    assert [f.reason for f in qa_before] == ["nonplace"]
    n, flags = apply_corrections([other, e], [Correction("place", "Rauchschwalben", "Kaufbeuren", entry_uid="e24")])
    assert e.place is KAUFBEUREN                      # reused with kind + coordinates
    assert all(o.place is KAUFBEUREN for o in e.observations)
    assert n == 3 and flags[0].reason == "value_corrected"
    _, qa = run_qa([e], {})
    assert not [f for f in qa if f.reason == "nonplace"]


def test_place_correction_keeps_own_localities_and_fixes_travel() -> None:
    wrong, own = Place(verbatim="Kaufbeuern"), Place(verbatim="Wertach")
    o1, o2 = _obs(Taxon("Amsel"), place=wrong), _obs(Taxon("Star"), place=own, i=1)
    o2.locality = own
    e = _entry("e", [o1, o2], place=wrong)
    e.travel_events = [TravelEvent("e", [TravelLeg(Place(verbatim="München"), wrong)])]
    apply_corrections([e], [Correction("place", "Kaufbeuern", "Kaufbeuren", entry_uid="e")])
    assert e.place.name == "Kaufbeuren" and o1.place is e.place and o2.place is own
    assert e.travel_events[0].legs[0].arrival_place is e.place


def test_unmatched_correction_is_reported() -> None:
    e = _entry("a", [_obs(Taxon("Amsel"))])
    n, flags = apply_corrections([e], [Correction("taxon", "Reh", "Birkhenne", entry_uid="a")])
    assert n == 0 and flags[0].reason == "correction_unmatched" and e.observations[0].taxon.vernacular_de == "Amsel"


def test_load_corrections_validates_rows(tmp_path: Path) -> None:
    p = tmp_path / "value_corrections.csv"
    with p.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS); w.writeheader()
        w.writerow({"kind": "taxon", "entry_uid": "e1", "old_value": "Reh", "new_value": "Birkhenne", "is_bird": ""})
        w.writerow({"kind": "taxon", "old_value": "Reh", "new_value": "X"})                  # no entry
        w.writerow({"kind": "person", "entry_uid": "e1", "old_value": "A", "new_value": "B"})  # unknown kind
        w.writerow({"kind": "place", "entry_id": "L01-e0024", "old_value": "A", "new_value": "B", "is_bird": "n"})
    rows = load_corrections(p)
    assert [(r.kind, r.old) for r in rows] == [("taxon", "Reh"), ("place", "A")]
    legacy = tmp_path / "legacy.csv"                     # corpus-wide rows are not accepted
    legacy.write_text("kind,scope,entry_uid,old_value,new_value\ntaxon,all,,Stam,Star\ntaxon,all,e2,Stam,Star\n", encoding="utf-8")
    assert load_corrections(legacy) == []
    assert rows[0].is_bird is True
    assert load_corrections(tmp_path / "missing.csv") == []


def test_pipeline_applies_corrections_before_qa(sample_config, tmp_path: Path) -> None:
    p = tmp_path / "value_corrections.csv"
    with p.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=FIELDS); w.writeheader()
        w.writerow({"kind": "place", "entry_uid": "", "entry_id": "L02-e0002",
                    "old_value": "Kaufbeuren", "new_value": "Kaufbeuren-Neugablonz"})
    sample_config["corrections"] = {"csv": str(p)}
    result = run_pipeline(sample_config)
    e = next(x for x in result.entries if x.entry_id == "L02-e0002")
    assert e.place.name == "Kaufbeuren-Neugablonz"
    assert any(f.reason == "value_corrected" and f.entry_id == "L02-e0002" for f in result.qa_flags)
