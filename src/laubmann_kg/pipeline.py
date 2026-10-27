"""Corpus → in-memory model pipeline shared by the extraction and export stages.

Loads the frozen corpus interface (entries.csv + multimodal), builds domain
objects, and runs extraction (LLM by default in production; the offline
rule-based backend is the network-free test double). Switching from the sample
to the deduped corpus is a path change in the config, not a code change.
"""

from __future__ import annotations

import collections

import datetime as _dt
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from laubmann_kg.env import load_dotenv
from laubmann_kg.extraction.observations import extract_observations
from laubmann_kg.io.csv import read_entries
from laubmann_kg.io.metadata import read_multimodal, to_region
from laubmann_kg.kg.model import DiaryEntry, Place, SourceRegionRef
from laubmann_kg.normalization.dates import normalize_date
from laubmann_kg.normalization.places import normalize_place
from laubmann_kg.normalization.taxa import build_resolver

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    entries: list[DiaryEntry] = field(default_factory=list)
    places: dict[str, Place] = field(default_factory=dict)
    multimodal: list[dict] = field(default_factory=list)
    qa_flags: list = field(default_factory=list)
    # How the graph was produced (backend/model/prompt hash/timestamp): feeds the
    # PROV skeleton in kg/rdf.py and measurementMethod in the DwC-A.
    provenance: dict = field(default_factory=dict)
    # volume -> (start, end) YYYY-MM from configs/volume_coverage.yaml (title
    # pages); emitted as dcterms:temporal on the DiaryVolume nodes
    volume_spans: dict = field(default_factory=dict)
    # public base URL of the region crops once hosted (config multimodal.image_base_url);
    # None = crops are only referenced by their path (dcterms:identifier)
    image_base_url: Optional[str] = None
    # reviewed identities of name forms (review/identities.csv, validation UI):
    # read by linking and resolution; see laubmann_kg.review.identities
    identities: object = None

    @property
    def observations(self) -> list:
        return [obs for entry in self.entries for obs in entry.observations]


