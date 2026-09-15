from pathlib import Path

from laubmann_kg.kg.explorer import graph_from_result, write_explorer
from laubmann_kg.pipeline import run_pipeline


def test_graph_from_result_matches_explorer_v7_schema(sample_config) -> None:
    result = run_pipeline(sample_config)
    graph = graph_from_result(result, meta={"tag": "test"})
    assert set(graph) >= {"meta", "entries", "obs", "taxa", "places", "persons", "habitats"}
    assert graph["meta"]["entries"] == len(result.entries)
    assert graph["meta"]["observations"] == len(result.observations)
    assert graph["meta"]["tag"] == "test"
    by_id = {e["id"]: e for e in graph["entries"]}
    assert "L02-e0001" in by_id
    first = by_id["L02-e0001"]
    assert first["text"]
    assert first["obs"]
    obs = graph["obs"][first["obs"][0]]
    assert obs["v"]
    assert "t" in obs
    taxon = graph["taxa"][obs["t"]]
    assert taxon["name"]
    assert taxon["u"].startswith("taxon_")


def test_graph_json_and_shell_expose_ziel1_fields() -> None:
    from laubmann_kg.kg.model import (
        DiaryEntry, Observation, Place, Taxon,
    )
    from laubmann_kg.pipeline import ExtractionResult

    place = Place("München", canonical="München", kind="settlement")
    own = Place("Äußere Prinzregentenstraße 14", canonical="Äußere Prinzregentenstraße 14",
                kind="locality")
    entry = DiaryEntry(
        entry_uid="e_ex1", entry_id="L02-e0002", volume=2, page_uid="p", page_id="pid",
        region_uid=None, scan=None, entry_date="1918-05-03",
        verbatim_event_date="3. Mai 1918", location_raw="München",
        text_clean="Vormittags 1/2 12 h vom Fenster.",
        place=place,
    )
    entry.observations = [Observation(
        entry_uid=entry.entry_uid, taxon=Taxon("Mauersegler"),
        verbatim_notes="erste Mauersegler", place=own, locality=own, index=0,
        spatial_context="vom Fenster meiner Wohnung an der äußeren Prinzregentenstraße 14",
        time_of_day="forenoon", event_time="11:30", estimated_radius_m=100,
        sampling_protocol="Ansitz/Fensterbeobachtung",
    )]
    obs = graph_from_result(ExtractionResult(entries=[entry]))["obs"][0]
    assert obs["sc"].startswith("vom Fenster")
    assert obs["tod"] == "forenoon" and obs["tm"] == "11:30" and obs["rad"] == 100
    html = Path("tools/explorer/index.html").read_text(encoding="utf-8")
    for term in ("lkg:spatialContext", "lkg:timeOfDay", "lkg:observationRadiusMeters",
                 "dwc:samplingProtocol", "lkg:microhabitat"):
        assert term in html


def test_write_explorer_copies_shell_and_graph(sample_config, tmp_path: Path) -> None:
    result = run_pipeline(sample_config)
    template = tmp_path / "shell.html"
    template.write_text("<!doctype html><title>explorer</title>", encoding="utf-8")
    summary = write_explorer(result, tmp_path / "run", template=template)
    graph_path = Path(summary["graph"])
    assert graph_path.exists()
    assert (tmp_path / "run" / "html" / "index.html").read_text(encoding="utf-8").startswith("<!doctype")
    assert summary["entries"] == len(result.entries)
