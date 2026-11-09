"""Mete los edificios del Catastro (INSPIRE, GML) en un extracto OSM (.osm.pbf).

Uso:
    python catastro_merge.py <entrada.osm.pbf> <salida.osm.pbf> <carpeta_catastro> [<carpeta_catastro> ...]

Cada carpeta es un zip A.ES.SDGC.BU.<código>.zip del Catastro ya descomprimido
(contiene *.building.gml y *.buildingpart.gml).

Qué hace:
- Lee las huellas de edificio del Catastro (EPSG:25830) y las pasa a WGS84.
- Plantas: el máximo de numberOfFloorsAboveGround de las partes de cada edificio.
- Uso (currentUse) y número de viviendas -> etiqueta building=* de OSM.
- Quita del extracto los edificios OSM que se solapan con uno del Catastro y
  escribe el resto tal cual, más los edificios del Catastro como ways nuevos.

Los edificios del Catastro llevan source=Catastro y ref:catastro=<referencia>.
Datos: © Dirección General del Catastro.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import osmium
from lxml import etree
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Polygon

NS = {
    "gml": "http://www.opengis.net/gml/3.2",
    "bu-ext2d": "http://inspire.jrc.ec.europa.eu/schemas/bu-ext2d/2.0",
    "bu-core2d": "http://inspire.jrc.ec.europa.eu/schemas/bu-core2d/2.0",
}
GML_ID = "{%s}id" % NS["gml"]
TO_WGS84 = Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)

# Ids nuevos, muy por encima de los de OSM, para no chocar y mantener el orden.
NODE_ID0 = 90_000_000_000
WAY_ID0 = 9_000_000_000


def _ref(gml_id: str) -> str:
    """ES.SDGC.BU.0033101VJ1103S_part1 -> 0033101VJ1103S"""
    return gml_id.rsplit(".", 1)[-1].split("_part")[0]


def _rings(elem) -> list[list[tuple[float, float]]]:
    """Anillos exteriores (coordenadas UTM) de la geometría de un elemento."""
    out = []
    for pos in elem.iterfind(".//gml:exterior//gml:posList", NS):
        vals = [float(v) for v in pos.text.split()]
        out.append(list(zip(vals[0::2], vals[1::2])))
    return out


def read_parts(path: Path) -> dict[str, int]:
    floors: dict[str, int] = defaultdict(int)
    for _, el in etree.iterparse(str(path), tag="{%s}BuildingPart" % NS["bu-ext2d"]):
        f = el.findtext("bu-ext2d:numberOfFloorsAboveGround", namespaces=NS)
        if f and f.strip().isdigit():
            ref = _ref(el.get(GML_ID))
            floors[ref] = max(floors[ref], int(f))
        el.clear()
    return floors


def tags_for(use: str, dwellings: int, levels: int) -> dict[str, str]:
    if use == "1_residential":
        if dwellings >= 3 or levels >= 4:
            kind = "apartments"
        elif dwellings == 0:
            kind = "residential"
        else:
            kind = "house"
    elif use == "2_agriculture":
        kind = "farm_auxiliary"
    elif use == "3_industrial":
        kind = "industrial"
    elif use == "4_1_office":
        kind = "office"
    elif use == "4_2_retail":
        kind = "retail"
    elif use == "4_3_publicServices":
        kind = "public"
    else:
        kind = "yes"
    return {"building": kind}


def read_buildings(folder: Path) -> list[dict]:
    bfile = next(folder.glob("*.building.gml"))
    pfile = next(folder.glob("*.buildingpart.gml"), None)
    floors = read_parts(pfile) if pfile else {}
    out = []
    for _, el in etree.iterparse(str(bfile), tag="{%s}Building" % NS["bu-ext2d"]):
        cond = el.findtext("bu-core2d:conditionOfConstruction", namespaces=NS) or ""
        if cond in ("ruin", "declined", "projected", "underConstruction"):
            el.clear()
            continue
        ref = _ref(el.get(GML_ID))
        use = (el.findtext("bu-ext2d:currentUse", namespaces=NS) or "").strip()
        dw = el.findtext("bu-ext2d:numberOfDwellings", namespaces=NS) or "0"
        dwellings = int(dw) if dw.strip().isdigit() else 0
        levels = floors.get(ref, 0)
        for ring in _rings(el):
            if len(ring) < 4:
                continue
            lon, lat = TO_WGS84.transform([p[0] for p in ring], [p[1] for p in ring])
            poly_utm = Polygon(ring)
            if not poly_utm.is_valid or poly_utm.area < 6:  # casetas de < 6 m²
                continue
            tags = tags_for(use, dwellings, levels)
            if levels:
                tags["building:levels"] = str(levels)
            tags["source"] = "Catastro"
            tags["ref:catastro"] = ref
            out.append({"lonlat": list(zip(lon, lat)), "tags": tags})
        el.clear()
    return out


def main() -> int:
    src, dst = sys.argv[1], sys.argv[2]
    folders = [Path(p) for p in sys.argv[3:]]
    cat = []
    for f in folders:
        b = read_buildings(f)
        print(f"{f.name}: {len(b)} edificios")
        cat += b
    polys = [Polygon(b["lonlat"]) for b in cat]
    tree = STRtree(polys)

    # 1) Qué edificios OSM se solapan con el Catastro (hace falta su geometría).
    drop_ways: set[int] = set()
    fp = osmium.FileProcessor(src, osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for w in fp:
        if not w.is_way() or "building" not in w.tags:
            continue
        try:
            pts = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            continue
        if len(pts) < 4:
            continue
        p = Polygon(pts)
        if not p.is_valid:
            p = p.buffer(0)
        hits = tree.query(p, predicate="intersects")
        if len(hits):
            drop_ways.add(w.id)
    print(f"edificios OSM sustituidos: {len(drop_ways)}")

    # 2) Escribir: nodos OSM + nodos nuevos, ways OSM (menos los quitados) +
    #    ways nuevos, relaciones OSM. Así el fichero sigue ordenado por tipo.
    Path(dst).unlink(missing_ok=True)
    with osmium.SimpleWriter(dst) as wr:
        for n in osmium.FileProcessor(src, osmium.osm.NODE):
            wr.add_node(n)
        nid = NODE_ID0
        way_nodes = []
        for b in cat:
            ids = []
            for lon, lat in b["lonlat"][:-1]:  # el último repite el primero
                wr.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat)))
                ids.append(nid)
                nid += 1
            way_nodes.append(ids + [ids[0]])
        for w in osmium.FileProcessor(src, osmium.osm.WAY):
            if w.id not in drop_ways:
                wr.add_way(w)
        for i, (b, ids) in enumerate(zip(cat, way_nodes)):
            wr.add_way(osmium.osm.mutable.Way(id=WAY_ID0 + i, nodes=ids, tags=b["tags"]))
        for r in osmium.FileProcessor(src, osmium.osm.RELATION):
            if "building" in r.tags and any(m.type == "w" and m.ref in drop_ways for m in r.members):
                continue
            wr.add_relation(r)
    print(f"escrito {dst}: {len(cat)} edificios del Catastro")
    return 0


if __name__ == "__main__":
    sys.exit(main())
