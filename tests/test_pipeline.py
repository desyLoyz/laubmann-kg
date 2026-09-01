from laubmann_kg.pipeline import build_entry, run_pipeline, select_sample_rows


def test_pipeline_builds_entries_and_observations(sample_config) -> None:
    result = run_pipeline(sample_config)
    assert len(result.entries) == 3

    by_id = {e.entry_id: e for e in result.entries}
    assert by_id["L02-e0001"].entry_date == "1918-04-07"
    # The weather-only entry yields no observation.
    assert by_id["L02-e0003"].observations == []
    # München resolves to seeded coordinates.
    muenchen = next(p for p in result.places.values() if p.canonical == "München")
    assert muenchen.lat is not None


def test_pipeline_is_deterministic(sample_config) -> None:
    first = [o.uid for o in run_pipeline(sample_config).observations]
    second = [o.uid for o in run_pipeline(sample_config).observations]
    assert first == second


def test_concurrent_extraction_matches_sequential(sample_config) -> None:
    sequential = run_pipeline(sample_config)
    sample_config["extraction"]["concurrency"] = 4
    concurrent = run_pipeline(sample_config)
    assert [e.entry_id for e in concurrent.entries] == [e.entry_id for e in sequential.entries]
    assert [o.uid for o in concurrent.observations] == [o.uid for o in sequential.observations]


def test_input_dir_prefers_cleaned_multimodal_catalogue(tmp_path) -> None:
    from laubmann_kg.pipeline import _resolve_corpus
    (tmp_path / "entries.csv").write_text("x", encoding="utf-8")
    assert _resolve_corpus({}, tmp_path) == (tmp_path / "entries.csv", None)
    (tmp_path / "multimodal.md").write_text("raw", encoding="utf-8")
    assert _resolve_corpus({}, tmp_path)[1] == tmp_path / "multimodal.md"
    (tmp_path / "multimodal_clean.md").write_text("clean", encoding="utf-8")
    assert _resolve_corpus({}, tmp_path)[1] == tmp_path / "multimodal_clean.md"


def test_select_sample_rows_by_inclusive_id_range() -> None:
    rows = [{"entry_id": f"L02-e{i:04d}"} for i in range(1, 6)]
    got = select_sample_rows(rows, {"entry_id_from": "L02-e0002", "entry_id_to": "L02-e0004"})
    assert [r["entry_id"] for r in got] == ["L02-e0002", "L02-e0003", "L02-e0004"]


def test_select_sample_rows_entry_ids_and_limit() -> None:
    rows = [{"entry_id": f"L02-e{i:04d}"} for i in range(1, 8)]
    got = select_sample_rows(rows, {"entry_ids": ["L02-e0001", "L02-e0004", "L02-e0007"], "limit": 2})
    assert [r["entry_id"] for r in got] == ["L02-e0001", "L02-e0004"]


def test_pipeline_honours_entry_id_range(sample_config) -> None:
    sample_config["sample"] = {"volume": 2, "entry_id_from": "L02-e0001", "entry_id_to": "L02-e0002"}
    result = run_pipeline(sample_config)
    assert [e.entry_id for e in result.entries] == ["L02-e0001", "L02-e0002"]


def test_build_entry_synthesises_uid_when_corpus_omits_it() -> None:
    entry = build_entry({
        "entry_id": "L02-e0001", "volume": "2", "page_id": "pageid-0004",
        "region_id": "r02", "scan": "4", "date_norm": "1918-04-07",
        "text_clean": "An der Isar sind einige Lachmöwen.",
    })
    assert entry.entry_uid == "e_L02-e0001"
    assert entry.page_uid == "pageid-0004"
    assert entry.region_uid == "r02"
