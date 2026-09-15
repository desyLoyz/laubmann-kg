"""Ontology 0.5.0 Ziel 1: spatial / temporal qualification of observations.

The 1918-05-03 Mauersegler window-watch is the canonical sample: locality is
the street address, spatial_context keeps the vantage wording, clock time and
forenoon slot are split, and the urban window radius is 100 m.
"""

from __future__ import annotations

import json
from pathlib import Path

from rdflib import Literal
from rdflib.namespace import RDF, XSD

from laubmann_kg.extraction.llm_observations import extract_observations_llm, load_entry_schema
from laubmann_kg.kg.model import DiaryEntry
from laubmann_kg.kg.rdf import DATA, DWC, LKG, build_graph
from laubmann_kg.kg.shacl_validate import run_shacl_validation
from laubmann_kg.llm.prompts import PromptLibrary
from laubmann_kg.normalization.taxa import SeedTaxonResolver
from laubmann_kg.pipeline import ExtractionResult

REPO_ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = REPO_ROOT / "ontologies" / "laubmann.ttl"
SHAPES = REPO_ROOT / "ontologies" / "shacl_shapes.ttl"
PROMPTS = PromptLibrary(REPO_ROOT / "prompts")
SCHEMA = load_entry_schema()

MAUERSEGLER_TEXT = (
    "Vormittags 1/2 12 h beobachtete ich vom Fenster meiner Wohnung an der "
    "äußeren Prinzregentenstraße 14 die ersten Mauersegler."
)

MAUERSEGLER_PAYLOAD = {
    "entry_date": {"iso": "1918-05-03"},
    "entry_place": {"name": "München", "kind": "settlement"},
    "entry_kind": "field-day",
    "observations": [{
        "vernacular_de": "Mauersegler",
        "scientific_name": "Apus apus",
        "is_bird": True,
        "verbatim_notes": MAUERSEGLER_TEXT,
        "locality": {
            "name": "Äußere Prinzregentenstraße 14",
            "verbatim": "äußeren Prinzregentenstraße 14",
        },
        "spatial_context": "vom Fenster meiner Wohnung an der äußeren Prinzregentenstraße 14",
        "microhabitat": "Wohngebäude/Fenster",
        "time_of_day": "forenoon",
        "daylight_phase": "day",
        "event_time": "11:30",
        "sampling_protocol": "Ansitz/Fensterbeobachtung",
        "estimated_radius_m": 100,
        "spatial_confidence": "high",
        "evidence": [{"kind": "visual"}],
        "confidence": 0.95,
    }],
    "travel_events": [],
    "persons": [],
    "weather": None,
}


class _FakeClient:
    model = "fake"

    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload)

    def complete(self, prompt: str) -> str:
        return self.payload


def _mauersegler_entry() -> DiaryEntry:
    return DiaryEntry(
        entry_uid="e_1918_05_03",
        entry_id="L02-e1918-05-03",
        volume=2,
        page_uid="p_1918_05_03",
        page_id="L02-p0503",
        region_uid="r_1918_05_03",
        scan=None,
        entry_date="1918-05-03",
        verbatim_event_date="3. V. 1918",
        location_raw="München",
        text_clean=MAUERSEGLER_TEXT,
    )


def test_mauersegler_1918_05_03_window_watch_fields() -> None:
    entry = _mauersegler_entry()
    obs = extract_observations_llm(
        entry, _FakeClient(MAUERSEGLER_PAYLOAD), SeedTaxonResolver(),
        None, PROMPTS, SCHEMA,
    )
    assert len(obs) == 1
    record = obs[0]
    assert record.taxon.vernacular_de == "Mauersegler"
    assert record.spatial_context == (
        "vom Fenster meiner Wohnung an der äußeren Prinzregentenstraße 14"
    )
    assert record.time_of_day == "forenoon"
    assert record.event_time == "11:30"
    assert record.estimated_radius_m == 100
    assert record.sampling_protocol == "Ansitz/Fensterbeobachtung"
    assert record.microhabitat == "Wohngebäude/Fenster"
    assert record.spatial_confidence == "high"
    assert record.locality is not None
    assert record.locality.name == "Äußere Prinzregentenstraße 14"
    assert entry.place is not None
    assert entry.place.name == "München"
    assert record.locality.uid != entry.place.uid


def test_mauersegler_1918_05_03_rdf_and_shacl(tmp_path: Path) -> None:
    entry = _mauersegler_entry()
    entry.observations = extract_observations_llm(
        entry, _FakeClient(MAUERSEGLER_PAYLOAD), SeedTaxonResolver(),
        None, PROMPTS, SCHEMA,
    )
    graph = build_graph(ExtractionResult(entries=[entry]))
    node = DATA[entry.observations[0].uid]
    assert (node, RDF.type, LKG.Observation) in graph
    assert graph.value(node, LKG.spatialContext) == Literal(
        "vom Fenster meiner Wohnung an der äußeren Prinzregentenstraße 14", lang="de"
    )
    assert graph.value(node, LKG.timeOfDay) == Literal("forenoon")
    assert graph.value(node, DWC.eventTime) == Literal("11:30")
    assert graph.value(node, LKG.observationRadiusMeters) == Literal(
        100, datatype=XSD.integer
    )
    assert graph.value(node, DWC.coordinateUncertaintyInMeters) == Literal(
        100, datatype=XSD.integer
    )
    assert graph.value(node, DWC.samplingProtocol) == Literal(
        "Ansitz/Fensterbeobachtung", lang="de"
    )
    locality = graph.value(node, LKG.hasLocality)
    assert locality == DATA[entry.observations[0].locality.uid]
    assert graph.value(locality, RDF.type) is not None
    assert graph.value(DATA[entry.uid], LKG.entryPlace) == DATA[entry.place.uid]
    assert locality != DATA[entry.place.uid]

    ttl = tmp_path / "mauersegler_1918_05_03.ttl"
    graph.serialize(destination=str(ttl), format="turtle")
    assert run_shacl_validation(
        data_path=str(ttl), ontology_path=str(ONTOLOGY), shapes_path=str(SHAPES),
    )
