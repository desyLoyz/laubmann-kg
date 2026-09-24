"""Parse an export's Turtle file once into triples.pkl (rdflib; ~75 s for the full graph).

    python tools/validation_ui/load.py <export>/rdf/laubmann_sample.ttl [triples.pkl]
"""
import pickle
import sys
import time

import rdflib

ttl = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "triples.pkl"
t = time.time()
g = rdflib.Graph()
g.parse(ttl, format="turtle")
print(len(g), "triples in", round(time.time() - t), "s")
pickle.dump(list(g), open(out, "wb"))
