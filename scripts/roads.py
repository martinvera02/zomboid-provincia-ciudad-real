"""Red de carreteras reales entre los pueblos, a partir del extracto OSM.

Uso: python roads.py <zona.osm.pbf> <salida.json>

Construye un grafo con las carreteras interurbanas (autovías, nacionales,
autonómicas y provinciales), calcula el camino más corto entre cada par de
pueblos y se queda con los enlaces "directos": los que no atraviesan el núcleo
de un tercer pueblo. Para cada enlace guarda la geometría (lon/lat), la
longitud y la carretera principal (ref) que sigue.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import networkx as nx
import osmium

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cr import PUEBLOS  # noqa: E402

KEEP = {"motorway", "trunk", "primary", "secondary", "tertiary",
        "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
        "unclassified", "residential"}
# Penalización para preferir carreteras principales, como haría un conductor.
COST = {"motorway": 0.8, "trunk": 0.85, "primary": 0.9, "secondary": 1.0, "tertiary": 1.1,
        "unclassified": 1.4, "residential": 1.6}


def hav(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def inside(p, box, pad=0.0):
    s, w, n, e = box
    return s - pad <= p[1] <= n + pad and w - pad <= p[0] <= e + pad


def main():
    src, dst = sys.argv[1], sys.argv[2]
    g = nx.Graph()
    coords = {}
    fp = osmium.FileProcessor(src, osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for w in fp:
        if not w.is_way():
            continue
        hw = w.tags.get("highway")
        if hw not in KEEP:
            continue
        base = hw.replace("_link", "")
        ref = w.tags.get("ref", "")
        try:
            pts = [(n.ref, (n.lon, n.lat)) for n in w.nodes]
        except osmium.InvalidLocationError:
            continue
        for (a, pa), (b, pb) in zip(pts, pts[1:]):
            coords[a], coords[b] = pa, pb
            d = hav(pa, pb)
            g.add_edge(a, b, length=d, cost=d * COST.get(base, 1.5), ref=ref, hw=base)
    big = max(nx.connected_components(g), key=len)
    g = g.subgraph(big).copy()
    print(f"grafo: {g.number_of_nodes()} nodos, {g.number_of_edges()} tramos")

    # Nodo de cada pueblo: el de la red principal más cercano al centro de su caja.
    main_nodes = [n for n in g.nodes if any(g.edges[n, m]["hw"] in ("motorway", "trunk", "primary",
                                                                    "secondary", "tertiary")
                                            for m in g.neighbors(n))]
    centre = {}
    for name, (s, w, n, e) in PUEBLOS.items():
        c = ((w + e) / 2, (s + n) / 2)
        centre[name] = min(main_nodes, key=lambda k: hav(coords[k], c))

    names = list(PUEBLOS)
    links = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            try:
                path = nx.shortest_path(g, centre[a], centre[b], weight="cost")
            except nx.NetworkXNoPath:
                continue
            pts = [coords[k] for k in path]
            # ¿Atraviesa el núcleo de un tercer pueblo? Entonces no es enlace directo.
            others = [o for o in names if o not in (a, b)]
            if any(sum(inside(p, PUEBLOS[o]) for p in pts) > 3 for o in others):
                continue
            length = sum(g.edges[u, v]["length"] for u, v in zip(path, path[1:]))
            refs = Counter()
            for u, v in zip(path, path[1:]):
                e = g.edges[u, v]
                if e["ref"]:
                    refs[e["ref"]] += e["length"]
            # Tramo fuera de las dos cajas: lo que de verdad hay que enlazar.
            out = [p for p in pts if not inside(p, PUEBLOS[a]) and not inside(p, PUEBLOS[b])]
            links.append({"a": a, "b": b, "km": round(length / 1000, 1),
                          "ref": refs.most_common(1)[0][0] if refs else "",
                          "outside_km": round(sum(hav(p, q) for p, q in zip(out, out[1:])) / 1000, 1),
                          "points": pts})
    # Quitar enlaces redundantes: de más largo a más corto, uno a uno, si con
    # los que quedan se llega por otro lado sin alargar más de un 25 %. Así
    # nunca se quitan dos que se cubren el uno al otro y nadie queda aislado.
    gl = nx.Graph()
    for l in links:
        gl.add_edge(l["a"], l["b"], km=l["km"])
    keep = []
    for l in sorted(links, key=lambda l: -l["km"]):
        gl.remove_edge(l["a"], l["b"])
        try:
            alt = nx.shortest_path_length(gl, l["a"], l["b"], weight="km")
        except nx.NetworkXNoPath:
            alt = math.inf
        if alt > l["km"] * 1.25:
            gl.add_edge(l["a"], l["b"], km=l["km"])
            keep.append(l)
    keep.sort(key=lambda l: l["km"])
    for l in keep:
        print(f"{l['a']:20s} - {l['b']:20s} {l['km']:5.1f} km  {l['ref']}")
    Path(dst).write_text(json.dumps({"links": keep}, ensure_ascii=False))


if __name__ == "__main__":
    main()
