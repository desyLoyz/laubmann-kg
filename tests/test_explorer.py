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


def test_write_explorer_copies_shell_and_graph(sample_config, tmp_path: Path) -> None:
    result = run_pipeline(sample_config)
    template = tmp_path / "shell.html"
    template.write_text("<!doctype html><title>explorer</title>", encoding="utf-8")
    summary = write_explorer(result, tmp_path / "run", template=template)
    graph_path = Path(summary["graph"])
    assert graph_path.exists()
    assert (tmp_path / "run" / "html" / "index.html").read_text(encoding="utf-8").startswith("<!doctype")
    assert summary["entries"] == len(result.entries)
