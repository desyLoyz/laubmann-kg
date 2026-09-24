"""Person linking against Wikidata (wbsearchentities + P31=Q5 verification).

Auto-accept is deliberately high-precision: the top search hit for a name is
often the wrong entity entirely ("Walter Wüst" -> a politician, not the
ornithologist), so a link is only applied for a unique exact-label match on a
multi-token name that is verifiably human — everything else goes to review.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from typing import Optional

from laubmann_kg.linking import http, review
from laubmann_kg.linking.cache import JsonCache

logger = logging.getLogger(__name__)

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY_NS = "http://www.wikidata.org/entity/"   # http, not https
GND_NS = "https://d-nb.info/gnd/"
PERSON_REVIEW_FIELDS = ["person_name", "person_uid", "n_entries", "qid",
    "wd_label", "wd_description", "rule", "gnd", "decision"]
_GND_RE = re.compile(r"(?:d-nb\.info/gnd/)?([0-9]+-[0-9X]|[0-9]{1,10}[0-9X])\b")


def gnd_id(value: str) -> Optional[str]:
    """GND identifier from an id or a d-nb.info URI ("118540238", "https://d-nb.info/gnd/1012345-6")."""
    m = _GND_RE.search((value or "").strip())
    return m.group(1) if m else None
_TITLE_RE = re.compile(
    r"^(dr|prof|frl|frau|herr|forstmeister|oberförster|förster|oberlehrer|"
    r"lehrer|pfarrer|freiherr|graf)\.?\s+", re.IGNORECASE)


class WikidataClient:
    def __init__(self, cache: JsonCache, offline: bool = False,
                 sleep_s: float = 0.5, language: str = "de") -> None:
        self.cache = cache
        self.offline = offline
        self.sleep_s = sleep_s
        self.language = language

    def search(self, name: str, language: Optional[str] = None) -> Optional[list[dict]]:
        lang = language or self.language
        key = f"search:{lang}:{name.lower()}"
        if key in self.cache:
            return self.cache.get(key)
        if self.offline:
            return None
        response = http.get_json(WIKIDATA_API_URL, {
            "action": "wbsearchentities", "search": name, "language": lang,
            "uselang": lang, "type": "item", "format": "json", "limit": 5})
        if not isinstance(response, dict) or "error" in response:
            # "error" on HTTP 200 (e.g. ratelimited) is a failure, not an
            # empty result -> never cached, retried next run
            return None
        hits = response.get("search") or []
        time.sleep(self.sleep_s)
        self.cache.put(key, hits)
        return hits

    def get_claims(self, qid: str) -> Optional[dict]:
        key = f"claims:{qid}"
        if key in self.cache:
            return self.cache.get(key)
        if self.offline:
            return None
        response = http.get_json(WIKIDATA_API_URL, {
            "action": "wbgetentities", "ids": qid, "props": "claims",
            "format": "json"})
        if not isinstance(response, dict) or "error" in response:
            return None
        claims = ((response.get("entities") or {}).get(qid) or {}).get("claims") or {}
        time.sleep(self.sleep_s)
        self.cache.put(key, claims)
        return claims


def is_human(claims: dict) -> bool:
    """True when any P31 mainsnak points at Q5 (human); tolerates missing keys."""
    for statement in (claims or {}).get("P31") or []:
        if not isinstance(statement, dict):
            continue
        value = ((statement.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict) and value.get("numeric-id") == 5:
            return True
    return False


def strip_titles(name: str) -> str:
    """Iteratively strip leading title tokens ("Dr.", "Förster", ...) for the
    SEARCH QUERY only — the diary name stays on the node."""
    out = " ".join((name or "").split())
    while True:
        stripped = _TITLE_RE.sub("", out).strip()
        if stripped == out:
            return out
        out = stripped


def _exact_label_hits(hits: list, query: str) -> list[dict]:
    q = query.casefold()
    return [h for h in hits if isinstance(h, dict)
            and ((h.get("label") or "").casefold() == q
                 or any((alias or "").casefold() == q
                        for alias in (h.get("aliases") or [])))]


def _needs_network(cache: JsonCache, language: str, query: str) -> bool:
    """True when processing ``query`` would fire an uncached request: the
    primary-language search, the en fallback after a cached-empty search, or
    the claims lookup for a unique cached exact-label candidate."""
    key = f"search:{language}:{query.lower()}"
    if key not in cache:
        return True
    hits = cache.get(key)
    if not hits and language != "en":
        en_key = f"search:en:{query.lower()}"
        if en_key not in cache:
            return True
        hits = cache.get(en_key)
    exact = _exact_label_hits(hits or [], query)
    if len(exact) == 1:  # claims are only ever fetched for a unique exact hit
        return f"claims:{exact[0].get('id') or ''}" not in cache
    return False


def _collect_persons(result) -> list[dict]:
    """Distinct persons by uid across entry.persons AND obs.observer, counting
    the entries each appears in. The diarist is NOT skipped — Alfred Laubmann
    is a notable ornithologist and legitimately linkable."""
    by_uid: dict[str, dict] = {}
    for entry in result.entries:
        mentions = list(entry.persons) + [obs.observer for obs in entry.observations
                                          if obs.observer is not None]
        seen_here: set[str] = set()
        for person in mentions:
            if person.uid in seen_here:
                continue
            seen_here.add(person.uid)
            info = by_uid.setdefault(person.uid, {
                "name": person.name, "uid": person.uid, "n_entries": 0})
            info["n_entries"] += 1
    return sorted(by_uid.values(), key=lambda i: (-i["n_entries"], i["name"]))


def link_persons(result, cfg: dict, cache: JsonCache, offline: bool) -> tuple[int, list[dict]]:
    cfg = cfg or {}
    limit = int(cfg.get("limit", 0) or 0)
    client = WikidataClient(cache, offline=offline,
                            sleep_s=float(cfg.get("sleep", 0.5)),
                            language=cfg.get("language", "de"))

    # accepted review rows: a Wikidata item and/or a GND identifier researched by the reviewer
    reviewed: dict[str, str] = {}
    gnd: dict[str, str] = {}
    if cfg.get("reviewed_csv"):
        for row in review.load_reviewed(cfg["reviewed_csv"]):
            name = (row.get("person_name") or "").strip()
            qid = (row.get("qid") or "").strip()
            g = gnd_id(row.get("gnd") or "")
            if name and qid:
                reviewed[name.lower()] = qid
            if name and g:
                gnd[name.lower()] = GND_NS + g

    rows: list[dict] = []
    # name.lower() -> wikidata IRI: same identity as Person.uid (casefold
    # would collapse ß/ss and stamp one QID onto two distinct people)
    links: dict[str, str] = {}
    uncached = 0
    for item in _collect_persons(result):
        try:
            base = {"person_name": item["name"], "person_uid": item["uid"],
                    "n_entries": item["n_entries"], "qid": "", "wd_label": "",
                    "wd_description": "", "rule": "", "gnd": "", "decision": ""}
            low = item["name"].lower()
            if low in gnd:
                base["gnd"] = gnd[low][len(GND_NS):]
            if low in reviewed:
                links[low] = WIKIDATA_ENTITY_NS + reviewed[low]
                rows.append({**base, "qid": reviewed[low], "rule": "reviewed"})
                continue
            if low in gnd:
                rows.append({**base, "rule": "reviewed"})
                continue
            query = strip_titles(item["name"])
            if len(query.split()) < 2:
                # bare surnames ("Kiel") never auto-link
                rows.append({**base, "rule": "single-token-name"})
                continue
            # limit caps UNCACHED work per run; skipped persons get no review
            # row and resume next run once earlier names are fully cached
            needs_lookup = _needs_network(cache, client.language, query)
            if limit and needs_lookup and uncached >= limit:
                continue
            if needs_lookup:
                uncached += 1
            hits = client.search(query)
            if hits is not None and not hits and client.language != "en":
                hits = client.search(query, language="en")
            if hits is None:
                rows.append({**base, "rule": "error"})
                continue
            if not hits:
                rows.append({**base, "rule": "no-match"})
                continue
            exact = _exact_label_hits(hits, query)
            if not exact:
                for hit in hits[:5]:
                    rows.append({**base, "qid": hit.get("id", ""),
                                 "wd_label": hit.get("label", ""),
                                 "wd_description": hit.get("description", ""),
                                 "rule": "no-exact-label"})
                continue
            if len(exact) > 1:
                for hit in exact[:5]:
                    rows.append({**base, "qid": hit.get("id", ""),
                                 "wd_label": hit.get("label", ""),
                                 "wd_description": hit.get("description", ""),
                                 "rule": "multiple-candidates"})
                continue
            hit = exact[0]
            qid = hit.get("id") or ""
            candidate = {**base, "qid": qid, "wd_label": hit.get("label", ""),
                         "wd_description": hit.get("description", "")}
            claims = client.get_claims(qid)
            if claims is None:
                rows.append({**candidate, "rule": "error"})
                continue
            if not is_human(claims):
                rows.append({**candidate, "rule": "not-human"})
                continue
            links[low] = WIKIDATA_ENTITY_NS + qid
            rows.append({**candidate, "rule": "linked"})
        except Exception as exc:  # noqa: BLE001 - linking must never abort the pipeline
            logger.warning("person linking failed for %r: %s", item.get("name"), exc)

    # collect-then-apply on EVERY occurrence (entry.persons and obs.observer):
    # a partial replacement would diverge at the idempotency-guarded emitter.
    for entry in result.entries:
        entry.persons = [
            replace(p, wikidata_iri=links.get(p.name.lower(), p.wikidata_iri),
                    gnd_iri=gnd.get(p.name.lower(), p.gnd_iri))
            for p in entry.persons]
        for obs in entry.observations:
            if obs.observer is not None:
                obs.observer = replace(
                    obs.observer,
                    wikidata_iri=links.get(obs.observer.name.lower(),
                                           obs.observer.wikidata_iri),
                    gnd_iri=gnd.get(obs.observer.name.lower(), obs.observer.gnd_iri))
    return len(links), rows
