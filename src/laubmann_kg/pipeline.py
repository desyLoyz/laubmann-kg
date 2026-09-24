"""Corpus → in-memory model pipeline shared by the extraction and export stages.

Loads the frozen corpus interface (entries.csv + multimodal), builds domain
objects, and runs extraction (LLM by default in production; the offline
rule-based backend is the network-free test double). Switching from the sample
to the deduped corpus is a path change in the config, not a code change.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from laubmann_kg.env import load_dotenv
from laubmann_kg.extraction.observations import extract_observations
from laubmann_kg.io.csv import read_entries
from laubmann_kg.io.metadata import read_multimodal
from laubmann_kg.kg.model import DiaryEntry, Place
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
        # the cleaned catalogue (multimodal_clean.md: duplicate pages and
        # degenerate crops/descriptions removed) wins over the raw one
        for name in ("multimodal_clean.md", "multimodal.md"):
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


def run_pipeline(config: dict, input_dir: Optional[Path] = None) -> ExtractionResult:
    load_dotenv()
    entries_csv, multimodal_path = _resolve_corpus(config, input_dir)
    sample = config.get("sample", {}) or {}
    volume = sample.get("volume")
    extract, provenance = _build_extractor(config)

    rows = read_entries(entries_csv, volume=int(volume) if volume is not None else None)
    rows = select_sample_rows(rows, sample)
    total = len(rows)
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

    result = ExtractionResult(provenance=provenance)

    # Sequential prep. The gazetteer/regex reading of the header is only the
    # FALLBACK place: the LLM extractor replaces it with the model's own reading
    # of the entry place (entry.place); the offline backend keeps it.
    jobs: list[tuple] = []
    for row in rows:
        entry = build_entry(row)
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
    correction_flags: list = []
    corr_cfg = config.get("corrections") or {}
    if corr_cfg.get("enabled", True) and corr_cfg.get("csv"):
        from laubmann_kg.normalization.corrections import apply_corrections, load_corrections
        _, correction_flags = apply_corrections(result.entries, load_corrections(corr_cfg["csv"]))

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
        entry_uids = {e.entry_uid for e in result.entries}
        result.multimodal = [r for r in read_multimodal(multimodal_path)
                             if r.get("entry_uid") in entry_uids]

    logger.info("pipeline: %d entries (%d empty, %d failed), %d observations, "
                "%d travel events, %d persons, %d places, %d media",
                len(result.entries), empty, failed, len(result.observations),
                sum(len(e.travel_events) for e in result.entries),
                sum(len(e.persons) for e in result.entries),
                len(result.places), len(result.multimodal))
    return result
