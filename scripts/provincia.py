"""Monta la provincia: pueblos con el norte arriba, colocados según el plano,
y carreteras de enlace entre ellos.

Uso (Windows, desde la carpeta de KnoxMap):
    .venv\\Scripts\\python.exe provincia.py . zona_ciudad_real_osm_catastro.osm.pbf layout.json ^
        --pueblos CiudadReal,Poblete --enlaces CiudadReal-Poblete

    --pueblos   pueblos a generar y colocar (nombres de build_cr.PUEBLOS, o "todos")
    --enlaces   enlaces a construir, "A-B" separados por comas, o "todos"
                (tienen que estar en layout.json; sus dos pueblos ya colocados)
    --solo-colocar   no regenera los pueblos, solo los coloca

layout.json sale de layout.py: la celda de cada pueblo y los puntos de cada
enlace en tiles del mundo. Cada enlace se construye como un mapa propio,
"Enlace_<A>_<B>", en las celdas libres entre los dos pueblos, con la misma
escala que ellos para que la carretera tenga el mismo ancho que sus calles.

Después, en la ventana de KnoxMap: Compile e Install de cada mapa (pueblos y
enlaces). No pulses Generate ni muevas los mapas desde la ventana.
"""
from __future__ import annotations

import argparse
import math
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_cr import PUEBLOS  # noqa: E402

# Igual que build_cr, más el norte arriba: sin girar el mapa para alinear calles,
# así las carreteras salen de cada pueblo en su dirección real.
TOWN_SETTINGS = {"true_map": 0, "fill_frontage": 0, "align_streets": 0, "rotate_degrees": 0}
# Lo que usa la ventana de KnoxMap para un enlace.
LINK_SETTINGS = {"preset": "rural", "align_streets": 0, "rotate_degrees": 0, "straight_roads": 0}
# Clase de carretera (road_hierarchy.bmp de KnoxMap) -> tipo de carretera del enlace.
KIND_BY_CLASS = {8: "motorway", 7: "primary", 6: "primary", 5: "secondary",
                 4: "secondary", 3: "residential"}
CELL = 300
STUB = 40          # tiles rectos al salir del borde, para que siga a la calle del pueblo


BAND = 40          # tiles: una calle que acaba a menos de esto del borde cuenta como salida


def edge_roads(knox: str, name: str, cell: tuple[int, int], edge: str):
    """Carreteras que llegan a un borde del mapa de un pueblo: [(x, y, clase,
    hueco)] en tiles del mundo, el centro de cada una sobre el borde y cuántos
    tiles se queda antes de él. Se leen del mapa ya generado, así que salen
    donde KnoxMap las ha dejado de verdad (después de enderezarlas)."""
    import numpy as np
    from PIL import Image
    img = np.array(Image.open(os.path.join(knox, "output", name, f"{name}_road_hierarchy.bmp")))
    h, w = img.shape[:2]
    # Franja junto al borde, con el borde en la fila 0.
    band = {"left": img[:, :BAND].T, "right": img[:, ::-1][:, :BAND].T,
            "top": img[:BAND, :], "bottom": img[::-1, :][:BAND, :]}[edge]
    best = band.max(axis=0)                       # clase máxima en la franja
    hit = band >= 3
    gap = np.where(hit.any(axis=0), hit.argmax(axis=0), BAND)
    out, run = [], None
    for i, v in enumerate(list(best) + [0]):
        v = int(v)
        if v >= 3:
            if run is None:
                run = [i, i, v, int(gap[i])]
            else:
                run[1], run[2], run[3] = i, max(run[2], v), min(run[3], int(gap[i]))
        elif run is not None:
            mid = (run[0] + run[1]) / 2
            if edge in ("left", "right"):
                x = cell[0] * CELL + (0 if edge == "left" else w)
                out.append((x, cell[1] * CELL + mid, run[2], run[3]))
            else:
                y = cell[1] * CELL + (0 if edge == "top" else h)
                out.append((cell[0] * CELL + mid, y, run[2], run[3]))
            run = None
    return out


def crossing(box, p, q):
    """Dónde corta el segmento p->q (de dentro a fuera) el borde de la caja."""
    x0, y0, x1, y1 = box
    best = None
    for edge, t in (("left", (x0 - p[0]) / (q[0] - p[0]) if q[0] != p[0] else None),
                    ("right", (x1 - p[0]) / (q[0] - p[0]) if q[0] != p[0] else None),
                    ("top", (y0 - p[1]) / (q[1] - p[1]) if q[1] != p[1] else None),
                    ("bottom", (y1 - p[1]) / (q[1] - p[1]) if q[1] != p[1] else None)):
        if t is None or not 0 <= t <= 1:
            continue
        x, y = p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])
        if x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1 and (best is None or t < best[0]):
            best = (t, edge, (x, y))
    return best