def load_config(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _resolve_corpus(config: dict, input_dir: Optional[Path]) -> tuple[Path, Optional[Path]]:
    corpus = config.get("corpus", {})
    entries = None
    multimodal = None
    if input_dir and (Path(input_dir) / "entries.csv").exists():
        entries = Path(input_dir) / "entries.csv"
        # the relinked region file (HistOrniGraph_addons/build_multimodal_regions.py:
        # catalogue v2 + selected text inserts, duplicates removed, entry_uid of
        # THIS corpus) wins over the cleaned catalogue (multimodal_clean.md:
        # duplicate pages and degenerate crops removed), which wins over the raw one
        for name in ("multimodal_regions.jsonl", "multimodal_clean.md", "multimodal.md"):
            mm = Path(input_dir) / name
            if mm.exists():
                multimodal = mm
                break
    if entries is None and corpus.get("entries"):
        entries = Path(corpus["entries"])
    if multimodal is None and corpus.get("multimodal"):
        candidate = Path(corpus["multimodal"])
        multimodal = candidate if candidate.exists() else None
    if entries is None:
        raise FileNotFoundError("No entries.csv found via input-dir or config.corpus.entries")
    return entries, multimodal


def _source_regions(raw: Optional[str]) -> list[SourceRegionRef]:
    """``source_regions`` column of a patched corpus: JSON list of the body-text
    regions the entry's text runs through ({region_uid, page_uid, page_id, scan})."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("unreadable source_regions cell: %.60s", raw)
        return []
    return [SourceRegionRef(str(i["region_uid"]), str(i.get("page_uid") or ""), str(i.get("page_id") or ""),
                            str(i["scan"]) if i.get("scan") not in (None, "") else None)
            for i in items if isinstance(i, dict) and i.get("region_uid")]


def build_entry(row: dict) -> DiaryEntry:
    entry_id = row.get("entry_id") or ""
    # Some corpus dumps omit the content-addressed uids; fall back so observations
    # still get a stable provenance key (never collide on an empty string).
    entry_uid = row.get("entry_uid") or (f"e_{entry_id}" if entry_id else "")
    return DiaryEntry(
        entry_uid=entry_uid,
        entry_id=entry_id,
        volume=int(row.get("volume") or 0),
        page_uid=row.get("page_uid") or row.get("page_id") or "",
        page_id=row.get("page_id") or "",
        region_uid=row.get("region_uid") or row.get("region_id") or None,
        scan=row.get("scan") or None,
        entry_date=normalize_date(row.get("date_raw"), row.get("date_norm")),
        verbatim_event_date=row.get("date_raw") or None,
        location_raw=row.get("location_raw") or None,
        text_clean=row.get("text_clean") or row.get("text_raw") or "",
        source_regions=_source_regions(row.get("source_regions")),
        context_before=(row.get("context_before") or "").strip() or None,
        boundary_kind=(row.get("boundary_kind") or "").strip() or None,
        boundary_source=(row.get("boundary_source") or "").strip() or None,
    )


def select_sample_rows(rows: list[dict], sample: dict) -> list[dict]:
    """Restrict the corpus to a review subset.

    Applied after the volume filter, in this order: explicit ``entry_ids``,
    inclusive ``entry_id_from`` / ``entry_id_to`` (string compare, so the
    zero-padded ``L02-e0100`` form sorts correctly), then ``offset`` /
    ``limit``. An empty sample dict returns ``rows`` unchanged.
    """
    sample = sample or {}
    entry_ids = sample.get("entry_ids")
    if entry_ids:
        wanted = {str(x) for x in entry_ids}
        rows = [row for row in rows if (row.get("entry_id") or "") in wanted]
    start = sample.get("entry_id_from")
    if start:
        rows = [row for row in rows if (row.get("entry_id") or "") >= str(start)]
    end = sample.get("entry_id_to")
    if end:
        rows = [row for row in rows if (row.get("entry_id") or "") <= str(end)]
    offset = int(sample.get("offset") or 0)
    if offset:
        rows = rows[offset:]
    limit = int(sample.get("limit") or 0)
    if limit:
        rows = rows[:limit]
    return rows


def _prompt_fingerprint(prompt_dir: Path, name: str = "observation_extraction") -> Optional[str]:
    path = Path(prompt_dir) / f"{name}.md"
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_extractor(config: dict) -> tuple:
    """Return ``(extract(entry, place) -> list[Observation], provenance)`` selected
    by ``extraction.backend`` (offline rule-based, or an LLM provider)."""
    extraction = config.get("extraction", {})
    backend = (extraction.get("backend") or "offline").lower()
    resolver = build_resolver(config.get("taxa"))
    started = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()

    if backend in ("offline", "rule", "rules", "gazetteer"):
        provenance = {"backend": "offline", "model": "rule-based", "started_at": started,
                      "method": "rule-based extraction from diary text (offline backend)"}
        return (lambda entry, place: extract_observations(entry, resolver, place)), provenance

    from laubmann_kg.extraction.llm_observations import extract_observations_llm, load_entry_schema
    from laubmann_kg.llm.cache import LLMCache
    from laubmann_kg.llm.clients import build_client
    from laubmann_kg.llm.prompts import PromptLibrary

    cache = LLMCache(Path(extraction["cache_dir"])) if extraction.get("cache_dir") else None
    client = build_client(cache=cache, config={
        "backend": extraction.get("provider", "google"),
        "model": extraction.get("model"),
        "api_key_env": extraction.get("api_key_env", "GOOGLE_API_KEY"),
        "temperature": extraction.get("temperature", 0.0),
        "max_output_tokens": extraction.get("max_output_tokens", 4096),
        "timeout": extraction.get("timeout", 120),
        "thinking_level": extraction.get("thinking_level"),
        "context_cache": extraction.get("context_cache", False),
        "context_cache_ttl_s": extraction.get("context_cache_ttl_s", 10800),
        "retry_attempts": extraction.get("retry_attempts", 3),
        "retry_backoff": extraction.get("retry_backoff", 2.0),
    })
    prompt_dir = Path(extraction.get("prompt_dir", "prompts"))
    prompts = PromptLibrary(prompt_dir)
    schema = load_entry_schema(extraction.get("schema"))
    model = extraction.get("model")
    logger.info("extraction backend=%s provider=%s model=%s", backend,
                extraction.get("provider", "google"), model)
    provenance = {
        "backend": backend,
        "provider": extraction.get("provider", "google"),
        "model": model,
        "prompt": "observation_extraction",
        "prompt_sha256": _prompt_fingerprint(prompt_dir),
        "temperature": extraction.get("temperature", 0.0),
        "thinking_level": extraction.get("thinking_level"),
        "started_at": started,
        "method": f"LLM extraction from diary text ({model})",
    }
    return (lambda entry, place: extract_observations_llm(
        entry, client, resolver, place, prompts, schema)), provenance


def entry_page_ids(entry: DiaryEntry) -> list[str]:
    """The pages an entry is written on, in reading order (header page first)."""
    ids = [entry.page_id] + [ref.page_id for ref in entry.source_regions]
    return [i for i in dict.fromkeys(ids) if i]


def page_image_loader(cfg: dict):
    """``entry -> [(page_id, jpeg bytes)]`` for the visual reading (config
    ``reading``: enabled, images_dir, max_pages), or None when disabled.
    Pages without an image file are left out (logged once)."""
    if not cfg.get("enabled"):
        return None
    folder = Path(cfg.get("images_dir", "data/pages_jpg"))
    max_pages = int(cfg.get("max_pages", 12))
    missing: set[str] = set()

    def load(entry: DiaryEntry):
        out = []
        for page_id in entry_page_ids(entry)[:max_pages]:
            path = folder / f"{page_id}.jpg"
            if path.exists():
                out.append((page_id, path.read_bytes()))
            elif page_id not in missing:
                missing.add(page_id)
                logger.warning("no page image %s (entry %s)", path, entry.entry_id)
        return out
    return load


def load_entries(config: dict, input_dir: Optional[Path] = None) -> tuple[list[DiaryEntry], list]:
    """The entries a run extracts, exactly as the model will read them: the
    corpus rows of the configured sample, with the reviewed readings
    (``review.text_corrections``) applied to their texts. Returns (entries,
    reading flags). Shared by run_pipeline and tools/batch_extract.py, so both
    render byte-identical prompts (the LLM cache key)."""
    from laubmann_kg.review.readings import apply_readings, load_readings
    entries_csv, _ = _resolve_corpus(config, input_dir)
    sample = config.get("sample", {}) or {}
    volume = sample.get("volume")
    rows = read_entries(entries_csv, volume=int(volume) if volume is not None else None)
    # neighbours in the volume stream (for the visual reading: the text of the
    # entry before/after on a shared page is not this entry's)
    around: dict[str, tuple[str, str]] = {}
    for i, row in enumerate(rows):
        prev = rows[i - 1] if i > 0 and rows[i - 1].get("volume") == row.get("volume") else None
        nxt = rows[i + 1] if i + 1 < len(rows) and rows[i + 1].get("volume") == row.get("volume") else None
        around[row.get("entry_id") or ""] = ((prev.get("text_clean") or "")[-300:] if prev else "",
                                             (nxt.get("text_clean") or "")[:300] if nxt else "")
    rows = select_sample_rows(rows, sample)
    built = [build_entry(row) for row in rows]
    for entry in built:
        entry.neighbour_before, entry.neighbour_after = around.get(entry.entry_id, ("", ""))
    review_cfg = config.get("review") or {}
    reading_flags = apply_readings(built, load_readings(review_cfg.get("text_corrections")))
    return built, reading_flags


def run_pipeline(config: dict, input_dir: Optional[Path] = None) -> ExtractionResult:
    load_dotenv()
    _, multimodal_path = _resolve_corpus(config, input_dir)
    sample = config.get("sample", {}) or {}
    volume = sample.get("volume")
    extract, provenance = _build_extractor(config)

    built, reading_flags = load_entries(config, input_dir)
    total = len(built)
    # Visual reading (config ``reading``): each transcription is checked against
    # its page scans and corrected before the extraction model reads it.
    reading_cfg = config.get("reading") or {}
    # The machine layer of the text (review.machine.text_layer: the checks' better readings and the scan
    # agent's corrections): changes that need the model go in before the extraction (the entry is read
    # anew), the others are patched into the extracted entry afterwards (text, passages, and the species
    # or places they change as value corrections), so their extraction stays cached.
    machine_text = (config.get("review") or {}).get("machine") or {}
    machine_text = machine_text if machine_text.get("enabled", True) else {}
    layer_decisions, layer_readings, layer_after, after_uids = {}, [], [], set()
    if machine_text.get("text_layer") and reading_cfg.get("enabled"):
        from laubmann_kg.extraction.reading import load_transcript_decisions
        from laubmann_kg.review.better_readings import layer_parts, load_layer, reviewed_entries
        from laubmann_kg.review.readings import load_readings
        reviewed = reviewed_entries(load_transcript_decisions(reading_cfg.get("decisions")),
                                    load_readings((config.get("review") or {}).get("text_corrections")))
        layer_decisions, layer_readings, layer_after, after_uids = layer_parts(load_layer(machine_text["text_layer"]), reviewed)
        logger.info("text layer: %d decisions and %d readings before the extraction, %d changes in %d entries after it",
                    len(layer_decisions), len(layer_readings), len(layer_after), len(after_uids))
    if reading_cfg.get("enabled"):
        from laubmann_kg.extraction.reading import reading_prompt_sha, run_reading
        if layer_decisions:   # under the reviewer's decisions
            reading_cfg = dict(reading_cfg, machine_decisions=layer_decisions)
        logger.info("reading: %s", run_reading(built, reading_cfg, page_image_loader(reading_cfg)))
        if layer_readings:    # the scan agent's corrections of the corrected text, after the reading
            from laubmann_kg.review.better_readings import machine_readings
            reading_flags = list(reading_flags) + machine_readings(built, layer_readings, reading_cfg.get("decisions"))
        provenance["reading"] = {"model": reading_cfg.get("model", "gemini-3.8-flash"),
                                 "prompt": "transcript_reading",
                                 "prompt_sha256": reading_prompt_sha(reading_cfg.get("prompt_dir")),
                                 "media_resolution": reading_cfg.get("media_resolution", "MEDIA_RESOLUTION_HIGH")}
    extraction_cfg = config.get("extraction", {})
    backend = (extraction_cfg.get("backend") or "offline").lower()
    concurrency = max(1, int(extraction_cfg.get("concurrency", 1)))
    logger.info(
        "extracting %d entries (volume=%s, entry_id_from=%s, entry_id_to=%s, "
        "limit=%s, backend=%s, concurrency=%d)",
        total, volume, sample.get("entry_id_from") or "none",
        sample.get("entry_id_to") or "none", sample.get("limit") or "none",
        backend, concurrency,
    )

    result = ExtractionResult(provenance=provenance,
                              image_base_url=(config.get("multimodal") or {}).get("image_base_url") or None)

    # Validation decisions (tools/validation_ui export, config section ``review``):
    # corrected readings are applied to the entry texts BEFORE extraction (the
    # model reads the corrected entry; only those entries miss the LLM cache),
    # reviewed identities are read by the corrections, linking and resolution stages.
    review_cfg = config.get("review") or {}
    from laubmann_kg.review.identities import Identities
    # machine review (tools/validation_ui/machine_review): fills the forms nobody reviewed;
    # a human row in identities.csv always wins, machine rows need confidence + agreement
    machine_cfg = review_cfg.get("machine") or {}
    # the georeference check (data/review/machine/georef_machine.csv) is more specific than the
    # general identity review, so its place links come first
    machine_ids = [machine_cfg.get("georef"), machine_cfg.get("identities")] if machine_cfg.get("enabled", True) else None
    result.identities = Identities.load_layers(review_cfg.get("identities"), machine_ids,
                                              float(machine_cfg.get("min_confidence", 0.9)), int(machine_cfg.get("min_agreement", 2)))

    # Sequential prep. The gazetteer/regex reading of the header is only the
    # FALLBACK place: the LLM extractor replaces it with the model's own reading
    # of the entry place (entry.place); the offline backend keeps it.
    jobs: list[tuple] = []
    for entry in built:
        entry.place = normalize_place(entry.location_raw)
        jobs.append((entry, entry.place))

    def _extract_one(job):
        entry, place = job
        try:
            return extract(entry, place)
        except Exception as exc:  # noqa: BLE001 - one bad entry must not abort the run
            logger.error("%s extraction failed: %s -- skipping", entry.entry_id, exc)
            return None

    # Parallel extraction; executor.map preserves input order, so results,
    # logging, and downstream exports stay deterministic.
    empty = failed = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for i, (job, observations) in enumerate(zip(jobs, pool.map(_extract_one, jobs)), 1):
            entry, _ = job
            if observations is None:
                failed += 1
                observations = []
            entry.observations = observations
            if not entry.observations:
                empty += 1
            result.entries.append(entry)
            logger.info("[%d/%d] %s -> %d observations", i, total, entry.entry_id,
                        len(entry.observations))

    # Reviewer corrections of misread species/place names (review/value_corrections.csv):
    # applied before coverage and QA so a corrected "non-bird" or place-less entry is judged anew.
    correction_flags: list = list(reading_flags)
    corr_cfg = config.get("corrections") or {}
    from laubmann_kg.normalization.corrections import (apply_corrections, apply_identity_removals, load_corrections,
                                                       place_merge_aliases)
    resolution = config.get("resolution") or {}
    merged = place_merge_aliases((resolution.get("places") or {}).get("reviewed_csv")
                                 or Path(resolution.get("review_dir") or "data/review") / "place_merges.csv")
    if layer_after:
        # the text layer's changes after the extraction: first the species and places they change (the value
        # corrections still address the names as extracted), then the text, header and record passages
        from laubmann_kg.review.better_readings import patch as patch_text
        values = [c for c in load_corrections(machine_text.get("text_values")) if c.entry_uid in after_uids] \
            if machine_text.get("text_values") else []
        correction_flags += apply_corrections(result.entries, values, merged)[1]
        correction_flags += patch_text(result.entries, layer_after)
    if corr_cfg.get("enabled", True) and corr_cfg.get("csv"):
        correction_flags += apply_corrections(result.entries, load_corrections(corr_cfg["csv"]), merged)[1]
    if machine_cfg.get("enabled", True) and machine_cfg.get("value_corrections"):
        # scan-checked single mentions of the machine review, above the confidence threshold only
        correction_flags += apply_corrections(result.entries, load_corrections(
            machine_cfg["value_corrections"], float(machine_cfg.get("min_correction_confidence", 0.9)),
            int(machine_cfg.get("min_agreement", 2))), merged)[1]
    # name-level "not a taxon / person / place / habitat" decisions of the review
    correction_flags += apply_identity_removals(result.entries, result.identities)
    # single record fields (count, locality, date, observer, record type …) and records
    # added by hand (review/observation_corrections.csv); after the value corrections,
    # so a record is addressed by the name the graph shows for it
    from laubmann_kg.normalization.observation_corrections import (
        apply_observation_corrections, load_observation_corrections)
    # machine layers first, the reviewer's rows last (a human decision always wins): the record checks of
    # round 4, then the attribution check, which asks the one question who made the records credited to the
    # diarist and wins over a record check's record type for the same record (L28-e0133a: round 4 read the
    # "ich" of Wüst's 544th Begehung report as Laubmann)
    if machine_cfg.get("enabled", True) and machine_cfg.get("observation_corrections"):
        correction_flags += apply_observation_corrections(result.entries, load_observation_corrections(
            machine_cfg["observation_corrections"], float(machine_cfg.get("min_correction_confidence", 0.9)),
            int(machine_cfg.get("min_agreement", 2))))[1]
    if machine_cfg.get("enabled", True) and machine_cfg.get("attribution"):
        # records of pasted reports and letters the extraction credited to the diarist
        # (attribution_check.py: Gemini and Claude agree)
        correction_flags += apply_observation_corrections(result.entries, load_observation_corrections(
            machine_cfg["attribution"], float(machine_cfg.get("min_correction_confidence", 0.9)),
            int(machine_cfg.get("min_agreement", 2))))[1]
    if corr_cfg.get("enabled", True) and corr_cfg.get("observations"):
        correction_flags += apply_observation_corrections(
            result.entries, load_observation_corrections(corr_cfg["observations"]))[1]

    qa_cfg = dict(config.get("qa", {}) or {})
    # Volume coverage: misfiled scans -> home volume, OCR years repaired against
    # the sequence neighbours, off-span entries flagged/excluded (needs the
    # model's entry kind, so it runs after extraction and before QA).
    cov_cfg = dict(qa_cfg.get("coverage") or {})
    coverage_flags: list = []
    if cov_cfg.get("enabled", True):
        from laubmann_kg.normalization.coverage import DEFAULT_PATH, VolumeCoverage, apply_coverage
        cov_path = Path(cov_cfg.get("path", DEFAULT_PATH))
        if cov_path.exists():
            before = len(result.entries)
            coverage = VolumeCoverage.load(cov_path)
            result.volume_spans = coverage.as_dict()
            result.entries, coverage_flags = apply_coverage(result.entries, coverage, cov_cfg)
            logger.info("coverage: %d flags, %d/%d entries excluded",
                        len(coverage_flags), before - len(result.entries), before)
            qa_cfg.setdefault("misdate", False)   # superseded by the coverage check
        else:
            logger.warning("volume coverage table not found at %s — skipped", cov_path)

    if qa_cfg.get("enabled", True):
        from laubmann_kg.qa import run_qa
        before = len(result.entries)
        kept, qa_flags = run_qa(result.entries, qa_cfg)
        result.entries = kept
        result.qa_flags = correction_flags + coverage_flags + qa_flags
        logger.info("QA: %d flags, %d/%d entries excluded", len(qa_flags),
                    before - len(kept), before)
    else:
        result.qa_flags = correction_flags + coverage_flags

    # One reading per shared node: every record of a vernacular name gets the
    # same Taxon, every use of a place name the same Place (before linking,
    # which enriches that single node; RDF and DwC-A then agree).
    from laubmann_kg.normalization.harmonize import harmonize
    logger.info("harmonize: %s", harmonize(result))

    # Places actually referenced by the surviving entries (entry places and
    # per-record localities); travel places are added by the RDF emitter.
    for entry in result.entries:
        if entry.place is not None:
            result.places.setdefault(entry.place.uid, entry.place)
        for obs in entry.observations:
            if obs.place is not None:
                result.places.setdefault(obs.place.uid, obs.place)

    # Links only QA-surviving entries (no API/LLM spend on excluded garbage);
    # one hook covers all export stages since each calls run_pipeline.
    linking_cfg = config.get("linking", {})
    if linking_cfg.get("enabled", False):
        from laubmann_kg.linking import run_linking   # lazy import
        logger.info("linking: %s", run_linking(result, linking_cfg))

    # Entity resolution: same-GBIF-key taxa, person name variants, place and
    # habitat spellings become one node (uses the linking evidence; writes
    # *_merges.csv review files; decisions feed back through reviewed_csv).
    resolution_cfg = config.get("resolution", {}) or {}
    if resolution_cfg.get("enabled", False):
        from laubmann_kg.resolution import run_resolution   # lazy import
        resolution_cfg.setdefault("review_dir", (linking_cfg or {}).get("review_dir", "data/review"))
        logger.info("resolution: %s", run_resolution(result, resolution_cfg))
        # observation places may have been re-pointed
        result.places = {}
        for entry in result.entries:
            if entry.place is not None:
                result.places.setdefault(entry.place.uid, entry.place)
            for obs in entry.observations:
                if obs.place is not None:
                    result.places.setdefault(obs.place.uid, obs.place)

    # Habitat linking (EUNIS classes) works on the resolved, canonical labels
    if (linking_cfg or {}).get("enabled", False) and (linking_cfg.get("habitats") or {}).get("enabled", False):
        from laubmann_kg.linking import run_habitat_linking
        logger.info("habitat linking: %s", run_habitat_linking(result, linking_cfg))

    if multimodal_path is not None:
        # every region goes to the entry it sits in (lkg:hasMultimodalRegion);
        # regions of entries that QA excluded are dropped with them, and so are the regions
        # the region check drops (another region of the entry shows the object better, blank
        # paper, fragments); the others carry their completeness and, where the box cut the
        # object off, the new crop (review/regions.py)
        from laubmann_kg.review.regions import load_region_decisions
        decisions = load_region_decisions(
            machine_cfg.get("regions") if machine_cfg.get("enabled", True) else None,
            review_cfg.get("regions"), min_agreement=int(machine_cfg.get("min_agreement", 2)))
        dropped = collections.Counter()
        by_uid = {e.entry_uid: e for e in result.entries}
        for record in read_multimodal(multimodal_path):
            entry = by_uid.get(record.get("entry_uid") or "")
            if entry is None:
                continue
            region = to_region(record, entry.volume)
            if region is None:
                continue
            decision = decisions.get(region.region_uid)
            if decision is not None and decision.drop:
                dropped[decision.reason or "dropped"] += 1
                continue
            if decision is not None:
                region.completeness = decision.completeness
                region.crop = decision.crop or region.crop
            entry.multimodal.append(region)
            result.multimodal.append(region)
        if dropped:
            logger.info("regions dropped by the region check: %s", dict(dropped))

    logger.info("pipeline: %d entries (%d empty, %d failed), %d observations, "
                "%d travel events, %d persons, %d places, %d media",
                len(result.entries), empty, failed, len(result.observations),
                sum(len(e.travel_events) for e in result.entries),
                sum(len(e.persons) for e in result.entries),
                len(result.places), len(result.multimodal))
    return result
