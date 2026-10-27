"""Generate the human-readable ontology documentation with pyLODE.

    python tools/build_ontology_docs.py            # -> docs/ontology/{index,vocabularies,shapes}.html

pyLODE concatenates every language variant of a label into one heading, so the
pages are rendered from an English-label view of the graphs (German labels and
definitions remain in the Turtle sources). Also writes docs/ontology/data.html,
the landing page the w3id .htaccess sends instance IRIs to.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDFS, SKOS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "ontology"
PYLODE = Path(sys.executable).with_name("pylode.exe" if sys.platform == "win32" else "pylode")
LABEL_PREDS = {RDFS.label, DCTERMS.title, SKOS.prefLabel, SKOS.altLabel}


def english_view(src: Path) -> Path:
    g = Graph()
    g.parse(str(src), format="turtle")
    drop = [(s, p, o) for s, p, o in g if p in LABEL_PREDS and isinstance(o, Literal) and o.language and o.language != "en"]
    for t in drop:
        g.remove(t)
    fd, name = tempfile.mkstemp(suffix=".ttl", prefix=src.stem + "_en_"); os.close(fd)
    tmp = Path(name)
    g.serialize(destination=str(tmp), format="turtle")
    return tmp


def run_pylode(src: Path, out: Path, profile: str) -> None:
    tmp = english_view(src)
    try:
        subprocess.run([str(PYLODE), str(tmp), "-o", str(out), "-c", "true", "-s", "true", "-p", profile], check=True)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"{profile:8s} {src.name} -> {out.relative_to(ROOT)} ({out.stat().st_size/1024:.0f} KB)")


def write_vocabularies(src: Path, out: Path) -> None:
    """One table per skos:ConceptScheme (pyLODE's vocpub profile expects a single scheme)."""
    import html
    g = Graph(); g.parse(str(src), format="turtle")
    LKG = "https://w3id.org/laubmann-kg/ontology#"
    def lit(subj, pred, lang):
        for o in g.objects(subj, pred):
            if isinstance(o, Literal) and (o.language or "en") == lang:
                return str(o)
        return ""
    schemes = sorted(g.subjects(URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"), SKOS.ConceptScheme), key=lambda u: lit(u, SKOS.prefLabel, "en"))
    esc = html.escape
    parts = ["""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Laubmann KG · controlled vocabularies</title>
<style>body{font:15px/1.5 "Segoe UI",system-ui,sans-serif;max-width:960px;margin:4vh auto;padding:0 1.2rem;color:#1D2A21}
h1{font:500 1.9rem/1.2 Georgia,serif;margin:0 0 .3rem}h2{font:500 1.15rem/1.3 Georgia,serif;margin:2rem 0 .3rem;padding-top:.8rem;border-top:1px solid #DCE2DA}
p.meta{color:#5F6E64;font-size:.9rem}code{background:#EEF2EC;padding:1px 5px;border-radius:3px;font-size:.88em}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;padding:4px 8px;border-bottom:1px solid #EEF1EC;vertical-align:top}
th{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#5F6E64}nav{font-size:.86rem;color:#5F6E64;margin-bottom:1rem}nav a{color:#35608A;text-decoration:none;margin-right:10px}</style></head><body>
<h1>Laubmann Knowledge Graph — controlled vocabularies</h1>
<p class="meta">SKOS concept schemes in <code>https://w3id.org/laubmann-kg/ontology#</code>. The English <code>skos:prefLabel</code> is the literal value emitted in the data graph and checked by the SHACL shapes; the Python mirror is <code>normalization/vocabularies.py</code>. Source: <code>ontologies/controlled_vocabularies.ttl</code>. See also the <a href="index.html">ontology</a> and the <a href="shapes.html">SHACL shapes</a>.</p>
<nav>""" + "".join(f'<a href="#{esc(str(sc).replace(LKG, ""))}">{esc(lit(sc, SKOS.prefLabel, "en"))}</a>' for sc in schemes) + "</nav>"]
    for sc in schemes:
        local = str(sc).replace(LKG, "")
        concepts = sorted(g.subjects(SKOS.inScheme, sc), key=lambda u: str(u))
        defn = lit(sc, SKOS.definition, "en") or lit(sc, RDFS.comment, "en")
        parts.append(f'<h2 id="{esc(local)}">{esc(lit(sc, SKOS.prefLabel, "en"))} <span style="color:#5F6E64;font-size:.85rem">· {esc(lit(sc, SKOS.prefLabel, "de"))} · <code>lkg:{esc(local)}</code></span></h2>')
        if defn: parts.append(f'<p class="meta">{esc(defn)}</p>')
        if concepts:
            parts.append("<table><tr><th>concept</th><th>value (en, emitted)</th><th>de</th><th>definition</th></tr>")
            for c in concepts:
                parts.append(f"<tr><td><code>lkg:{esc(str(c).replace(LKG, ''))}</code></td><td>{esc(lit(c, SKOS.prefLabel, 'en'))}</td><td>{esc(lit(c, SKOS.prefLabel, 'de'))}</td><td>{esc(lit(c, SKOS.definition, 'en') or lit(c, RDFS.comment, 'en'))}</td></tr>")
            parts.append("</table>")
        else:
            parts.append('<p class="meta">Open scheme — concepts are minted in the data (no fixed list).</p>')
    parts.append("</body></html>")
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"vocab    {src.name} -> {out.relative_to(ROOT)} ({out.stat().st_size/1024:.0f} KB, {len(schemes)} schemes)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    onto = ROOT / "ontologies"
    run_pylode(onto / "laubmann.ttl", OUT / "index.html", "ontpub")
    write_vocabularies(onto / "controlled_vocabularies.ttl", OUT / "vocabularies.html")
    run_pylode(onto / "shacl_shapes.ttl", OUT / "shapes.html", "valpub")
    g = Graph(); g.parse(str(onto / "laubmann.ttl"), format="turtle")
    version = str(g.value(URIRef("https://w3id.org/laubmann-kg/ontology"), OWL.versionInfo) or "")
    (OUT / "data.html").write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Laubmann KG · data</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:60ch;margin:6vh auto;padding:0 1rem;color:#1D2A21}}code{{background:#EEF2EC;padding:1px 5px;border-radius:3px}}a{{color:#35608A}}</style></head>
<body><h1>Laubmann Knowledge Graph — data</h1>
<p>You followed an instance IRI under <code>https://w3id.org/laubmann-kg/data/</code>. The graph is not yet served
through a public SPARQL endpoint; the full exports (Turtle, JSON-LD, Darwin Core Archive) are published as releases of the
<a href="https://github.com/desyLoyz/laubmann-kg">laubmann-kg repository</a>. Vocabulary: <a href="index.html">ontology {version}</a> ·
<a href="vocabularies.html">controlled vocabularies</a> · <a href="shapes.html">SHACL shapes</a>.</p>
<p id="iri"></p><script>var p=document.getElementById('iri'),c=document.createElement('code');if(location.hash)p.append('Requested IRI: ',c),c.textContent='https://w3id.org/laubmann-kg/data/'+location.hash.slice(1);</script>
</body></html>""", encoding="utf-8")
    print("data.html written")


if __name__ == "__main__":
    main()