def _seg_hits(p, q, box, steps=40):
    """¿El segmento p->q pasa por dentro de la caja (sin contar el borde)?"""
    for i in range(1, steps):
        t = i / steps
        x, y = p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])
        if box[0] < x < box[2] and box[1] < y < box[3]:
            return True
    return False


def snap_link(knox, layout, a, b, points, obstacles=(), only_b=None, allow_blocked=False):
    """Ajusta un enlace para que empiece y acabe justo en una carretera que
    cruce el borde de cada pueblo. Se miran los cuatro bordes; valen los que
    miran hacia el otro pueblo, y se prefieren las carreteras grandes, de clase
    parecida, cerca de por donde sale la real y con la unión más corta.
    `obstacles` son otras cajas (tiles) que la carretera no puede atravesar.
    Devuelve (puntos, tipo de carretera, notas)."""
    def tbox(n):
        t = layout["towns"][n]
        return (t["cell_x"] * CELL, t["cell_y"] * CELL,
                (t["cell_x"] + t["cells"][0]) * CELL, (t["cell_y"] + t["cells"][1]) * CELL)

    def inside(pt, box):
        return box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]

    normals = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}
    ba, bb = tbox(a), tbox(b)
    centre = {a: ((ba[0] + ba[2]) / 2, (ba[1] + ba[3]) / 2), b: ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)}
    walls = [ba, bb, *obstacles]

    sides = []
    for town, other, pts in ((a, b, points), (b, a, points[::-1])):
        box = tbox(town)
        k = next((i for i, pt in enumerate(pts) if not inside(pt, box)), None)
        want, real_edge = (pts[0], None)
        if k:
            _, real_edge, want = crossing(box, pts[k - 1], pts[k])
        cands = []
        if town == b and only_b is not None:
            sides.append((only_b[0][3], only_b[0][:2], list(only_b)))
            continue
        for edge, (nx, ny) in normals.items():
            for x, y, cls, gap in edge_roads(knox, town, (layout["towns"][town]["cell_x"],
                                                          layout["towns"][town]["cell_y"]), edge):
                ox, oy = centre[other][0] - x, centre[other][1] - y
                if nx * ox + ny * oy <= 0:           # este borde da la espalda al otro pueblo
                    continue
                cands.append((x, y, cls, edge, gap))
        if not cands:
            raise RuntimeError(f"{town} no tiene ninguna carretera en los bordes que miran a {other}")
        sides.append((real_edge, want, cands))

    def stubs(c):
        n = normals[c[3]]
        return (c[0] + STUB * n[0], c[1] + STUB * n[1])

    def blocked(ca, cb):
        if allow_blocked:
            return False
        sa, sb = stubs(ca), stubs(cb)
        return any(_seg_hits(sa, sb, w) for w in walls)

    def score(ca, cb):
        return (0.5 * math.dist(ca[:2], sides[0][1]) + 0.5 * math.dist(cb[:2], sides[1][1])
                + math.dist(ca[:2], cb[:2])
                - 200 * (ca[2] + cb[2]) + 200 * abs(ca[2] - cb[2])
                + 300 * (ca[3] != sides[0][0]) + 300 * (cb[3] != sides[1][0])
                + 10 * (ca[4] + cb[4])
                # Enlaces compactos: cada celda de campo que ocupa es sitio que
                # luego no tienen los demás.
                + 150 * (abs(ca[0] - cb[0]) // CELL + 1) * (abs(ca[1] - cb[1]) // CELL + 1))

    pairs = [(ca, cb) for ca in sides[0][2] for cb in sides[1][2] if not blocked(ca, cb)]
    if not pairs:
        raise RuntimeError("no hay ninguna pareja de salidas que se pueda unir sin pisar otro mapa")
    for pick in sorted(pairs, key=lambda p: score(*p))[:8]:
        yield _solution(a, b, pick, sides, points, ba, bb, walls, stubs, inside)


def _solution(a, b, pick, sides, points, ba, bb, walls, stubs, inside):
    ends = []
    for (real_edge, want, _), (x, y, cls, edge, gap) in zip(sides, pick):
        ends.append({"pt": (x, y), "stub": stubs((x, y, cls, edge)), "cls": cls, "edge": edge,
                     "gap": gap,
                     "moved": round(math.dist((x, y), want)), "same": edge == real_edge})

    # Por dentro: la forma de la carretera real entre las dos salidas reales,
    # desplazada poco a poco para que empiece y acabe en las salidas elegidas
    # (el desplazamiento de cada extremo se reparte a lo largo del camino).
    # Si las salidas no son por los bordes de la real, o esa forma pisa otro
    # mapa, la carretera va directa de una salida a otra.
    middle = []
    if ends[0]["same"] and ends[1]["same"]:
        wa, wb = sides[0][1], sides[1][1]
        da = (ends[0]["pt"][0] - wa[0], ends[0]["pt"][1] - wa[1])
        db = (ends[1]["pt"][0] - wb[0], ends[1]["pt"][1] - wb[1])
        mid = [wa, *[p for p in points if not inside(p, ba) and not inside(p, bb)], wb]
        cum = [0.0]
        for p, q in zip(mid, mid[1:]):
            cum.append(cum[-1] + math.dist(p, q))
        total = cum[-1] or 1.0
        moved = [(p[0] + (1 - c / total) * da[0] + (c / total) * db[0],
                  p[1] + (1 - c / total) * da[1] + (c / total) * db[1]) for p, c in zip(mid, cum)]
        middle = [p for p in moved[1:-1]
                  if math.dist(p, ends[0]["pt"]) > 3 * STUB and math.dist(p, ends[1]["pt"]) > 3 * STUB
                  and not inside(p, ba) and not inside(p, bb)]
        line = [ends[0]["stub"], *middle, ends[1]["stub"]]
        if any(_seg_hits(p, q, w) for p, q in zip(line, line[1:]) for w in walls):
            middle = []
    pts = [ends[0]["pt"], ends[0]["stub"], *middle, ends[1]["stub"], ends[1]["pt"]]
    kind = KIND_BY_CLASS.get(min(ends[0]["cls"], ends[1]["cls"]), "secondary")
    notes = (f"sale de {a} por {ends[0]['edge']} (clase {ends[0]['cls']}, a {ends[0]['moved']} tiles "
             f"de la real), llega a {b} por {ends[1]['edge']} (clase {ends[1]['cls']}, "
             f"a {ends[1]['moved']} tiles), {'forma real' if middle else 'directa'}"
             + (f"; tramo sin asfaltar hasta el borde: {ends[0]['gap']} y {ends[1]['gap']} tiles"
                if ends[0]['gap'] or ends[1]['gap'] else ""))
    return [[round(x), round(y)] for x, y in pts], kind, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("knox")
    ap.add_argument("pbf")
    ap.add_argument("layout")
    ap.add_argument("--pueblos", default="")
    ap.add_argument("--enlaces", default="")
    ap.add_argument("--solo-colocar", action="store_true")
    ap.add_argument("--cruces", default="",
                    help='pueblo>enlace, p. ej. "CanadaDeCalatrava>CiudadReal-Almagro", separados por comas')
    args = ap.parse_args()

    knox = os.path.abspath(args.knox)
    pbf = os.path.abspath(args.pbf)
    layout = json.loads(open(args.layout, encoding="utf-8").read())

    towns = list(PUEBLOS) if args.pueblos == "todos" else [t for t in args.pueblos.split(",") if t]
    if args.enlaces == "todos":
        # Primero los que hacen falta para que todo quede conectado (árbol de
        # carreteras más cortas), después los que solo añaden atajos: así los
        # imprescindibles cogen sitio antes.
        group = {t: t for t in layout["towns"]}

        def root(t):
            while group[t] != t:
                t = group[t]
            return t
        tree, extra = [], []
        for l in sorted(layout["links"], key=lambda l: l["real_km"]):
            ra, rb = root(l["a"]), root(l["b"])
            (tree if ra != rb else extra).append((l["a"], l["b"]))
            group[ra] = rb
        links = tree + extra
    else:
        links = [tuple(x.split("-")) for x in args.enlaces.split(",") if x]
    for t in towns:
        if t not in PUEBLOS or t not in layout["towns"]:
            sys.exit(f"Pueblo desconocido: {t}")
    by_pair = {(l["a"], l["b"]): l for l in layout["links"]}
    by_pair.update({(l["b"], l["a"]): {**l, "a": l["b"], "b": l["a"],
                                       "points": l["points"][::-1]} for l in layout["links"]})
    for a, b in links:
        if (a, b) not in by_pair:
            sys.exit(f"El enlace {a}-{b} no está en {args.layout}")
    cruces = []
    for item in [c for c in args.cruces.split(",") if c]:
        town, link = item.split(">")
        la, lb = link.split("-")
        if town not in layout["towns"]:
            sys.exit(f"Pueblo desconocido en --cruces: {town}")
        cruces.append((town, la, lb))

    os.environ["KNOXMAP_OSM_SOURCE"] = "extract"
    sys.path.insert(0, knox)
    os.chdir(knox)

    from generator import extract
    region = {"id": "ciudad-real", "name": "Ciudad Real (BBBike)", "url": "local"}
    extract._index = lambda refresh_ok=True: {"features": []}
    extract.regions_for = lambda *a, **k: [region]
    extract._download = lambda region, say, should_stop: pbf

    from knoxbuild import placement as P
    import app as knoxapp

    # Al trazar un enlace, KnoxMap solo aparta la carretera de los mapas ya
    # instalados y del mapa del que sale. Aquí los pueblos aún no están
    # instalados, así que se le cuentan todos los del plano (en celdas de 256
    # tiles, que es como los cuenta: x * 256 da el tile exacto).
    real_world_maps = P.world_maps

    # Las versiones ya instaladas de los pueblos del plano y de los enlaces que
    # se van a rehacer no cuentan: se van a sustituir, no son otros mapas.
    replaced = set(layout["towns"]) | {f"Enlace_{a}_{b}" for a, b in links} \
        | {f"Enlace_{b}_{a}" for a, b in links} \
        | {f"Cruce_{t}_{la}_{lb}" for t, la, lb in cruces}
    # Enlaces que se rehacen con un ramal: su versión instalada tampoco cuenta,
    # pero su versión generada sí (es el mapa al que se engancha el cruce).
    rebuilt = {f"Enlace_{la}_{lb}" for _, la, lb in cruces} | {f"Enlace_{lb}_{la}" for _, la, lb in cruces}

    # Enlaces ya construidos (en esta tanda o en otra anterior, instalados o no):
    # dos mapas no pueden compartir celda, así que cada enlace nuevo los esquiva.
    link_boxes = {}
    out_dir = os.path.join(knox, "output")
    for entry in os.listdir(out_dir) if os.path.isdir(out_dir) else []:
        if not entry.startswith(("Enlace_", "Cruce_")) or entry in replaced:
            continue
        try:
            pl = json.load(open(os.path.join(out_dir, entry, "placement.json"), encoding="utf-8"))
            inf = json.load(open(os.path.join(out_dir, entry, f"{entry}_info.json"), encoding="utf-8"))
            link_boxes[entry] = (pl["cell_x"], pl["cell_y"], inf["cells_x"], inf["cells_y"])
        except (OSError, ValueError, KeyError):
            pass

    def world_maps(own_mod=None):
        out = [m for m in real_world_maps(own_mod) if m.get("kind") != "installed"
               or (m.get("name") not in replaced and m.get("name") not in rebuilt
                   and m.get("name") not in link_boxes)]
        boxes = [(n, t["cell_x"], t["cell_y"], *t["cells"]) for n, t in layout["towns"].items()]
        boxes += [(n, *b) for n, b in link_boxes.items()]
        for name, x, y, w, h in boxes:
            out.append({"name": name, "kind": "plan",
                        "x": x * 300 / 256, "y": y * 300 / 256,
                        "w": w * 300 / 256, "h": h * 300 / 256})
        return out

    P.world_maps = world_maps

    client = knoxapp.app.test_client()
    ok = {}

    def call(method, url, **kw):
        r = getattr(client, method)(url, **kw)
        body = r.get_json(silent=True) or {}
        if r.status_code != 200:
            raise RuntimeError(f"{url} -> {r.status_code}: {body.get('error', body)}")
        return body

    def place(name, x, y):
        body = call("post", f"/api/placement/{name}", json={"cell_x": x, "cell_y": y})
        return body

    for name in towns:
        print(f"\n=== {name} ===", flush=True)
        t = layout["towns"][name]
        try:
            if not args.solo_colocar:
                s, w, n, e = PUEBLOS[name]
                # KnoxMap guarda lo que leyó del .pbf junto al mapa y lo reusa
                # al regenerar: con un .pbf nuevo hay que tirarlo o no se nota.
                cache = os.path.join(knox, "output", name, f"{name}_osm.json.gz")
                if os.path.exists(cache) and os.path.getmtime(cache) < os.path.getmtime(pbf):
                    os.remove(cache)
                    print("  (datos de OSM guardados más viejos que el .pbf: se vuelven a leer)")
                t0 = time.time()
                body = call("post", "/api/generate", json={
                    "south": s, "west": w, "north": n, "east": e,
                    "metersPerTile": layout["meters_per_tile"], "mapName": name,
                    "settings": TOWN_SETTINGS})
                size = (body.get("cellsX"), body.get("cellsY"))
                print(f"generate ok en {time.time() - t0:.0f}s: {size[0]} x {size[1]} celdas", flush=True)
                if list(size) != t["cells"]:
                    raise RuntimeError(f"mide {size} y el plano esperaba {t['cells']}: "
                                       "vuelve a calcular layout.json")
                t0 = time.time()
                call("post", "/api/buildings", json={"mapName": name})
                print(f"buildings ok en {time.time() - t0:.0f}s", flush=True)
            place(name, t["cell_x"], t["cell_y"])
            print(f"colocado en la celda {t['cell_x']},{t['cell_y']}", flush=True)
            ok[name] = True
        except Exception as exc:  # noqa: BLE001 - se informa y se sigue
            print(f"FALLO: {exc}")
            ok[name] = False

    from generator import osm as kosm, sketch

    def view_with(extra):
        """El plano con mapas de más tratados como pueblos (para enganchar
        un cruce a un enlace ya hecho)."""
        v = {**layout, "towns": dict(layout["towns"])}
        for n, (x, y, w, h) in extra.items():
            v["towns"][n] = {"cell_x": x, "cell_y": y, "cells": [w, h]}
        return v

    def obstacles_except(*names):
        obs = [(x * CELL, y * CELL, (x + w) * CELL, (y + h) * CELL)
               for n, (x, y, w, h) in link_boxes.items() if n not in names]
        obs += [(t["cell_x"] * CELL, t["cell_y"] * CELL,
                 (t["cell_x"] + t["cells"][0]) * CELL, (t["cell_y"] + t["cells"][1]) * CELL)
                for n, t in layout["towns"].items() if n not in names]
        return obs

    def build_from_design(name, design, mpt, box):
        """Genera un mapa de enlace a partir de su dibujo, lo coloca y construye
        sus edificios con el mapa de papel bien dibujado."""
        call("post", "/api/generate", json={
            "mapName": name, "design": design, "metersPerTile": mpt, "settings": LINK_SETTINGS})
        place(name, box["x"], box["y"])
        link_boxes[name] = (int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"]))
        # El mapa de papel del juego (worldmap.xml) KnoxMap lo dibuja con
        # la descarga de OpenStreetMap del mapa, y un enlace no tiene: solo
        # saldrían sus casas. Se le da el propio dibujo del enlace (carretera,
        # bosques, campos) mientras construye.
        drawn = sketch.features(sketch.design_to_drawn(design))
        real_load = kosm.load_cache
        kosm.load_cache = lambda *a, **k: list(drawn)
        try:
            call("post", "/api/buildings", json={"mapName": name})
        finally:
            kosm.load_cache = real_load
        with open(os.path.join(out_dir, name, f"{name}_design.json"), "w", encoding="utf-8") as f:
            json.dump(design, f)

    def clear_old(name):
        """Al rehacer un enlace, fuera las versiones anteriores (de una pieza o
        en tramos), que si no quedarían como mapas sueltos."""
        import re
        import shutil
        for entry in os.listdir(out_dir):
            if entry == name or re.fullmatch(re.escape(name) + r"_\d+", entry):
                shutil.rmtree(os.path.join(out_dir, entry), ignore_errors=True)
                link_boxes.pop(entry, None)

    def build_routed(name, a, b, view, candidates):
        """Cuando una carretera recta no cabe en un solo rectángulo libre, se
        busca un camino por las celdas libres (con los menos giros posibles) y
        se construye en tramos rectos, cada uno su propio mapa: Nombre_1,
        Nombre_2... La carretera cruza de un tramo a otro por el mismo punto."""
        import heapq
        mpt = layout["meters_per_tile"]
        busy = set()
        for n, t in view["towns"].items():
            for cx in range(t["cell_x"], t["cell_x"] + t["cells"][0]):
                for cy in range(t["cell_y"], t["cell_y"] + t["cells"][1]):
                    busy.add((cx, cy))
        for n, (x, y, w, h) in link_boxes.items():
            for cx in range(x, x + w):
                for cy in range(y, y + h):
                    busy.add((cx, cy))
        xs = [c[0] for c in busy]
        ys = [c[1] for c in busy]
        bounds = (max(0, min(xs) - 6), max(0, min(ys) - 6), max(xs) + 6, max(ys) + 6)

        def edge_normal(town, pt):
            t = view["towns"][town]
            x0, y0 = t["cell_x"] * CELL, t["cell_y"] * CELL
            x1, y1 = x0 + t["cells"][0] * CELL, y0 + t["cells"][1] * CELL
            for nrm, hit in (((-1, 0), pt[0] == x0), ((1, 0), pt[0] == x1),
                             ((0, -1), pt[1] == y0), ((0, 1), pt[1] == y1)):
                if hit:
                    return nrm
            return None

        def astar(start, goal):
            # Estado: (celda, dirección). Cada giro cuesta como 3 celdas.
            heap = [(0, 0, start, None, None)]
            seen = {}
            n = 0
            while heap:
                f, g, cell, d, parent = heapq.heappop(heap)
                if (cell, d) in seen:
                    continue
                seen[(cell, d)] = parent
                if cell == goal:
                    path = [(cell, d)]
                    while seen[path[-1]] is not None:
                        path.append(seen[path[-1]])
                    return [c for c, _ in reversed(path)]
                for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nxt = (cell[0] + nd[0], cell[1] + nd[1])
                    if nxt in busy or not (bounds[0] <= nxt[0] <= bounds[2] and bounds[1] <= nxt[1] <= bounds[3]):
                        continue
                    ng = g + 1 + (3 if d is not None and nd != d else 0)
                    h = abs(nxt[0] - goal[0]) + abs(nxt[1] - goal[1])
                    n += 1
                    heapq.heappush(heap, (ng + h, ng, nxt, nd, (cell, d)))
            return None

        for points, kind, notes in candidates:
            p0, pn = points[0], points[-1]
            na, nb = edge_normal(a, p0), edge_normal(b, pn)
            if na is None or nb is None:
                continue
            start = (int((p0[0] + na[0]) // CELL), int((p0[1] + na[1]) // CELL))
            goal = (int((pn[0] + nb[0]) // CELL), int((pn[1] + nb[1]) // CELL))
            if start in busy or goal in busy:
                continue
            path = astar(start, goal)
            if not path:
                continue
            direct = abs(goal[0] - start[0]) + abs(goal[1] - start[1]) + 1
            if len(path) > 2 * direct + 4:
                print(f"  el camino libre da un rodeo de {len(path)} celdas (directo: {direct}); se descarta",
                      flush=True)
                continue
            # Tramos rectos; la celda de cada giro se queda en el tramo que acaba en ella.
            runs, cur = [], [path[0]]
            for prev, cell, nxt in zip(path, path[1:], path[2:] + [None]):
                cur.append(cell)
                if nxt is not None and (nxt[0] - cell[0], nxt[1] - cell[1]) != (cell[0] - prev[0], cell[1] - prev[1]):
                    runs.append(cur)
                    cur = []
            if cur:
                runs.append(cur)
            centre = lambda c: ((c[0] + 0.5) * CELL, (c[1] + 0.5) * CELL)
            line = [p0, (p0[0] + na[0] * STUB, p0[1] + na[1] * STUB), centre(path[0])]
            line += [centre(r[-1]) for r in runs[:-1]]
            line += [centre(path[-1]), (pn[0] + nb[0] * STUB, pn[1] + nb[1] * STUB), pn]
            print(notes, flush=True)
            print(f"en {len(runs)} tramos por celdas libres", flush=True)
            for k, run in enumerate(runs, 1):
                cx0, cy0 = min(c[0] for c in run), min(c[1] for c in run)
                w = max(c[0] for c in run) - cx0 + 1
                h = max(c[1] for c in run) - cy0 + 1
                W, H = w * CELL * mpt, h * CELL * mpt
                sheet = [((x - cx0 * CELL) * mpt, ((cy0 + h) * CELL - y) * mpt) for x, y in line]
                feats = []
                for part in P._clip_to_box(sheet, W, H):
                    feats.append({"kind": kind, "points": [[round(x, 1), round(y, 1)] for x, y in part]})
                    feats += P._scenery(part, W, H, seed=cx0 * 1000 + cy0)
                design = {"width_m": round(W, 1), "height_m": round(H, 1),
                          "anchor": {"lat": 0.0, "lon": 0.0}, "features": feats}
                piece = f"{name}_{k}"
                build_from_design(piece, design, mpt, {"x": cx0, "y": cy0, "w": w, "h": h})
                ok[piece] = True
                print(f"  {piece}: {w} x {h} celdas en {cx0},{cy0}", flush=True)
            return
        raise RuntimeError("tampoco hay un camino por celdas libres entre los dos")

    def build_link(name, a, b, view, candidates, fallback=None):
        """Prueba las salidas candidatas hasta que una cabe pegada a los dos
        mapas, con los dos extremos de la carretera dentro de la caja."""
        # KnoxMap deja una celda de campo alrededor de la carretera y, si
        # choca con otro mapa, recorta la caja entera por ese lado: puede
        # quedar una celda vacía entre el enlace y el pueblo, o cortarse el
        # final de la carretera. Se prueba sin margen y, si no, la siguiente
        # mejor pareja de salidas.
        def touches(bx, town):
            t = view["towns"][town]
            tx, ty, tw, th = t["cell_x"], t["cell_y"], *t["cells"]
            x0, y0, x1, y1 = bx["x"], bx["y"], bx["x"] + bx["w"], bx["y"] + bx["h"]
            side_x = (x1 == tx or x0 == tx + tw) and y0 < ty + th and ty < y1
            side_y = (y1 == ty or y0 == ty + th) and x0 < tx + tw and tx < x1
            return side_x or side_y

        def holds(bx, pt):
            return (bx["x"] * CELL <= pt[0] <= (bx["x"] + bx["w"]) * CELL
                    and bx["y"] * CELL <= pt[1] <= (bx["y"] + bx["h"]) * CELL)

        clear_old(name)
        plan = None
        try:
            tried = list(candidates)
        except RuntimeError:
            tried = []
        for points, kind, notes in tried:
            for margin in (1, 0):
                P.LINK_MARGIN_CELLS = margin
                try:
                    attempt = call("post", f"/api/placement/{a}/link",
                                   json={"points": points, "kind": kind})
                except RuntimeError:
                    continue
                bx = attempt["box"]
                if (touches(bx, a) and touches(bx, b)
                        and holds(bx, points[0]) and holds(bx, points[-1])):
                    plan = attempt
                    break
            P.LINK_MARGIN_CELLS = 1
            if plan is not None:
                print(notes, flush=True)
                break
        if plan is None:
            if fallback is not None:
                return build_routed(name, a, b, view, fallback())
            raise RuntimeError("no cabe una carretera pegada a los dos mapas sin pisar otros")
        box = plan["box"]
        # Un enlace largo en diagonal en un solo rectángulo son cientos de
        # celdas de campo vacío que hay que compilar. Si pasa de 150, mejor en
        # tramos rectos por celdas libres (si se puede).
        if box["w"] * box["h"] > 150 and fallback is not None:
            try:
                print(f"un solo rectángulo serían {box['w'] * box['h']} celdas; se intenta en tramos", flush=True)
                return build_routed(name, a, b, view, fallback())
            except RuntimeError as exc:
                print(f"en tramos no sale ({exc}); va en un rectángulo", flush=True)
        print(f"tramo: {box['w']} x {box['h']} celdas en {box['x']},{box['y']}", flush=True)
        build_from_design(name, plan["design"], plan["metersPerTile"], box)

    for a, b in links:
        l = by_pair[(a, b)]
        name = f"Enlace_{a}_{b}"
        print(f"\n=== {name} ({l['ref'] or 'carretera'}) ===", flush=True)
        try:
            t0 = time.time()
            build_link(name, a, b, layout,
                       snap_link(knox, layout, a, b, l["points"], obstacles_except(a, b)),
                       fallback=lambda: snap_link(knox, layout, a, b, l["points"],
                                                  obstacles_except(a, b), allow_blocked=True))
            print(f"ok en {time.time() - t0:.0f}s", flush=True)
            ok[name] = True
        except Exception as exc:  # noqa: BLE001
            print(f"FALLO: {exc}")
            ok[name] = False

    # ---------------------------------------------------------------- cruces
    # Un pueblo que se engancha a mitad de un enlace ya hecho: se rehace el
    # enlace con un ramal que sale de su carretera hasta su borde, y luego se
    # construye la carretera del pueblo hasta ese ramal.
    normals = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}
    ROADS = {"motorway", "primary", "secondary", "residential"}

    def nearest_on(poly, p):
        best = None
        for q0, q1 in zip(poly, poly[1:]):
            dx, dy = q1[0] - q0[0], q1[1] - q0[1]
            t = max(0.0, min(1.0, ((p[0] - q0[0]) * dx + (p[1] - q0[1]) * dy) / ((dx * dx + dy * dy) or 1)))
            q = (q0[0] + t * dx, q0[1] + t * dy)
            if best is None or math.dist(q, p) < math.dist(best, p):
                best = q
        return best

    for town, la, lb in cruces:
        lname = next((n for n in (f"Enlace_{la}_{lb}", f"Enlace_{lb}_{la}")
                      if os.path.isdir(os.path.join(out_dir, n))), None)
        name = f"Cruce_{town}_{la}_{lb}"
        print(f"\n=== {name} ===", flush=True)
        try:
            if lname is None:
                raise RuntimeError(f"no está generado el enlace {la}-{lb}")
            t0 = time.time()
            lx, ly, lw, lh = link_boxes[lname]
            ldir = os.path.join(out_dir, lname)
            design = json.load(open(os.path.join(ldir, f"{lname}_design.json"), encoding="utf-8"))
            mpt = json.load(open(os.path.join(ldir, f"{lname}_info.json"), encoding="utf-8"))["meters_per_tile"]
            top = (ly + lh) * CELL

            def to_world(p):
                return (lx * CELL + p[0] / mpt, top - p[1] / mpt)

            def to_design(w):
                return [round((w[0] - lx * CELL) * mpt, 1), round((top - w[1]) * mpt, 1)]

            # Quitar un ramal anterior al mismo pueblo, si se repite el cruce.
            feats = [f for f in design["features"] if f.get("branch") != town]
            road = next(f for f in feats if f["kind"] in ROADS)
            road_w = [to_world(p) for p in road["points"]]
            t = layout["towns"][town]
            tb = (t["cell_x"] * CELL, t["cell_y"] * CELL,
                  (t["cell_x"] + t["cells"][0]) * CELL, (t["cell_y"] + t["cells"][1]) * CELL)
            tc = ((tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2)
            occupied = obstacles_except(town, lname)
            lbox = (lx * CELL, ly * CELL, (lx + lw) * CELL, (ly + lh) * CELL)

            # Salida del ramal: un punto del borde del enlace que mire al pueblo,
            # con campo libre al otro lado y paso libre hasta el pueblo; el más
            # cercano al pueblo, sin alargar mucho el ramal por dentro.
            best = None
            for edge, (nx, ny) in normals.items():
                if edge in ("left", "right"):
                    x = lbox[0] if edge == "left" else lbox[2]
                    pts = [(x, y) for y in range(int(lbox[1]) + 90, int(lbox[3]) - 89, 30)]
                else:
                    y = lbox[1] if edge == "top" else lbox[3]
                    pts = [(x, y) for x in range(int(lbox[0]) + 90, int(lbox[2]) - 89, 30)]
                for pt in pts:
                    if nx * (tc[0] - pt[0]) + ny * (tc[1] - pt[1]) <= 0:
                        continue
                    out = (pt[0] + nx * CELL / 2, pt[1] + ny * CELL / 2)
                    if any(o[0] <= out[0] <= o[2] and o[1] <= out[1] <= o[3] for o in occupied):
                        continue
                    tp = (min(max(pt[0], tb[0]), tb[2]), min(max(pt[1], tb[1]), tb[3]))
                    stub = (pt[0] + nx * STUB, pt[1] + ny * STUB)
                    # Mejor si hay paso recto hasta el pueblo; si no, la carretera
                    # irá en tramos por las celdas libres.
                    straight = not any(_seg_hits(stub, tp, o) for o in occupied)
                    q = nearest_on(road_w, pt)
                    cost = math.dist(pt, tp) + 1.5 * math.dist(pt, q) + (0 if straight else 5000)
                    if best is None or cost < best[0]:
                        best = (cost, pt, edge, q)
            if best is None:
                raise RuntimeError(f"el enlace {la}-{lb} no tiene ningún borde libre mirando a {town}")
            _, pt, edge, q = best
            nx, ny = normals[edge]
            inner = (pt[0] - nx * STUB, pt[1] - ny * STUB)
            branch = [q, inner, pt]
            # Fuera las casas que caigan encima del ramal.
            def near_branch(f):
                if f["kind"] != "house":
                    return False
                return any(math.dist(to_world(p), nearest_on(branch, to_world(p))) < 15 / mpt * 2
                           for p in f["points"])
            feats = [f for f in feats if not near_branch(f)]
            feats.append({"kind": "secondary", "points": [to_design(p) for p in branch], "branch": town})
            design2 = {**design, "features": feats}
            print(f"ramal en {lname}: sale por {edge} en {round(pt[0])},{round(pt[1])}", flush=True)
            build_from_design(lname, design2, mpt, {"x": lx, "y": ly, "w": lw, "h": lh})
            ok[lname] = True

            # Y la carretera del pueblo hasta el ramal, como un enlace más.
            view = view_with({lname: (lx, ly, lw, lh)})
            only = [(pt[0], pt[1], 5, edge, 0)]
            cands = snap_link(knox, view, town, lname, [tc, pt],
                              obstacles_except(town, lname), only_b=only)
            build_link(name, town, lname, view, cands,
                       fallback=lambda: snap_link(knox, view, town, lname, [tc, pt],
                                                  obstacles_except(town, lname), only_b=only,
                                                  allow_blocked=True))
            print(f"ok en {time.time() - t0:.0f}s", flush=True)
            ok[name] = True
        except Exception as exc:  # noqa: BLE001
            print(f"FALLO: {exc}")
            ok[name] = False

    print("\nResumen:")
    for n, good in ok.items():
        print(f"  {n:40s} {'listo para Compile e Install' if good else 'FALLO'}")
    # ¿Queda todo conectado por carretera con los enlaces que han salido bien?
    if links or cruces:
        group = {t: t for t in layout["towns"]}

        def root(t):
            while group[t] != t:
                t = group[t]
            return t
        for town, la, lb in cruces:
            if ok.get(f"Cruce_{town}_{la}_{lb}"):
                group[root(town)] = root(la)
        import re
        for n in os.listdir(os.path.join(knox, "output")):
            base = re.sub(r"_\d+$", "", n)       # los tramos se llaman Enlace_A_B_1, _2...
            if n.startswith("Enlace_") and ok.get(n, True) and ok.get(base, True):
                for la, lb in [(l["a"], l["b"]) for l in layout["links"]]:
                    if base in (f"Enlace_{la}_{lb}", f"Enlace_{lb}_{la}"):
                        group[root(la)] = root(lb)
        parts = {}
        for t in layout["towns"]:
            parts.setdefault(root(t), []).append(t)
        if len(parts) == 1:
            print("\nTodos los pueblos quedan conectados por carretera.")
        else:
            print("\nOJO, quedan grupos sin conectar entre sí:")
            for p in parts.values():
                print("  - " + ", ".join(p))
    return 0 if all(ok.values()) else 1


# Imprescindible en Windows (procesos nuevos vuelven a importar este archivo).
if __name__ == "__main__":
    if os.environ.get("KNOX_SPAWN_TEST"):
        import multiprocessing
        multiprocessing.set_start_method("spawn", force=True)
    sys.exit(main())
