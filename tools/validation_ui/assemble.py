"""Inline Leaflet, the Drive page-image map and the payload into one standalone HTML page.

    python tools/validation_ui/assemble.py payload.b64 HistOrniGraph_Validierung.html
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
payload, out = sys.argv[1], sys.argv[2]
d = json.loads((HERE / "drive_pages.json").read_text())
# vol. 01 scan 0031 exists on Drive only as an unsplit _full page
full = "900847d2-aabe-4b16-b0e6-203b103bd1e1_0031_full"
for s in ("_L", "_R"):
    d.setdefault(full.replace("_full", s), d.get(full))
t = (HERE / "template.html").read_text()
html = (t.replace("/*LEAFLET_CSS*/", (HERE / "leaflet.css").read_text())
         .replace("__DRIVE__", json.dumps(d, separators=(",", ":")))
         .replace("/*LEAFLET_JS*/", (HERE / "leaflet.js").read_text())
         .replace("/*APP_JS*/", (HERE / "app.js").read_text())
         .replace("__PAYLOAD__", Path(payload).read_text()))
Path(out).write_text(html)
print(f"{out}: {len(html) / 1e6:.1f} MB")
