"""Rellena los huecos vacíos que quedan entre Ciudad Real y los pueblos de
alrededor, uniendo las carreteras que ya hay y poniendo sitios de interés.

Qué hace:
1. Busca los huecos del mapa: las celdas sin mapa que quedan encerradas entre
   pueblos y carreteras de enlace (no el vacío de fuera).
2. Parte cada hueco en rectángulos; cada uno será un mapa "Relleno_..." de
   campo, como los de los enlaces.
3. Busca qué carreteras llegan al borde del hueco:
   - las salidas de los pueblos que hoy acaban en el vacío;
   - las carreteras de enlace que pasan junto al hueco. A esos enlaces se les
     añade un ramal hasta su borde (el mapa del enlace se rehace con él).
4. Traza carreteras que unen todas esas salidas por dentro del hueco, rectas
   y a 45 grados, como las del juego.
5. Pone a los lados sitios de interés: centro comercial, polígono de naves,
   base militar, restaurantes de carretera, gasolineras; y campo (cultivos,
   olivares, bosquetes, cortijos) en el resto.

Uso (Windows, desde la carpeta de KnoxMap y con su ventana cerrada):
    .venv\\Scripts\\python.exe ..\\ProvinciaCR\\rellenos.py . ..\\ProvinciaCR\\layout.json
    --solo-plan    solo calcula y dibuja el plan (rellenos_plan.png), sin generar
Después: compilar.py (compila los Relleno_* y los enlaces con ramal nuevo).
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import random
import sys
import time

CELL = 300
STUB = 40              # tiles rectos al salir de un borde
R = 10                 # resolución de la rejilla de trazado, en tiles
MARGEN = 14            # las carreteras no pegadas al borde del hueco (tiles)
ROADS = {"motorway", "primary", "secondary", "residential"}
ZONA = (60, 0, 125, 60)  # celdas donde se buscan huecos (alrededor de Ciudad Real)
# Mapas de una versión anterior del plano que ya no existen (Infantes y
# Villahermosa se han acercado; sus enlaces largos sobran)
RETIRADOS = {"Enlace_Bolanos_Infantes", "Enlace_Bolanos_Infantes_1", "Enlace_Bolanos_Infantes_2",
             "Enlace_Infantes_Villahermosa"}

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


# ---------------------------------------------------------------------------
# Mapas, huecos y rectángulos
# ---------------------------------------------------------------------------

def cajas(out_dir, layout):
    """{nombre: (x, y, w, h)} en celdas de todos los mapas del plano."""
    out = {n: (t["cell_x"], t["cell_y"], *t["cells"]) for n, t in layout["towns"].items()}
    for entry in os.listdir(out_dir):
        if not entry.startswith(("Enlace_", "Cruce_", "Relleno_")) or entry in RETIRADOS:
            continue
        try:
            pl = json.load(open(os.path.join(out_dir, entry, "placement.json"), encoding="utf-8"))
            inf = json.load(open(os.path.join(out_dir, entry, f"{entry}_info.json"), encoding="utf-8"))
            out[entry] = (pl["cell_x"], pl["cell_y"], inf["cells_x"], inf["cells_y"])
        except (OSError, ValueError, KeyError):
            pass
    return out


def huecos(boxes, zona=ZONA, sin=("Relleno_",)):
    x0, y0, x1, y1 = zona
    occ = {}
    for n, (x, y, w, h) in boxes.items():
        if n.startswith(sin):
            continue
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                occ[(xx, yy)] = n
    fuera = set()
    stack = [(x, y) for x in range(x0 - 1, x1 + 1) for y in (y0 - 1, y1)] + \
            [(x, y) for y in range(y0 - 1, y1 + 1) for x in (x0 - 1, x1)]
    while stack:
        c = stack.pop()
        if c in fuera or c in occ or not (x0 - 1 <= c[0] <= x1 and y0 - 1 <= c[1] <= y1):
            continue
        fuera.add(c)
        stack += [(c[0] + 1, c[1]), (c[0] - 1, c[1]), (c[0], c[1] + 1), (c[0], c[1] - 1)]
    libres = {(x, y) for x in range(x0, x1) for y in range(y0, y1)
              if (x, y) not in occ and (x, y) not in fuera}
    grupos = []
    while libres:
        c = libres.pop()
        g, st = {c}, [c]
        while st:
            a = st.pop()
            for b in ((a[0] + 1, a[1]), (a[0] - 1, a[1]), (a[0], a[1] + 1), (a[0], a[1] - 1)):
                if b in libres:
                    libres.discard(b)
                    g.add(b)
                    st.append(b)
        grupos.append(g)
    grupos.sort(key=lambda g: (-len(g), min(g)))
    return grupos, occ


def rectangulos(cells):
    """Parte un conjunto de celdas en rectángulos, el más grande primero."""
    cells = set(cells)
    out = []
    while cells:
        best = None
        for (x, y) in cells:
            # el mayor rectángulo con esta esquina arriba-izquierda
            wmax = 0
            while (x + wmax, y) in cells:
                wmax += 1
            w = wmax
            h = 0
            while w > 0:
                if all((x + i, y + h) in cells for i in range(w)):
                    h += 1
                    if best is None or w * h > best[0]:
                        best = (w * h, x, y, w, h)
                else:
                    w -= 1
                    if w and best is not None and w * (h + 1) <= best[0]:
                        break
        _, x, y, w, h = best
        out.append((x, y, w, h))
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                cells.discard((xx, yy))
    return out


# ---------------------------------------------------------------------------
# Carreteras que llegan al hueco
# ---------------------------------------------------------------------------
NORMAL = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}


def _provincia():
    """provincia.py de ESTA carpeta (en la de KnoxMap puede haber una copia
    vieja, y al trabajar desde allí Python la encontraría antes)."""
    import importlib.util
    mod = sys.modules.get("provincia_cr")
    if mod is None:
        spec = importlib.util.spec_from_file_location("provincia_cr", os.path.join(HERE, "provincia.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["provincia_cr"] = mod
        spec.loader.exec_module(mod)
    return mod


def salidas_pueblo(knox, name, box, hole):
    """Calles de un pueblo que llegan a un borde que da al hueco.

    Si la calle toca el borde, la salida es justo donde lo toca (una calle en
    diagonal llega al borde lejos del centro de su franja). Si se queda un poco
    antes, se toma la franja de 40 tiles, como hacen los enlaces."""
    import numpy as np
    from PIL import Image
    edge_roads = _provincia().edge_roads
    img = np.array(Image.open(os.path.join(knox, "output", name, f"{name}_road_hierarchy.bmp")))
    h, w = img.shape[:2]
    tx, ty, tw, th = box
    out = []
    for edge, (nx, ny) in NORMAL.items():
        fila = {"left": img[:, 0], "right": img[:, w - 1], "top": img[0, :], "bottom": img[h - 1, :]}[edge]
        exactas = []
        run = None
        for i, v in enumerate(list(fila) + [0]):
            v = int(v)
            if v >= 3:
                run = [i, i, v] if run is None else [run[0], i, max(run[2], v)]
            elif run is not None:
                exactas.append(((run[0] + run[1]) / 2, run[2]))
                run = None
        cand = []
        for pos, cls in exactas:
            if edge in ("left", "right"):
                cand.append((tx * CELL + (0 if edge == "left" else w), ty * CELL + pos, cls))
            else:
                cand.append((tx * CELL + pos, ty * CELL + (0 if edge == "top" else h), cls))
        try:
            for x, y, cls, *_ in edge_roads(knox, name, (tx, ty), edge):
                if all(math.dist((x, y), (a, b)) > 30 for a, b, _c in cand):
                    cand.append((x, y, cls))
        except OSError:
            pass
        for x, y, cls in cand:
            # la celda de fuera, al otro lado del borde
            cx = int((x + nx * 5) // CELL)
            cy = int((y + ny * 5) // CELL)
            if (cx, cy) not in hole or cls < 3 or not _lejos_de_esquina((x, y), (nx, ny), hole, 25):
                continue
            out.append({"x": x, "y": y, "cls": cls, "edge": edge, "n": (nx, ny),
                        "de": name, "tipo": "pueblo"})
    return out


def carretera_de(out_dir, lname):
    """La carretera principal de un enlace, en tiles del mundo."""
    d = json.load(open(os.path.join(out_dir, lname, f"{lname}_design.json"), encoding="utf-8"))
    inf = json.load(open(os.path.join(out_dir, lname, f"{lname}_info.json"), encoding="utf-8"))
    pl = json.load(open(os.path.join(out_dir, lname, "placement.json"), encoding="utf-8"))
    mpt = inf["meters_per_tile"]
    top = (pl["cell_y"] + inf["cells_y"]) * CELL
    lines = []
    for f in d["features"]:
        if f["kind"] in ROADS and not f.get("branch"):
            lines.append([(pl["cell_x"] * CELL + p[0] / mpt, top - p[1] / mpt) for p in f["points"]])
    return d, mpt, lines


def _cerca(poly, p):
    best = None
    for q0, q1 in zip(poly, poly[1:]):
        dx, dy = q1[0] - q0[0], q1[1] - q0[1]
        t = max(0.0, min(1.0, ((p[0] - q0[0]) * dx + (p[1] - q0[1]) * dy) / ((dx * dx + dy * dy) or 1)))
        q = (q0[0] + t * dx, q0[1] + t * dy)
        if best is None or math.dist(q, p) < math.dist(best, p):
            best = q
    return best


def _lejos_de_esquina(p, n, hole, m=60):
    """Que a `m` tiles a cada lado del punto, a lo largo del borde, siga
    habiendo hueco (si no, el tramo recto de la salida va pegado a otro mapa)."""
    nx, ny = n
    tx, ty = -ny, nx
    for s_ in (-m, m):
        x, y = p[0] + tx * s_ + nx * 5, p[1] + ty * s_ + ny * 5
        if (int(x // CELL), int(y // CELL)) not in hole:
            return False
    return True


def ramales_enlace(out_dir, lname, box, hole, maxdist=300, lejos_de=None, cerca_de=None):
    """El mejor punto del borde de un enlace, junto al hueco, para sacarle un
    ramal: donde su carretera pasa más cerca."""
    try:
        _, _, lines = carretera_de(out_dir, lname)
    except (OSError, KeyError, ValueError):
        return []
    if not lines:
        return []
    lx, ly, lw, lh = box
    x0, y0, x1, y1 = lx * CELL, ly * CELL, (lx + lw) * CELL, (ly + lh) * CELL
    best = None
    for edge, (nx, ny) in NORMAL.items():
        if edge in ("left", "right"):
            x = x0 if edge == "left" else x1
            pts = [(x, y) for y in range(y0 + 60, y1 - 59, 15)]
        else:
            y = y0 if edge == "top" else y1
            pts = [(x, y) for x in range(x0 + 60, x1 - 59, 15)]
        for p in pts:
            c = (int((p[0] + nx * 5) // CELL), int((p[1] + ny * 5) // CELL))
            if c not in hole:
                continue
            # el hueco tiene que seguir STUB+MARGEN tiles al otro lado, y no
            # estar en una esquina (el tramo recto iría pegado al borde)
            c2 = (int((p[0] + nx * (STUB + MARGEN + 5)) // CELL), int((p[1] + ny * (STUB + MARGEN + 5)) // CELL))
            if c2 not in hole:
                continue
            if not _lejos_de_esquina(p, (nx, ny), hole):
                continue
            for line in lines:
                q = _cerca(line, p)
                d = math.dist(p, q)
                if d > maxdist:
                    continue
                # con `lejos_de`, el punto más alejado de esas salidas
                # con `cerca_de`, el que mejor queda hacia ese punto
                if lejos_de:
                    score = -min(math.dist(p, f) for f in lejos_de)
                elif cerca_de:
                    score = d + 0.5 * math.dist(p, cerca_de)
                else:
                    score = d
                if best is None or score < best[4]:
                    best = (d, p, edge, q, score)
    if best is None:
        return []
    d, p, edge, q, _ = best
    return [{"x": p[0], "y": p[1], "cls": 5, "edge": edge, "n": NORMAL[edge], "de": lname,
             "tipo": "enlace", "q": q}]


# ---------------------------------------------------------------------------
# Trazado por dentro del hueco
# ---------------------------------------------------------------------------
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]


def _pt(x, y):
    from shapely.geometry import Point
    return Point(x, y)


class Rejilla:
    def __init__(self, hole, bloqueo=None):
        self.hole = hole
        xs = [c[0] for c in hole]
        ys = [c[1] for c in hole]
        self.X0, self.Y0 = min(xs) * CELL, min(ys) * CELL
        self.nx = (max(xs) + 1 - min(xs)) * CELL // R
        self.ny = (max(ys) + 1 - min(ys)) * CELL // R
        self.ok = set()
        for i in range(self.nx):
            for j in range(self.ny):
                x, y = self.X0 + i * R + R / 2, self.Y0 + j * R + R / 2
                if self._dentro(x, y, MARGEN) and not (bloqueo is not None and bloqueo.contains(_pt(x, y))):
                    self.ok.add((i, j))
        self.road = {}       # nodo -> clase
        self.atraer = True   # las rutas nuevas buscan juntarse a lo ya trazado
        # distancia (en nodos) al borde del hueco, para que las carreteras
        # vayan por dentro y no pegadas a los enlaces de alrededor
        from collections import deque
        self.dist = {}
        q = deque()
        for n in self.ok:
            if any((n[0] + dx, n[1] + dy) not in self.ok for dx, dy in DIRS):
                self.dist[n] = 0
                q.append(n)
        while q:
            n = q.popleft()
            for dx, dy in DIRS[::2]:
                m = (n[0] + dx, n[1] + dy)
                if m in self.ok and m not in self.dist:
                    self.dist[m] = self.dist[n] + 1
                    q.append(m)

    def _dentro(self, x, y, m):
        for dx in (-m, 0, m):
            for dy in (-m, 0, m):
                if (int((x + dx) // CELL), int((y + dy) // CELL)) not in self.hole:
                    return False
        return True

    def nodo(self, x, y):
        return (int((x - self.X0) // R), int((y - self.Y0) // R))

    def cercano(self, n, radio=80):
        """El nodo válido más cercano a `n` (buscando en anillos)."""
        if n in self.ok:
            return n
        for r in range(1, radio):
            mejor = None
            for i in range(-r, r + 1):
                for m in ((n[0] + i, n[1] - r), (n[0] + i, n[1] + r), (n[0] - r, n[1] + i), (n[0] + r, n[1] + i)):
                    if m in self.ok:
                        d = (m[0] - n[0]) ** 2 + (m[1] - n[1]) ** 2
                        if mejor is None or d < mejor[0]:
                            mejor = (d, m)
            if mejor:
                return mejor[1]
        return n

    def punto(self, n):
        return (self.X0 + n[0] * R + R / 2, self.Y0 + n[1] * R + R / 2)

    def ruta(self, start, goals, ocupado=frozenset()):
        """Dijkstra en 8 direcciones con castigo por giro; la carretera ya
        trazada cuesta menos, para que las nuevas se junten a ella."""
        goals = set(goals)
        if start in goals:
            return [start]
        # A* cuando hay pocas metas (de punta a punta): lo mínimo que puede
        # costar llegar es la distancia en línea recta
        gl = list(goals) if len(goals) <= 8 else None
        fmin = 0.35 if (self.atraer and self.road) else 1.0

        def h(n):
            return fmin * min(math.hypot(n[0] - q[0], n[1] - q[1]) for q in gl) if gl else 0.0
        pq = [(h(start), 0.0, start, -1)]
        best = {(start, -1): 0.0}
        prev = {}
        while pq:
            _f, c, n, d = heapq.heappop(pq)
            if n in goals:
                path = [n]
                key = (n, d)
                while key in prev:
                    key = prev[key]
                    path.append(key[0])
                return path[::-1]
            if c > best.get((n, d), 1e18):
                continue
            for k, (dx, dy) in enumerate(DIRS):
                m = (n[0] + dx, n[1] + dy)
                if m not in self.ok or m in ocupado:
                    continue
                step = math.hypot(dx, dy)
                cerca_borde = max(0, 9 - self.dist.get(m, 9)) / 9      # 90 tiles
                cost = step * (0.35 if (self.atraer and m in self.road) else 1.0 + 1.5 * cerca_borde)
                if d >= 0 and d != k:
                    turn = min((k - d) % 8, (d - k) % 8)
                    cost += 2.5 * turn + (8 if turn > 1 else 0)
                nc = c + cost
                if nc < best.get((m, k), 1e18):
                    best[(m, k)] = nc
                    prev[(m, k)] = (n, d)
                    heapq.heappush(pq, (nc + h(m), nc, m, k))
        return None


def simplificar(pts):
    out = [pts[0]]
    for a, b in zip(pts[1:], pts[2:]):
        d1 = (a[0] - out[-1][0], a[1] - out[-1][1])
        d2 = (b[0] - a[0], b[1] - a[1])
        if d1[0] * d2[1] - d1[1] * d2[0] != 0:
            out.append(a)
    out.append(pts[-1])
    return out


AMPLITUD = {
    # (amplitud en tiles, longitud de onda en tiles)
    "carretera": (34, 700),
    "camino": (16, 260),
}


def marcar(g, line, cls):
    """Las casillas de la rejilla por las que pasa una línea ya trazada."""
    for (ax, ay), (bx, by) in zip(line, line[1:]):
        L = math.hypot(bx - ax, by - ay)
        for k in range(int(L // 5) + 1):
            t = k * 5 / L if L else 0
            n = g.nodo(ax + (bx - ax) * t, ay + (by - ay) * t)
            if n in g.ok:
                g.road[n] = max(g.road.get(n, 0), cls)


def _remuestrear(pts, paso):
    out = [pts[0]]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        L = math.hypot(bx - ax, by - ay)
        n = max(1, int(L // paso))
        for k in range(1, n + 1):
            out.append((ax + (bx - ax) * k / n, ay + (by - ay) * k / n))
    return out


def _chaikin(pts, veces=2):
    for _ in range(veces):
        nuevo = [pts[0]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            nuevo += [(0.75 * ax + 0.25 * bx, 0.75 * ay + 0.25 * by),
                      (0.25 * ax + 0.75 * bx, 0.25 * ay + 0.75 * by)]
        nuevo.append(pts[-1])
        pts = nuevo
    return pts


def _suavizar(line, tol=18):
    """Quita la escalera de 45 grados que deja la rejilla del trazado."""
    from shapely.geometry import LineString
    if len(line) < 3:
        return line
    cab, cola = line[:2], line[-2:]
    medio = LineString(line[1:-1]).simplify(tol) if len(line) > 3 else LineString(line[1:])
    return [cab[0]] + list(medio.coords) + [cola[-1]]


def ondular(line, g, rng, amp, onda, fijo_final=True):
    """Una carretera de campo: los ángulos de 45 grados del trazado se
    redondean en curvas y el trazado entero serpentea un poco, como una
    carretera comarcal. El tramo recto de cada salida (STUB) se respeta, para
    que siga enganchando recta con la calle del otro mapa."""
    if len(line) < 3:
        return line
    cabeza = line[:2]
    cola = line[-2:] if fijo_final and len(line) >= 4 else line[-1:]
    medio = line[1:len(line) - len(cola) + 1]
    if len(medio) < 2:
        return line
    base = _remuestrear(medio, 8)
    L = sum(math.dist(a, b) for a, b in zip(base, base[1:]))
    if L < 60:
        return line
    for intento in range(4):
        a = amp * (0.5 ** intento) * rng.uniform(0.7, 1.3)
        w1 = onda * rng.uniform(0.8, 1.3)
        w2 = w1 * rng.uniform(0.3, 0.45)
        f1, f2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
        out, s_ = [], 0.0
        for k, p in enumerate(base):
            if k:
                s_ += math.dist(base[k - 1], p)
            q0 = base[max(0, k - 1)]
            q1 = base[min(len(base) - 1, k + 1)]
            tx, ty = q1[0] - q0[0], q1[1] - q0[1]
            tl = math.hypot(tx, ty) or 1
            nx, ny = -ty / tl, tx / tl
            taper = max(0.0, math.sin(math.pi * min(s_, L) / L)) ** 0.8
            off = a * taper * (math.sin(2 * math.pi * s_ / w1 + f1) + 0.45 * math.sin(2 * math.pi * s_ / w2 + f2))
            out.append((p[0] + nx * off, p[1] + ny * off))
        out = _chaikin(out, 2)
        if all(g._dentro(x, y, 6) for x, y in out[::3]):
            return [cabeza[0]] + out + cola[1:]
    return [cabeza[0]] + _chaikin(base, 2) + cola[1:]


def _tangente(line, d):
    """Punto y dirección de una línea a `d` tiles de su principio."""
    acc = 0.0
    for a, b in zip(line, line[1:]):
        L = math.dist(a, b)
        if acc + L >= d and L > 0:
            t = (d - acc) / L
            return ((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                    ((b[0] - a[0]) / L, (b[1] - a[1]) / L))
        acc += L
    return None


def _largo(line):
    return sum(math.dist(a, b) for a, b in zip(line, line[1:]))


def trazar(hole, ends):
    """Carreteras que unen todas las salidas: un árbol que va creciendo, cada
    salida se engancha por el camino más corto a lo ya trazado."""
    g = Rejilla(hole)
    roads = []
    if not ends:
        return g, roads
    # dentro del hueco, al final del tramo recto
    for e in ends:
        nx, ny = e["n"]
        e["dentro"] = (e["x"] + nx * STUB, e["y"] + ny * STUB)
        e["nodo"] = g.cercano(g.nodo(*e["dentro"]))
    # de la salida más importante hacia fuera
    orden = sorted(ends, key=lambda e: (-e["cls"], e["x"], e["y"]))
    hecho = [orden[0]]
    pend = orden[1:]
    while pend:
        # la salida pendiente más cerca de lo ya trazado (o de las salidas hechas)
        red = set(g.road) or {hecho[0]["nodo"]}
        e = min(pend, key=lambda e: min(math.dist(e["nodo"], r) for r in red))
        pend.remove(e)
        path = g.ruta(e["nodo"], red)
        if path is None:
            continue
        cls = max(e["cls"], 4)
        for n in path:
            g.road[n] = max(g.road.get(n, 0), cls)
        if not set(path[1:]) & set():
            pass
        pts = [g.punto(n) for n in path]
        nx, ny = e["n"]
        line = [(e["x"], e["y"]), e["dentro"]] + pts
        roads.append({"cls": cls, "line": simplificar(line), "end": e})
        hecho.append(e)
    # la primera salida también necesita su tramo recto hasta la red
    e0 = orden[0]
    if len(orden) > 1:
        roads.append({"cls": max(e0["cls"], 4),
                      "line": [(e0["x"], e0["y"]), e0["dentro"], g.punto(e0["nodo"])], "end": e0})
    return g, roads


def enfrente(knox, out_dir, layout, boxes, occ, hole, e, todas):
    """Lo que hay al otro lado del hueco, siguiendo recto desde una salida: la
    carretera de un enlace (a la que se le saca un ramal justo enfrente) o una
    salida de otro pueblo."""
    nx, ny = e["n"]
    x, y = e["x"] + nx * 5, e["y"] + ny * 5
    for _ in range(4000):
        x2, y2 = x + nx * 10, y + ny * 10
        c = (int(x2 // CELL), int(y2 // CELL))
        if c not in hole:
            break
        x, y = x2, y2
    else:
        return None
    m = occ.get(c)
    if m is None:
        return None
    # el punto del borde entre el hueco y ese mapa
    if nx:
        hx, hy = (c[0] * CELL if nx > 0 else (c[0] + 1) * CELL), y
    else:
        hx, hy = x, (c[1] * CELL if ny > 0 else (c[1] + 1) * CELL)
    if math.dist((hx, hy), (e["x"], e["y"])) < 2 * STUB + 60:
        return None
    back = (-nx, -ny)
    edge = next(k for k, v in NORMAL.items() if v == back)
    if not _lejos_de_esquina((hx, hy), back, hole):
        return None
    if m in layout["towns"]:
        cands = [f for f in todas if f["de"] == m and f["n"] == back
                 and math.dist((f["x"], f["y"]), (hx, hy)) < 260]
        return min(cands, key=lambda f: math.dist((f["x"], f["y"]), (hx, hy))) if cands else None
    try:
        _, _, lines = carretera_de(out_dir, m)
    except (OSError, KeyError, ValueError):
        return None
    bx, by, bw, bh = boxes[m]
    # dentro del borde del enlace, lejos de sus esquinas
    if nx and not (by * CELL + 60 <= hy <= (by + bh) * CELL - 60):
        return None
    if ny and not (bx * CELL + 60 <= hx <= (bx + bw) * CELL - 60):
        return None
    best = None
    for line in lines:
        q = _cerca(line, (hx, hy))
        if best is None or math.dist(q, (hx, hy)) < math.dist(best, (hx, hy)):
            best = q
    if best is None or math.dist(best, (hx, hy)) > 240:
        return None
    return {"x": hx, "y": hy, "cls": 5, "edge": edge, "n": back, "de": m, "tipo": "enlace", "q": best}


def radiales(knox, out_dir, layout, boxes, occ, hole, salidas, ramas=(), bloqueo=None, unir=()):
    """Cada salida de pueblo sigue recta hasta lo que tiene enfrente al otro
    lado del hueco; si no hay nada útil, se engancha a la carretera más cercana
    ya trazada. Así salen carreteras que cruzan el campo, no que lo rodean."""
    g = Rejilla(hole, bloqueo)
    roads, ends = [], []
    usados = []

    def nodo_de(e):
        nx, ny = e["n"]
        e["dentro"] = (e["x"] + nx * STUB, e["y"] + ny * STUB)
        e["nodo"] = g.cercano(g.nodo(*e["dentro"]))
        return e["nodo"]

    def anadir(e):
        for f in ends:
            if math.dist((f["x"], f["y"]), (e["x"], e["y"])) < 60:
                return f
        ends.append(e)
        nodo_de(e)
        return e

    rng = random.Random(len(hole) * 7919 + min(hole)[0])
    # Primero las carreteras pedidas de pueblo a pueblo (o a un enlace)
    def centro(n):
        b = boxes[n]
        return ((b[0] + b[2] / 2) * CELL, (b[1] + b[3] / 2) * CELL)

    def candidatas(n, hacia):
        if n in layout["towns"]:
            return [f for f in salidas if f["de"] == n and f["cls"] >= 3]
        if n in boxes:
            return ramales_enlace(out_dir, n, boxes[n], hole, maxdist=520, cerca_de=hacia)
        return []
    for A, B in unir:
        if A not in boxes or B not in boxes:
            continue
        ca, cb = candidatas(A, centro(B)), candidatas(B, centro(A))
        pares = [(math.dist((a["x"], a["y"]), (b["x"], b["y"])) - 250 * (a["cls"] + b["cls"]), a, b)
                 for a in ca for b in cb
                 if math.dist((a["x"], a["y"]), (b["x"], b["y"])) > 2 * STUB + 60
                 and not any(math.dist((a["x"], a["y"]), (f["x"], f["y"])) < 60 for f in usados)
                 and not any(math.dist((b["x"], b["y"]), (f["x"], f["y"])) < 60 for f in usados)]
        if not pares:
            print(f"  (sin salidas para unir {A} con {B})")
            continue
        _, a, b = min(pares, key=lambda t: t[0])
        a, b = anadir(dict(a)), anadir(dict(b))
        g.atraer = False
        path = g.ruta(a["nodo"], {b["nodo"]})
        g.atraer = True
        if path is None:
            print(f"  (no hay paso para unir {A} con {B})")
            continue
        usados += [a, b]
        cls = max(min(a["cls"], 6), 4)
        line = [(a["x"], a["y"]), a["dentro"]] + [g.punto(n) for n in path] + [b["dentro"], (b["x"], b["y"])]
        line = ondular(_suavizar(simplificar(line)), g, rng, *AMPLITUD["carretera"])
        roads.append({"cls": cls, "line": line, "end": a})
        marcar(g, line, cls)
    pend = []
    for e in sorted(salidas, key=lambda e: -e["cls"]):
        if any(math.dist((e["x"], e["y"]), (f["x"], f["y"])) < 60 for f in usados):
            continue
        o = enfrente(knox, out_dir, layout, boxes, occ, hole, e, salidas) if e["cls"] >= 4 else None
        if o is None:
            pend.append(e)
            continue
        # dos salidas casi juntas que van al mismo sitio: con una carretera
        # basta; la segunda se engancha a ella (no dos paralelas)
        if any(math.dist((o["x"], o["y"]), (f["x"], f["y"])) < 400 for f in usados[1::2]) and \
                any(math.dist((e["x"], e["y"]), (f["x"], f["y"])) < 400 for f in usados[0::2]):
            pend.append(e)
            continue
        a, b = anadir(e), anadir(o)
        usados += [a, b]
        g.atraer = False
        path = g.ruta(a["nodo"], {b["nodo"]})
        g.atraer = True
        if path is None:
            continue
        cls = max(a["cls"], 4)
        line = [(a["x"], a["y"]), a["dentro"]] + [g.punto(n) for n in path] + [b["dentro"], (b["x"], b["y"])]
        line = ondular(_suavizar(simplificar(line)), g, rng, *AMPLITUD["carretera"])
        roads.append({"cls": cls, "line": line, "end": a})
        marcar(g, line, cls)
    # Las salidas sin nada enfrente (y las calles de los pueblos, que siguen
    # como caminos de tierra): a la carretera más cercana ya trazada o, si no
    # hay, al enlace más cercano con un ramal.
    ramas = [dict(r) for r in ramas]
    for r in ramas:
        nodo_de(r)
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points, unary_union
    for e in sorted(pend, key=lambda e: -e["cls"]):
        if any(math.dist((e["x"], e["y"]), (f["x"], f["y"])) < 60 for f in ends):
            continue
        camino = e["cls"] < 4
        a = anadir(e)
        goals = set(g.road)
        por_nodo = {}
        if not camino:
            for r in ramas:
                if r["de"] != e["de"] and math.dist((r["x"], r["y"]), (e["x"], e["y"])) > 2 * STUB + 60:
                    goals.add(r["nodo"])
                    por_nodo[r["nodo"]] = r
            if not g.road:
                # sin red todavía: también a la salida grande de otro pueblo
                for f in pend:
                    if f["de"] != e["de"] and f["cls"] >= 4 and f not in ends and \
                            math.dist((f["x"], f["y"]), (e["x"], e["y"])) > 2 * STUB + 60:
                        nodo_de(f)
                        goals.add(f["nodo"])
                        por_nodo[f["nodo"]] = f
        path = g.ruta(a["nodo"], goals) if goals else None
        if path is None or len(path) * R > (900 if camino else 3500):
            ends.remove(a)
            continue
        cls = 2 if camino else max(a["cls"], 4)
        line = [(a["x"], a["y"]), a["dentro"]] + [g.punto(n) for n in path]
        fin = por_nodo.get(path[-1])
        if fin is not None:
            fin = anadir(fin)
            line += [fin["dentro"], (fin["x"], fin["y"])]
            if fin["tipo"] == "enlace":
                ramas = [r for r in ramas if r["de"] != fin["de"]]
        elif roads:
            # acabar justo encima de la carretera a la que se engancha
            red = unary_union([LineString(r["line"]) for r in roads])
            q = nearest_points(red, Point(line[-1]))[0]
            line[-1] = (q.x, q.y)
        tipo = "camino" if camino else "carretera"
        line = ondular(_suavizar(simplificar(line)), g, rng, *AMPLITUD[tipo], fijo_final=fin is None)
        roads.append({"cls": cls, "line": line, "end": a})
        marcar(g, line, cls)
    return g, roads, ends


# ---------------------------------------------------------------------------
# Sitios de interés
# ---------------------------------------------------------------------------
# Cada sitio es una lista de piezas en tiles relativos a su esquina, con el
# lado que da a la carretera arriba (y = 0); se gira al colocarlo.

def _r(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def sitio(tipo, rng):
    """(ancho, fondo, piezas): piezas = (tipo de dibujo, anillo o línea, tags)."""
    P = []
    if tipo == "centro_comercial":
        W, D = 150, 105
        P.append(("commercial_land", _r(0, 0, W, D), {}))
        P.append(("parking", _r(10, 6, 130, 38), {}))
        P.append(("mall", _r(15, 50, 85, 45), {"name": "Centro Comercial", "building:levels": "2"}))
        P.append(("supermarket", _r(105, 50, 38, 30), {"name": "Hipermercado"}))
        P.append(("shop", _r(105, 84, 18, 14), {}))
        P.append(("shop", _r(125, 84, 18, 14), {}))
        P.append(("restaurant", _r(2, 8, 10, 9), {"name": "Hamburguesería"}))
        P.append(("restaurant", _r(138, 8, 10, 9), {"name": "Pizzería"}))
        P.append(("fuel", [(75, 3)], {}))
    elif tipo == "poligono":
        W, D = 160, 120
        P.append(("industrial_land", _r(0, 0, W, D), {}))
        P.append(("service", [(80, 0), (80, 115)], {}))
        P.append(("service", [(8, 60), (152, 60)], {}))
        for row, y in enumerate((8, 66)):
            for col, x in enumerate((6, 44, 88, 124)):
                w = rng.randint(28, 32)
                d = rng.randint(34, 46)
                if x == 88 and row == 0:
                    P.append(("garage", _r(x, y + 4, 20, 14), {"name": "Taller"}))
                    continue
                P.append(("warehouse", _r(x, y, w, min(d, 48)), {}))
        P.append(("fuel", [(150, 4)], {}))
    elif tipo == "base_militar":
        W, D = 170, 140
        P.append(("military_land", _r(0, 0, W, D), {}))
        ring = [(2, 2), (W - 2, 2), (W - 2, D - 2), (2, D - 2), (2, 2)]
        P.append(("fence", ring[:1] + [(W / 2 - 6, 2)], {}))          # puerta en el centro
        P.append(("fence", [(W / 2 + 6, 2)] + ring[1:4] + [(2, 2)], {}))
        P.append(("service", [(W / 2, 0), (W / 2, 120)], {}))
        P.append(("service", [(20, 70), (150, 70)], {}))
        P.append(("barracks", _r(W / 2 + 8, 8, 14, 10), {"name": "Puesto de guardia"}))
        for i, x in enumerate((12, 46, 104, 138)):
            P.append(("barracks", _r(x, 20, 26, 12), {"name": "Barracones"}))
            P.append(("barracks", _r(x, 40, 26, 12), {}))
        P.append(("warehouse", _r(12, 80, 44, 32), {"name": "Hangar"}))
        P.append(("warehouse", _r(110, 80, 44, 32), {"name": "Almacén de material"}))
        P.append(("parking", _r(62, 78, 22, 40), {}))
        P.append(("barracks", _r(90, 84, 14, 26), {"name": rng.choice(
            ["Comandancia", "Acuartelamiento", "Base Militar", "Centro de Mantenimiento"])}))
        P.append(("pitch", _r(60, 124, 50, 12), {}))
    elif tipo == "venta":
        W, D = 80, 55
        P.append(("parking", _r(4, 4, 46, 18), {}))
        P.append(("restaurant", _r(6, 26, 26, 16), {"name": "Venta"}))
        P.append(("hotel", _r(36, 28, 40, 12), {"name": "Hostal", "building:levels": "2"}))
        P.append(("pub", _r(56, 6, 14, 12), {}))
        P.append(("fuel", [(65, 22)], {}))
        if rng.random() < 0.5:
            P.append(("shop", _r(4, 44, 16, 10), {"name": "Armería", "shop": "weapons"}))
    elif tipo == "ocio":
        W, D = 110, 70
        P.append(("commercial_land", _r(0, 0, W, D), {}))
        P.append(("parking", _r(4, 4, 102, 20), {}))
        P.append(("restaurant", _r(6, 30, 22, 16), {"name": "Asador"}))
        P.append(("restaurant", _r(32, 30, 18, 14), {"name": "Restaurante"}))
        P.append(("cafe", _r(54, 30, 12, 10), {}))
        P.append(("pub", _r(70, 30, 16, 12), {"name": "Discoteca"}))
        P.append(("hotel", _r(6, 52, 50, 14), {"name": "Hotel", "building:levels": "3"}))
        P.append(("restaurant", _r(88, 30, 18, 14), {"name": "Mesón"}))
    elif tipo == "armeria":
        W, D = 50, 36
        P.append(("parking", _r(2, 2, 46, 12), {}))
        P.append(("shop", _r(4, 16, 20, 14), {"name": "Armería", "shop": "weapons"}))
        P.append(("shop", _r(27, 16, 18, 14), {"name": "Caza y Pesca", "shop": "weapons"}))
    elif tipo == "centro_visitantes":
        W, D = 90, 70
        P.append(("parking", _r(4, 4, 50, 22), {}))
        P.append(("library", _r(8, 30, 34, 20), {"name": "Centro de Visitantes"}))
        P.append(("restaurant", _r(48, 30, 16, 12), {"name": "Cafetería"}))
        P.append(("grass", _r(58, 4, 30, 60), {}))
        for k in range(6):
            P.append(("tree", [(62 + (k % 3) * 9, 10 + (k // 3) * 30)], {}))
        P.append(("shed", _r(70, 48, 8, 6), {"name": "Aseos"}))
    elif tipo == "casa_guarda":
        W, D = 40, 34
        P.append(("house", _r(4, 6, 13, 11), {"name": "Casa del guarda", "building:levels": "1"}))
        P.append(("barn", _r(20, 4, 16, 12), {}))
        P.append(("shed", _r(6, 22, 9, 7), {}))
        P.append(("fence", [(2, 2), (38, 2), (38, 32), (2, 32), (2, 2)], {}))
    elif tipo == "gasolinera":
        W, D = 40, 30
        P.append(("parking", _r(2, 2, 36, 14), {}))
        P.append(("shop", _r(10, 18, 16, 9), {"name": "Tienda"}))
        P.append(("fuel", [(20, 6)], {}))
    elif tipo == "puesto_forestal":
        W, D = 48, 42
        P.append(("parking", _r(2, 2, 26, 12), {}))
        P.append(("house", _r(4, 17, 16, 12), {"name": "Puesto forestal", "building:levels": "1"}))
        P.append(("garage", _r(23, 17, 15, 12), {"name": "Cochera de los forestales"}))
        P.append(("apartments", _r(33, 2, 11, 11), {"name": "Torre de vigilancia", "building:levels": "5"}))
        P.append(("shed", _r(4, 32, 9, 7), {}))
        P.append(("fence", [(W / 2 - 6, 1), (1, 1), (1, D - 1), (W - 1, D - 1), (W - 1, 1), (W / 2 + 6, 1)], {}))
    elif tipo == "aserradero":
        W, D = 84, 64
        P.append(("industrial_land", _r(0, 0, W, D), {}))
        P.append(("parking", _r(4, 4, 34, 16), {}))
        P.append(("warehouse", _r(6, 24, 34, 22), {"name": "Aserradero"}))
        P.append(("shed", _r(46, 6, 14, 12), {"name": "Secadero"}))
        P.append(("shed", _r(64, 6, 14, 12), {"name": "Secadero"}))
        P.append(("barn", _r(46, 24, 32, 16), {"name": "Almacén de madera"}))
        P.append(("house", _r(6, 49, 15, 11), {"name": "Oficina del aserradero"}))
        P.append(("garage", _r(46, 46, 20, 14), {"name": "Taller"}))
        P.append(("fence", [(W / 2 - 8, 1), (1, 1), (1, D - 1), (W - 1, D - 1), (W - 1, 1), (W / 2 + 8, 1)], {}))
    elif tipo == "refugio":
        W, D = 28, 24
        P.append(("house", _r(6, 6, 13, 11), {"name": "Refugio", "building:levels": "1"}))
        P.append(("tree", [(23, 8)], {}))
        P.append(("tree", [(23, 18)], {}))
    elif tipo == "molino":
        W, D = 36, 30
        P.append(("house", _r(4, 6, 17, 14), {"name": "Molino de Molemocho", "building:levels": "2"}))
        P.append(("shed", _r(24, 8, 9, 8), {}))
        P.append(("grass", _r(2, 22, 32, 6), {}))
    elif tipo == "observatorio":
        W, D = 20, 18
        P.append(("shed", _r(4, 5, 11, 8), {"name": "Observatorio de aves"}))
    elif tipo == "cortijo":
        W, D = 60, 50
        P.append(("house", _r(6, 8, 14, 11), {"building:levels": "2"}))
        P.append(("barn", _r(26, 6, 26, 16), {}))
        P.append(("barn", _r(6, 26, 20, 14), {}))
        P.append(("shed", _r(32, 30, 10, 8), {}))
        P.append(("orchard", _r(44, 26, 14, 22), {}))
    return W, D, P


# Qué va en cada hueco: por orden de preferencia, el sitio y a qué pueblo se
# acerca (None: donde quepa).
PLAN = [
    ("centro_comercial", "CiudadReal"),
    ("poligono", "CiudadReal"),
    ("base_militar", None),
    ("ocio", "CiudadReal"),
    ("poligono", None),
    ("venta", None),
    ("venta", None),
    ("gasolinera", None),
    ("gasolinera", None),
]
POR_HUECO = {0: ["base_militar", "poligono", "armeria", "venta", "gasolinera", "venta"],
             1: ["centro_comercial", "ocio", "poligono", "armeria", "venta", "gasolinera"],
             2: ["poligono", "venta", "gasolinera"],
             3: ["ocio", "gasolinera", "venta", "armeria"]}
# Lo que va en las zonas con tema propio
POR_TEMA = {"tablas": ["centro_visitantes", "venta", "casa_guarda"],
            "cabaneros": ["centro_visitantes", "casa_guarda", "casa_guarda", "casa_guarda", "venta", "armeria"],
            "aeropuerto": ["gasolinera", "venta"]}


def colocar_sitios(hole, rects, roads, boxes, idx, rng, tipos=None, ocupado=None, con_caminos=True):
    """Busca sitio junto a las carreteras para cada sitio de interés."""
    from shapely.geometry import LineString, Polygon, box
    from shapely.ops import unary_union
    tipos = POR_HUECO.get(idx, []) if tipos is None else tipos
    carreteras = unary_union([LineString(r["line"]).buffer(12) for r in roads]) if roads else Polygon()
    cr = boxes.get("CiudadReal")
    crc = ((cr[0] + cr[2] / 2) * CELL, (cr[1] + cr[3] / 2) * CELL) if cr else (0, 0)
    puestos = []
    tomado = ocupado.buffer(20) if ocupado is not None else Polygon()
    for tipo in tipos:
        W, D, piezas = sitio(tipo, rng)
        best = None
        for r in roads:
            if r["cls"] < 4:
                continue                # los sitios, junto a carreteras de verdad
            L = _largo(r["line"])
            for t in range(int(STUB + 30), int(L - STUB - 30), 25):
                pt = _tangente(r["line"], t)
                if pt is None:
                    continue
                (px, py), (ux, uy) = pt
                horiz = abs(ux) >= abs(uy)
                for side in (1, -1):
                    # normal a la carretera, redondeada al eje más cercano
                    if horiz:
                        nx, ny = 0, side
                    else:
                        nx, ny = side, 0
                    cx0, cy0 = px + nx * 16, py + ny * 16
                    if horiz:
                        x0 = cx0 - W / 2
                        y0 = cy0 if ny > 0 else cy0 - D
                        w_, d_ = W, D
                    else:
                        y0 = cy0 - W / 2
                        x0 = cx0 if nx > 0 else cx0 - D
                        w_, d_ = D, W
                    g = box(x0, y0, x0 + w_, y0 + d_)
                    dentro = any(rx * CELL + 8 <= x0 and x0 + w_ <= (rx + rw) * CELL - 8
                                 and ry * CELL + 8 <= y0 and y0 + d_ <= (ry + rh) * CELL - 8
                                 for rx, ry, rw, rh in rects)
                    if not dentro or g.intersects(carreteras) or g.intersects(tomado):
                        continue
                    c = g.centroid.coords[0]
                    if tipo in ("centro_comercial", "ocio", "poligono"):
                        cerca = math.dist(c, crc)          # junto a Ciudad Real
                    elif tipo == "base_militar":
                        cerca = -min(math.dist(c, ((b[0] + b[2] / 2) * CELL, (b[1] + b[3] / 2) * CELL))
                                     for n, b in boxes.items() if not n.startswith(("Enlace_", "Cruce_", "Relleno_")))
                    else:
                        cerca = rng.uniform(0, 1000)
                    if best is None or cerca < best[0]:
                        best = (cerca, g, (x0, y0, w_, d_), (nx, ny), (px, py), r["line"])
        if best is None:
            continue
        _, g, (x0, y0, w_, d_), (nx, ny), road_pt, rline = best
        tomado = tomado.union(g.buffer(20))
        feats = []

        def tr(p):
            # piezas en (u a lo largo del frente, v hacia dentro)
            u, v = p
            if abs(ny) > 0.5:            # carretera arriba o abajo del sitio
                x = x0 + u
                y = y0 + v if ny > 0 else y0 + d_ - v
            else:
                y = y0 + u
                x = x0 + v if nx > 0 else x0 + w_ - v
            return (x, y)

        for kind, ring, tags in piezas:
            feats.append((kind, [tr(p) for p in ring], tags))
        if tipo in ("gasolinera", "venta"):
            # una explanada asfaltada de la carretera al frente, con su
            # entrada y su salida en las dos puntas (no un caminito)
            a1, a2 = tr((3, 0)), tr((W - 3, 0))
            q1, q2 = _cerca(rline, a1), _cerca(rline, a2)
            feats.append(("parking", [a1, a2, q2, q1], {}))
            feats.append(("service", [q1, a1, tr((3, 8))], {"name": "Entrada"}))
            feats.append(("service", [q2, a2, tr((W - 3, 8))], {"name": "Salida"}))
        else:
            # la entrada: un ramal desde la carretera hasta el frente del sitio
            ent = tr((W / 2, 0))
            feats.append(("service", [road_pt, ent], {}))
        puestos.append({"tipo": tipo, "geom": g, "feats": feats})
    if con_caminos:
        puestos += caminos(rects, roads, tomado, rng)
    return puestos


def caminos(rects, roads, tomado, rng):
    """Caminos de tierra que salen de las carreteras hacia dentro del campo,
    con un cortijo al final: lo que hace que el interior del hueco no sea una
    pradera vacía."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    otras = unary_union([LineString(r["line"]).buffer(45) for r in roads])
    out = []

    def en_un_rect(g, m):
        x0, y0, x1, y1 = g.bounds
        return any(rx * CELL + m <= x0 and x1 <= (rx + rw) * CELL - m
                   and ry * CELL + m <= y0 and y1 <= (ry + rh) * CELL - m for rx, ry, rw, rh in rects)

    hechos = []
    for r in roads:
        L = _largo(r["line"])
        t = STUB + 80 + rng.uniform(0, 120)
        while t < L - STUB - 80:
            pt = _tangente(r["line"], t)
            t += rng.uniform(170, 330)
            if pt is None:
                continue
            (px, py), (ux, uy) = pt
            for side in rng.sample((1, -1), 2):
                nx, ny = -uy * side, ux * side
                largo = rng.uniform(140, 360)
                # un camino que se tuerce: sale casi recto y va doblando
                giro = rng.uniform(-0.7, 0.7)
                pts = [(px, py)]
                ang = math.atan2(ny, nx)
                x, y = px, py
                for k in range(int(largo // 20)):
                    a = ang + giro * (k / max(1, largo // 20)) + rng.uniform(-0.15, 0.15)
                    x, y = x + 20 * math.cos(a), y + 20 * math.sin(a)
                    pts.append((x, y))
                pts = _chaikin(pts, 2)
                b = pts[-1]
                W, D, piezas = sitio("cortijo", rng)
                cx, cy = b
                g = box(cx - W / 2, cy - D / 2, cx + W / 2, cy + D / 2)
                linea = LineString(pts)
                todo = linea.buffer(6).union(g)
                lejos = linea.difference(Point(px, py).buffer(55))
                if not en_un_rect(todo, 10) or todo.intersects(tomado) or \
                        lejos.intersects(otras) or g.intersects(otras):
                    continue
                if any(todo.distance(h) < 60 for h in hechos):
                    continue
                hechos.append(todo)
                x0, y0 = cx - W / 2, cy - D / 2
                feats = [("track", pts, {})]
                for kind, ring, tags in piezas:
                    feats.append((kind, [(x0 + u, y0 + v) for u, v in ring], tags))
                out.append({"tipo": "cortijo", "geom": g, "feats": feats})
                break
    return out


def destinos(g, rects, roads, sitios, rng, tipos, evitar=None, junto_a=None):
    """Sitios apartados de la carretera (puestos forestales, aserraderos,
    refugios, el molino, observatorios) con su camino de tierra, que va
    buscando el terreno por la rejilla hasta la carretera más cercana.
    `junto_a`: {tipo: geometría} para los que tienen que estar al lado de
    algo (el molino, junto al río)."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import nearest_points, unary_union
    from shapely.prepared import prep
    if not roads or not g.road:
        return []
    zona = _zona(rects).buffer(-30)
    vias = unary_union([LineString(r["line"]) for r in roads])
    ocup = unary_union([st["geom"].buffer(40) for st in sitios] + [_P0()])
    if evitar is not None:
        ocup = ocup.union(evitar)
    # nodos por los que no puede ir el camino (agua)
    bloq = set()
    if evitar is not None and not evitar.is_empty:
        pe = prep(evitar)
        x0, y0, x1, y1 = evitar.bounds
        n0, n1 = g.nodo(x0, y0), g.nodo(x1, y1)
        for i in range(n0[0], n1[0] + 1):
            for j in range(n0[1], n1[1] + 1):
                if (i, j) in g.ok and pe.contains(_pt(*g.punto((i, j)))):
                    bloq.add((i, j))
    bx0, by0, bx1, by1 = zona.bounds
    out, puestos = [], []
    for tipo in tipos:
        W, D, piezas = sitio(tipo, rng)
        mejor = None
        for _ in range(400):
            cx, cy = rng.uniform(bx0, bx1), rng.uniform(by0, by1)
            caja = box(cx - W / 2 - 4, cy - W / 2 - 4, cx + W / 2 + 4, cy + W / 2 + 4)
            if not zona.contains(caja) or caja.intersects(ocup):
                continue
            dr = vias.distance(Point(cx, cy))
            if not 200 <= dr <= 800:
                continue
            if junto_a and tipo in junto_a and junto_a[tipo].distance(caja) > 60:
                continue
            score = -min([math.dist((cx, cy), q) for q in puestos] + [3000]) + rng.uniform(0, 300)
            if mejor is None or score < mejor[0]:
                mejor = (score, cx, cy)
        if mejor is None:
            continue
        _, cx, cy = mejor
        # el frente mira a la carretera más cercana
        q = nearest_points(vias, Point(cx, cy))[0]
        sx, sy = q.x - cx, q.y - cy
        if abs(sx) >= abs(sy):
            nx, ny = (-1 if sx > 0 else 1), 0          # de la carretera al sitio
            w_, d_ = D, W
        else:
            nx, ny = 0, (-1 if sy > 0 else 1)
            w_, d_ = W, D
        x0, y0 = cx - w_ / 2, cy - d_ / 2

        def tr(p):
            u, v = p
            if ny:
                return (x0 + u, y0 + v if ny > 0 else y0 + d_ - v)
            return (x0 + v if nx > 0 else x0 + w_ - v, y0 + u)
        ent = tr((W / 2, 0))
        fuera = (ent[0] - nx * 10, ent[1] - ny * 10)
        n0 = g.cercano(g.nodo(*fuera))
        path = g.ruta(n0, set(g.road) - bloq, ocupado=bloq)
        if not path or len(path) * R > 1600:
            continue
        line = [ent, fuera] + [g.punto(n) for n in path]
        p_ = nearest_points(vias, Point(line[-1]))[0]
        line[-1] = (p_.x, p_.y)
        line = ondular(_suavizar(simplificar(line)), g, rng, *AMPLITUD["camino"], fijo_final=False)
        geom = box(x0, y0, x0 + w_, y0 + d_)
        feats = [("track", line, {})] + [(k, [tr(p) for p in ring], tags) for k, ring, tags in piezas]
        out.append({"tipo": tipo, "geom": geom, "feats": feats})
        puestos.append((cx, cy))
        ocup = ocup.union(geom.buffer(60)).union(LineString(line).buffer(12))
    return out


# ---------------------------------------------------------------------------
# Paisaje: parcelas irregulares, bosquetes, setos, un arroyo y alguna aldea
# ---------------------------------------------------------------------------
CULTIVOS = [("farmland", 32), ("orchard", 24), ("scrub", 12), ("grass", 6), ("forest", 6), (None, 20)]


def _P0():
    from shapely.geometry import Point
    return Point(0, 0).buffer(0.01)


def _zona(rects):
    from shapely.geometry import box
    from shapely.ops import unary_union
    return unary_union([box(x * CELL, y * CELL, (x + w) * CELL, (y + h) * CELL) for x, y, w, h in rects])


def aldea(hole, rects, roads, sitios, boxes, rng):
    """Un caserío junto a una carretera, lejos de los pueblos: casas a los dos
    lados, una calle que sale de la carretera, la iglesia y el bar."""
    from shapely.geometry import LineString, Point, box
    from shapely.ops import unary_union
    if len(hole) < 90:
        return []
    zona = _zona(rects).buffer(-15)
    vias = unary_union([LineString(r["line"]).buffer(9) for r in roads])
    ocup = unary_union([st["geom"].buffer(60) for st in sitios]) if sitios else Point(0, 0).buffer(0)
    centros = [((b[0] + b[2] / 2) * CELL, (b[1] + b[3] / 2) * CELL) for n, b in boxes.items()
               if not n.startswith(("Enlace_", "Cruce_", "Relleno_"))]
    mejor = None
    for r in roads:
        if r["cls"] < 4:
            continue
        L = _largo(r["line"])
        for t in range(int(STUB + 150), int(L - STUB - 150), 40):
            (px, py), (ux, uy) = _tangente(r["line"], t)
            lejos = min(math.dist((px, py), c) for c in centros)
            if lejos < 700 or Point(px, py).buffer(170).intersects(ocup) or not zona.contains(Point(px, py).buffer(170)):
                continue
            if mejor is None or abs(lejos - 1100) < abs(mejor[0] - 1100):
                mejor = (lejos, (px, py), (ux, uy), r)
    if mejor is None:
        return []
    _, (px, py), (ux, uy), r = mejor
    feats = []
    casas = []
    horiz = abs(ux) >= abs(uy)
    # una calle que sale de la carretera hacia un lado
    side = rng.choice((1, -1))
    nx, ny = (0, side) if horiz else (side, 0)
    calle = [(px, py), (px + nx * 150, py + ny * 150)]
    calle_g = LineString(calle)
    feats.append(("residential", calle, {}))
    feats.append(("plaza", [(px + nx * 60 - 14, py + ny * 60 - 14), (px + nx * 60 + 14, py + ny * 60 - 14),
                            (px + nx * 60 + 14, py + ny * 60 + 14), (px + nx * 60 - 14, py + ny * 60 + 14)], {}))
    tomado = vias.union(calle_g.buffer(9)).union(box(px + nx * 60 - 16, py + ny * 60 - 16, px + nx * 60 + 16, py + ny * 60 + 16))
    especiales = ["church", "pub", "shop"]

    def poner(cx, cy, ax, ay):
        # una casa con la fachada a la calle (ax, ay: hacia la calle)
        w, d = rng.uniform(9, 13), rng.uniform(10, 14)
        if abs(ax) > 0.5:
            g = box(cx - d / 2, cy - w / 2, cx + d / 2, cy + w / 2)
        else:
            g = box(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
        if g.intersects(tomado) or not zona.contains(g):
            return False
        kind = especiales.pop(0) if especiales and rng.random() < 0.3 else "house"
        if kind == "church":
            g = g.buffer(5, join_style=2)
            if g.intersects(tomado) or not zona.contains(g):
                kind = "house"
                g = g.buffer(-5, join_style=2)
        casas.append((kind, g))
        return True

    # a lo largo de la calle, a los dos lados
    for k in range(4):
        d = 25 + k * 30
        for lado in (1, -1):
            mx, my = (lado, 0) if horiz else (0, lado)
            cx, cy = px + nx * d + mx * 18, py + ny * d + my * 18
            if poner(cx, cy, -mx, -my):
                tomado = tomado.union(casas[-1][1].buffer(3))
    # a lo largo de la carretera, unas pocas
    for k in range(-3, 4):
        if k == 0:
            continue
        for lado in (1, -1):
            if rng.random() < 0.35:
                continue
            mx, my = ((0, lado) if horiz else (lado, 0))
            cx, cy = px + ux * k * 28 + mx * 22, py + uy * k * 28 + my * 22
            if poner(cx, cy, -mx, -my):
                tomado = tomado.union(casas[-1][1].buffer(3))
    for kind, g in casas:
        tags = {"building:levels": str(rng.choice((1, 2, 2)))}
        if kind == "church":
            tags = {"name": "Ermita", "building:levels": "1"}
        feats.append((kind, list(g.exterior.coords)[:-1], tags))
    if len(casas) < 6:
        return []
    geom = unary_union([g for _, g in casas] + [calle_g.buffer(10)]).envelope
    return [{"tipo": "aldea", "geom": geom, "feats": feats}]


def paisaje(hole, rects, roads, sitios, rng, cultivos=None, manchas_por=12, dehesa=0.0, evitar=None):
    """[(tipo, geometría)] del campo de todo el hueco, en tiles del mundo.
    `dehesa`: árboles sueltos por cada 1000 tiles² de pasto (encinas)."""
    cultivos = cultivos or CULTIVOS
    from shapely.geometry import LineString, MultiPoint, Point, Polygon
    from shapely.ops import unary_union, voronoi_diagram
    zona = _zona(rects)
    vias = unary_union([LineString(r["line"]).buffer(16 if r["cls"] >= 4 else 7) for r in roads]
                       + [LineString(p).buffer(6) for st in sitios for k, p, _ in st["feats"]
                          if k in ("track", "service", "residential") and len(p) > 1])
    ocup = unary_union([st["geom"].buffer(10) for st in sitios]) if sitios else Polygon()
    if evitar is not None:
        ocup = ocup.union(evitar)
    libre = zona.buffer(-4).difference(vias).difference(ocup)
    out = []
    # bosquetes: manchas de encina y pino hechas de círculos juntos
    x0, y0, x1, y1 = zona.bounds
    manchas = []
    for _ in range(max(2, len(hole) // manchas_por)):
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
        if not zona.contains(Point(cx, cy)):
            continue
        circ = [Point(cx + rng.gauss(0, 70), cy + rng.gauss(0, 70)).buffer(rng.uniform(25, 65), 8)
                for _ in range(rng.randint(5, 14))]
        manchas.append(unary_union(circ).simplify(4))
    bosque = unary_union(manchas).intersection(libre) if manchas else Polygon()
    for g in getattr(bosque, "geoms", [bosque]):
        if g.geom_type == "Polygon" and g.area > 800:
            out.append(("forest", g))
    # parcelas: un mosaico irregular (Voronoi) sobre todo el campo
    pts = []
    paso = 150
    for gx in range(int(x0), int(x1), paso):
        for gy in range(int(y0), int(y1), paso):
            pts.append((gx + rng.uniform(0, paso), gy + rng.uniform(0, paso)))
    celdas = voronoi_diagram(MultiPoint(pts), envelope=zona.buffer(50))
    resto = libre.difference(bosque.buffer(6)) if not bosque.is_empty else libre
    kinds, pesos = zip(*cultivos)
    for c in celdas.geoms:
        g = c.intersection(resto).buffer(-3)
        for q in getattr(g, "geoms", [g]):
            if q.geom_type != "Polygon" or q.area < 1500:
                continue
            kind = rng.choices(kinds, pesos)[0]
            if kind:
                out.append((kind, q.simplify(2)))
            if dehesa and kind in ("grass", None):
                # encinas sueltas: la dehesa
                n = int(q.area / 1000 * dehesa)
                bx0, by0, bx1, by1 = q.bounds
                for _ in range(n):
                    p_ = Point(rng.uniform(bx0, bx1), rng.uniform(by0, by1))
                    if q.contains(p_):
                        out.append(("tree", p_))
            # un seto en uno de sus lados, a veces
            if rng.random() < 0.25:
                ring = list(q.exterior.coords)
                i = rng.randrange(len(ring) - 1)
                out.append(("hedge", LineString([ring[i], ring[i + 1]])))
    # un arroyo que cruza el hueco, con árboles en la orilla
    if len(hole) >= 40:
        ang = rng.uniform(0, 6.28)
        cx, cy = zona.centroid.x, zona.centroid.y
        largo = max(x1 - x0, y1 - y0)
        pts = []
        x, y = cx - math.cos(ang) * largo, cy - math.sin(ang) * largo
        a = ang
        for k in range(int(2 * largo // 15)):
            a = ang + 0.6 * math.sin(k / 9.0 + rng.uniform(-0.2, 0.2)) + rng.uniform(-0.1, 0.1)
            x, y = x + 15 * math.cos(a), y + 15 * math.sin(a)
            pts.append((x, y))
        arroyo = LineString(_chaikin(pts, 2)).intersection(zona.buffer(-10).difference(vias.buffer(4)).difference(ocup))
        for seg in getattr(arroyo, "geoms", [arroyo]):
            if seg.geom_type == "LineString" and seg.length > 80:
                out.append(("stream", seg))
                for d in range(0, int(seg.length), 18):
                    p = seg.interpolate(d)
                    for lado in (1, -1):
                        if rng.random() < 0.6:
                            out.append(("tree", Point(p.x + lado * rng.uniform(3, 7), p.y + rng.uniform(-5, 5))))
    return out



# ---------------------------------------------------------------------------
# Aldeas con sus manzanas
# ---------------------------------------------------------------------------
NOMBRES_ALDEA = ["Valdelobos", "El Torno", "Las Casillas", "Los Pozuelos", "La Poblachuela",
                 "Casas de Benítez", "El Hoyo", "La Alameda", "Peralvillo", "Las Huertas",
                 "Navalrincón", "Fuentecilla", "Los Corrales", "El Robledo", "Valdeazores",
                 "La Cañadilla", "Los Molinos", "Las Labores", "El Villar", "Navalagrulla"]


def aldea_manzanas(px, py, ux, uy, side, rng, nombre):
    """Una aldea de dos o tres manzanitas a un lado de la carretera: calles,
    una placita con la iglesia, el bar, la tienda, la armería y el
    ayuntamiento, y casas en hilera alrededor de cada manzana.
    Devuelve (features, huella) en tiles del mundo, o None."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    horiz = abs(ux) >= abs(uy)
    A = (1, 0) if horiz else (0, 1)            # a lo largo de la carretera
    B = (0, side) if horiz else (side, 0)      # hacia dentro

    def W(a, b):
        return (px + A[0] * a + B[0] * b, py + A[1] * a + B[1] * b)

    def caja(a0, b0, a1, b1):
        (x0, y0), (x1, y1) = W(a0, b0), W(a1, b1)
        return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    nb = rng.choice((2, 3))
    ancho = rng.uniform(52, 66)
    fondo = rng.uniform(58, 72)
    b0, b1 = 16, 16 + fondo                      # manzanas entre b0 y b1
    calles_a = [-(nb * (ancho + 12)) / 2 + k * (ancho + 12) for k in range(nb + 1)]
    feats = []
    for a in calles_a:
        feats.append(("residential", [W(a, 0), W(a, b1 + 7)], {}))
    feats.append(("residential", [W(calles_a[0], b1 + 7), W(calles_a[-1], b1 + 7)], {}))
    huella = caja(calles_a[0] - 12, 8, calles_a[-1] + 12, b1 + 16)
    plaza_k = nb // 2
    especiales = [("church", {"name": "Iglesia", "building:levels": "2"}),
                  ("pub", {"name": "Bar"}),
                  ("shop", {"name": "Tienda"}),
                  ("shop", {"name": "Armería", "shop": "weapons"}),
                  ("townhall", {"name": f"Ayuntamiento de {nombre}", "building:levels": "2"})]
    tomado = []
    for k in range(nb):
        a0, a1 = calles_a[k] + 6, calles_a[k + 1] - 6
        bb0, bb1 = b0, b1
        if k == plaza_k:
            # la placita en la esquina que da a la carretera
            pl = caja(a0, bb0, a0 + 28, bb0 + 26)
            feats.append(("plaza", list(pl.exterior.coords)[:-1], {}))
            tomado.append(pl)
            # la iglesia mirando a la plaza
            ig = caja(a0 + 30, bb0, a0 + 30 + 16, bb0 + 26)
            if a0 + 46 < a1:
                kind, tags = especiales.pop(0)
                feats.append((kind, list(ig.exterior.coords)[:-1], tags))
                tomado.append(ig)
        # casas en hilera por los cuatro lados de la manzana
        lados = [((a0, bb0), (1, 0), (0, 1), a1 - a0), ((a1, bb0), (0, 1), (-1, 0), bb1 - bb0),
                 ((a1, bb1), (-1, 0), (0, -1), a1 - a0), ((a0, bb1), (0, -1), (1, 0), bb1 - bb0)]
        for (sa, sb), (da, db), (na, nb_), L in lados:
            t = 0
            while t < L - 8:
                w = min(rng.uniform(9, 13), L - t)
                d = rng.uniform(11, 14)
                p0 = (sa + da * t, sb + db * t)
                p1 = (p0[0] + da * w + na * d, p0[1] + db * w + nb_ * d)
                g = caja(min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))
                t += w
                if w < 8 or any(g.intersection(o).area > 4 for o in tomado):
                    continue
                if especiales and k == plaza_k and rng.random() < 0.6:
                    kind, tags = especiales.pop(0)
                else:
                    kind, tags = "house", {"building:levels": str(rng.choice((1, 2, 2)))}
                feats.append((kind, list(g.exterior.coords)[:-1], tags))
                tomado.append(g)
    # lo que no haya cabido junto a la plaza, en la carretera, enfrente
    for i, (kind, tags) in enumerate(especiales):
        a = calles_a[plaza_k] + 10 + i * 20
        g = caja(a, -14, a + 16, -28)
        feats.append((kind, list(g.exterior.coords)[:-1], tags))
        huella = unary_union([huella, g.buffer(4)])
    return feats, huella


def colocar_aldea(roads, permitido, ocupado, centros, rng, nombre, lejos_min=550, objetivo=1000):
    """Busca junto a una carretera sitio para una aldea."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    vias = unary_union([LineString(r["line"]).buffer(10) for r in roads]) if roads else None
    mejor = None
    for ri, r in enumerate(roads):
        if r["cls"] < 4:
            continue
        L = _largo(r["line"])
        otras = unary_union([LineString(o["line"]).buffer(10) for j, o in enumerate(roads) if j != ri]) \
            if len(roads) > 1 else None
        for t in range(int(STUB + 160), int(L - STUB - 160), 50):
            pt = _tangente(r["line"], t)
            if pt is None:
                continue
            (px, py), (ux, uy) = pt
            # solo en tramos casi rectos y casi alineados con la rejilla
            if min(abs(ux), abs(uy)) > 0.25:
                continue
            lej = min(math.dist((px, py), c) for c in centros) if centros else 9999
            if lej < lejos_min:
                continue
            for side in (1, -1):
                res = aldea_manzanas(px, py, ux, uy, side, random.Random(rng.random()), nombre)
                feats, huella = res
                if not permitido.contains(huella):
                    continue
                if ocupado is not None and huella.intersects(ocupado):
                    continue
                if otras is not None and huella.intersects(otras):
                    continue
                # la propia carretera no puede pasar por dentro de la aldea
                if vias is not None and huella.buffer(-12).intersects(LineString(r["line"])):
                    continue
                score = abs(lej - objetivo) + rng.uniform(0, 150)
                if mejor is None or score < mejor[0]:
                    mejor = (score, feats, huella)
    if mejor is None:
        return None
    return {"tipo": "aldea", "geom": mejor[2], "feats": mejor[1], "nombre": nombre}


# ---------------------------------------------------------------------------
# Carreteras transversales: unen entre sí las que cruzan el hueco
# ---------------------------------------------------------------------------

def transversales(g, roads, rng, maximo=2):
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points
    mayores = [r for r in roads if r["cls"] >= 4 and _largo(r["line"]) > 400]
    pares = []
    for i, a in enumerate(mayores):
        for b in mayores[i + 1:]:
            d = LineString(a["line"]).distance(LineString(b["line"]))
            if 250 < d < 1500:
                pares.append((d, a, b))
    rng.shuffle(pares)
    out = []
    for d, a, b in pares:
        if len(out) >= maximo:
            break
        la, lb = LineString(a["line"]), LineString(b["line"])
        pa = la.interpolate(rng.uniform(0.3, 0.7), normalized=True)
        na = g.nodo(pa.x, pa.y)
        if na not in g.ok:
            continue
        goals = set()
        for k in range(0, int(lb.length), 8):
            q = lb.interpolate(k)
            n = g.nodo(q.x, q.y)
            if n in g.ok:
                goals.add(n)
        g.atraer = False
        path = g.ruta(na, goals)
        g.atraer = True
        if not path or len(path) * R > 2 * d + 500:
            continue
        pts = [(pa.x, pa.y)] + [g.punto(n) for n in path]
        q = nearest_points(lb, Point(pts[-1]))[0]
        pts[-1] = (q.x, q.y)
        line = ondular(_suavizar(simplificar(pts)), g, rng, *AMPLITUD["carretera"], fijo_final=False)
        r = {"cls": 4, "line": line, "end": None}
        out.append(r)
        marcar(g, line, 4)
    return out


# ---------------------------------------------------------------------------
# Zonas con tema: Tablas de Daimiel, Cabañeros, el aeropuerto
# ---------------------------------------------------------------------------
ZONAS_EXTRA = [
    # Zonas que no son huecos cerrados: se rellenan las celdas libres del
    # rectángulo (x, y, ancho, alto en celdas). `unir`: carreteras que tienen
    # que salir sí o sí entre esos dos pueblos (o pueblo y enlace).
    {"nombre": "Cabaneros", "rect": (63, 3, 10, 9), "tema": "cabaneros"},
    {"nombre": "Aeropuerto", "rect": (88, 34, 10, 7), "tema": "aeropuerto"},
    {"nombre": "Montiel", "rect": (98, 23, 27, 22), "tema": None,
     "tipos": ["base_militar", "poligono", "venta", "gasolinera", "armeria", "venta", "gasolinera"],
     "unir": [("Almagro", "Infantes"), ("Bolanos", "Villahermosa"), ("Infantes", "Villahermosa")]},
    {"nombre": "SurOeste", "rect": (66, 38, 17, 21), "tema": None,
     "tipos": ["base_militar", "venta", "gasolinera", "armeria", "ocio"],
     "unir": [("Puertollano", "Enlace_Villamayor_CaracuelDeCalatrava"),
              ("Puertollano", "Enlace_Argamasilla_Villamayor")]},
    {"nombre": "SurEste", "rect": (84, 41, 14, 18), "tema": None,
     "tipos": ["poligono", "venta", "gasolinera", "ocio", "armeria"],
     "unir": [("Puertollano", "Enlace_Puertollano_Argamasilla")]},
]


def puertas(zonas):
    """Donde dos zonas se tocan, un punto del borde por el que pasa una
    carretera de una a otra (las dos mitades salen rectas del mismo punto)."""
    out = {z["nombre"]: [] for z in zonas}
    k = 0
    for i, A in enumerate(zonas):
        for B in zonas[i + 1:]:
            lados = {}
            for (x, y) in A["hole"]:
                for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if (x + dx, y + dy) in B["hole"]:
                        if dx:
                            key = ("v", max(x, x + dx), (-dx, 0))     # n hacia A
                            lados.setdefault(key, []).append(y)
                        else:
                            key = ("h", max(y, y + dy), (0, -dy))
                            lados.setdefault(key, []).append(x)
            mejor = None
            for (orient, linea, nA), pos in lados.items():
                pos = sorted(pos)
                run = [pos[0]]
                for q in pos[1:] + [None]:
                    if q is not None and q == run[-1] + 1:
                        run.append(q)
                        continue
                    if mejor is None or len(run) > len(mejor[3]):
                        mejor = (orient, linea, nA, list(run))
                    if q is not None:
                        run = [q]
            if mejor is None:
                continue
            orient, linea, nA, run = mejor
            mid = (run[0] + len(run) / 2) * CELL
            p = (linea * CELL, mid) if orient == "v" else (mid, linea * CELL)
            nB = (-nA[0], -nA[1])
            if not (_lejos_de_esquina(p, nA, A["hole"]) and _lejos_de_esquina(p, nB, B["hole"])):
                continue
            k += 1
            for Z, n, otra in ((A, nA, B), (B, nB, A)):
                out[Z["nombre"]].append({"x": p[0], "y": p[1], "cls": 5, "edge": "puerta", "n": n,
                                         "de": f"puerta {otra['nombre']}", "tipo": "puerta", "id": k})
            print(f"  puerta {k}: {A['nombre']} - {B['nombre']} en {p[0]:.0f},{p[1]:.0f}")
    return out


def conectar(g, roads, ends, pend, rng):
    """Engancha cada punto pendiente (puertas, ramales) a la red de la zona;
    si la zona aún no tiene carreteras, los une entre ellos. Devuelve los
    que no se han podido enganchar."""
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points, unary_union
    fallan = []
    hechos = []
    for e in pend:
        nx, ny = e["n"]
        e["dentro"] = (e["x"] + nx * STUB, e["y"] + ny * STUB)
        e["nodo"] = g.cercano(g.nodo(*e["dentro"]))
    pend = sorted(pend, key=lambda e: -e["cls"])
    for e in pend:
        if e in hechos:
            continue
        fin = None
        if g.road:
            path = g.ruta(e["nodo"], set(g.road))
        else:
            otros = [f for f in pend if f is not e and f not in hechos and f not in fallan]
            if not otros:
                fallan.append(e)
                continue
            g.atraer = False
            path = g.ruta(e["nodo"], {f["nodo"] for f in otros})
            g.atraer = True
            if path:
                fin = next(f for f in otros if f["nodo"] == path[-1])
        if not path or len(path) * R > 4000:
            print(f"    {e['de']} ({e['x']:.0f},{e['y']:.0f}): "
                  + ("sin camino" if not path else f"camino de {len(path) * R} tiles"))
            fallan.append(e)
            continue
        line = [(e["x"], e["y"]), e["dentro"]] + [g.punto(n) for n in path]
        if fin is not None:
            line += [fin["dentro"], (fin["x"], fin["y"])]
            hechos.append(fin)
            ends.append(fin)
        elif roads:
            red = unary_union([LineString(r["line"]) for r in roads])
            q = nearest_points(red, Point(line[-1]))[0]
            line[-1] = (q.x, q.y)
        line = ondular(_suavizar(simplificar(line)), g, rng, *AMPLITUD["carretera"], fijo_final=fin is not None)
        roads.append({"cls": 5, "line": line, "end": e, "puerta": e.get("id"),
                      "puerta_fin": fin.get("id") if fin else None})
        marcar(g, line, 5)
        hechos.append(e)
        ends.append(e)
    return fallan


def aeropuerto(rects):
    """El Aeropuerto Central de Ciudad Real, en pequeño: pista, calle de
    rodaje, plataforma, terminal, torre, hangares, bomberos y aparcamiento,
    todo vallado. Devuelve (sitio, zona bloqueada para las carreteras,
    punto de la entrada)."""
    from shapely.geometry import box
    x0 = min(r[0] for r in rects) * CELL + 250
    x1 = max(r[0] + r[2] for r in rects) * CELL - 250
    y0 = min(r[1] for r in rects) * CELL + 170
    y1 = y0 + 720
    xm = (x0 + x1) / 2
    F = []
    rect = lambda a, b, c, d: [(a, b), (c, b), (c, d), (a, d)]
    F.append(("grass", rect(x0, y0, x1, y1), {}))
    pista_y = y0 + 190
    F.append(("primary", [(x0 + 120, pista_y), (x1 - 120, pista_y)], {"name": "Pista 10/28", "width": "30"}))
    rod_y = y0 + 320
    F.append(("secondary", [(x0 + 260, rod_y), (x1 - 260, rod_y)], {"name": "Calle de rodaje", "width": "15"}))
    for xx in (x0 + 260, xm - 120, xm + 120, x1 - 260):
        F.append(("secondary", [(xx, pista_y), (xx, rod_y)], {"width": "15"}))
    F.append(("parking", rect(xm - 330, rod_y + 14, xm + 330, rod_y + 140), {}))
    F.append(("mall", rect(xm - 150, rod_y + 150, xm + 150, rod_y + 205),
              {"name": "Terminal del Aeropuerto Central", "building:levels": "2"}))
    F.append(("apartments", rect(xm + 190, rod_y + 160, xm + 204, rod_y + 174),
              {"name": "Torre de control", "building:levels": "8"}))
    for k in range(3):
        hx = xm + 380 + k * 95
        F.append(("warehouse", rect(hx, rod_y + 14, hx + 80, rod_y + 70), {"name": "Hangar"}))
    F.append(("fire", rect(xm - 470, rod_y + 20, xm - 430, rod_y + 50), {"name": "Bomberos del aeropuerto"}))
    F.append(("police", rect(xm - 210, rod_y + 160, xm - 180, rod_y + 182), {"name": "Guardia Civil"}))
    F.append(("parking", rect(xm - 260, rod_y + 222, xm + 260, rod_y + 330), {}))
    # la entrada: una calle de verdad hasta la terminal, con el carril de
    # dejar viajeros delante de la puerta
    F.append(("secondary", [(xm, y1 + 30), (xm, rod_y + 214)], {"name": "Avenida del Aeropuerto"}))
    F.append(("secondary", [(xm - 170, rod_y + 214), (xm + 170, rod_y + 214)], {}))
    F.append(("garage", rect(xm - 330, rod_y + 340, xm - 290, rod_y + 362), {"name": "Alquiler de coches"}))
    F.append(("fuel", [(xm + 640, rod_y + 90)], {}))
    F.append(("restaurant", rect(xm + 220, rod_y + 230, xm + 250, rod_y + 255), {"name": "Restaurante"}))
    F.append(("hotel", rect(xm + 280, rod_y + 222, xm + 340, rod_y + 250), {"name": "Hotel Aeropuerto", "building:levels": "4"}))
    # la valla, con la puerta en la entrada
    F.append(("fence", [(xm - 12, y1), (x0, y1), (x0, y0), (x1, y0), (x1, y1), (xm + 12, y1)], {}))
    huella = box(x0, y0, x1, y1)
    entrada = (xm, y1 + 30)
    return {"tipo": "aeropuerto", "geom": huella, "feats": F}, huella.buffer(25), entrada


def tablas(rects, roads, sitios, rng):
    """Las Tablas de Daimiel: lagunas, carrizal, el río serpenteando entre
    ellas, pasarelas de madera con observatorios."""
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    zona = _zona(rects)
    vias = unary_union([LineString(r["line"]).buffer(22) for r in roads]) if roads else Point(0, 0).buffer(0)
    ocup = unary_union([st["geom"].buffer(25) for st in sitios]) if sitios else Point(0, 0).buffer(0)
    libre = zona.buffer(-40).difference(vias).difference(ocup)
    if libre.is_empty:
        return [], []
    x0, y0, x1, y1 = libre.bounds
    lag = []
    centros = []
    for _ in range(14):
        cx, cy = rng.uniform(x0, x1), rng.uniform(y0, y1)
        if not libre.contains(Point(cx, cy)) or any(math.dist((cx, cy), c) < 220 for c in centros):
            continue
        centros.append((cx, cy))
        circ = [Point(cx + rng.gauss(0, 45), cy + rng.gauss(0, 30)).buffer(rng.uniform(35, 90), 10)
                for _ in range(rng.randint(4, 9))]
        lag.append(unary_union(circ))
        if len(centros) >= 6:
            break
    agua = unary_union(lag).intersection(libre.buffer(-20)) if lag else Point(0, 0).buffer(0)
    carrizal = agua.buffer(70).intersection(libre).difference(agua)
    out = []
    for g in getattr(carrizal, "geoms", [carrizal]):
        if g.geom_type == "Polygon" and g.area > 500:
            out.append(("wetland", g))
    for g in getattr(agua, "geoms", [agua]):
        if g.geom_type == "Polygon" and g.area > 500:
            out.append(("water", g))
    # el río, de laguna en laguna
    if len(centros) >= 2:
        orden = sorted(centros, key=lambda c: c[0])
        pts = [(orden[0][0] - 300, orden[0][1])] + orden + [(orden[-1][0] + 300, orden[-1][1])]
        rio = LineString(_chaikin(_remuestrear(pts, 60), 3)).intersection(zona.buffer(-15).difference(vias.buffer(-8)))
        for seg in getattr(rio, "geoms", [rio]):
            if seg.geom_type == "LineString" and seg.length > 60:
                out.append(("river", seg))
    # pasarelas y observatorios
    extra = []
    cv = next((st for st in sitios if st["tipo"] == "centro_visitantes"), None)
    if cv is not None and not agua.is_empty:
        c = cv["geom"].centroid
        lagunas = [g for g in getattr(agua, "geoms", [agua]) if g.geom_type == "Polygon"]
        lagunas.sort(key=lambda g: g.distance(c))
        from shapely.ops import nearest_points
        for g in lagunas[:3]:
            orilla = nearest_points(g.exterior, c)[0]
            dx, dy = orilla.x - c.x, orilla.y - c.y
            L = math.hypot(dx, dy) or 1
            dentro = (orilla.x + dx / L * 25, orilla.y + dy / L * 25)
            pas = LineString([(c.x, c.y), dentro]).difference(cv["geom"].buffer(2))
            for seg in getattr(pas, "geoms", [pas]):
                if seg.geom_type == "LineString" and seg.length > 10:
                    out.append(("pier", seg))
            fuera = (orilla.x - dx / L * 10, orilla.y - dy / L * 10)
            out.append(("shed", Point(fuera).buffer(4, cap_style=3)))
    return out, extra


CULTIVOS_CABANEROS = [("forest", 28), ("scrub", 26), ("grass", 26), ("farmland", 4), (None, 16)]

# ---------------------------------------------------------------------------
# El dibujo de cada rectángulo
# ---------------------------------------------------------------------------
KIND = {7: "motorway", 6: "primary", 5: "primary", 4: "secondary", 3: "residential", 2: "track"}


def _recortar(points, W, H):
    """Los trozos de una línea que caen dentro de la hoja (también los tramos
    que la cruzan entera sin tener ningún vértice dentro)."""
    from shapely.geometry import LineString, box
    g = LineString(points).intersection(box(0, 0, W, H))
    parts = [g] if g.geom_type == "LineString" else list(getattr(g, "geoms", []))
    return [list(p.coords) for p in parts if p.geom_type == "LineString" and p.length > 1]


def disenos(rects, roads, sitios, seed, mpt=2.0, campo=()):
    from knoxbuild.placement import _scenery
    from shapely.geometry import LineString, Polygon, box
    from shapely.ops import unary_union
    out = {}
    ocupado = unary_union([s["geom"].buffer(10) for s in sitios]) if sitios else Polygon()
    for k, (rx, ry, rw, rh) in enumerate(rects):
        W, H = rw * CELL * mpt, rh * CELL * mpt
        top = (ry + rh) * CELL

        def to_d(p):
            return ((p[0] - rx * CELL) * mpt, (top - p[1]) * mpt)

        feats = []
        for r in roads:
            kind = KIND.get(r["cls"], "secondary")
            for run in _recortar([to_d(p) for p in r["line"]], W, H):
                feats.append({"kind": kind, "points": [[round(x, 1), round(y, 1)] for x, y in run]})
                scen = _scenery(run, W, H, seed=seed + k * 101 + len(feats))
                # nada de campo encima de los sitios de interés
                for f in scen:
                    if f["kind"] not in ("tree", "hedge"):
                        continue            # el campo lo pone paisaje()
                    pts = [((p[0] / mpt) + rx * CELL, top - p[1] / mpt) for p in f["points"]]
                    g = Polygon(pts) if len(pts) >= 3 else LineString(pts) if len(pts) == 2 else box(pts[0][0], pts[0][1], pts[0][0] + 1, pts[0][1] + 1)
                    if not g.intersects(ocupado):
                        feats.append(f)
        for s in sitios:
            for kind, pts, tags in s["feats"]:
                if kind in ("service", "track", "fence", "hedge") and len(pts) > 1:
                    trozos = _recortar([to_d(p) for p in pts], W, H)
                elif all(rx * CELL <= p[0] <= (rx + rw) * CELL and ry * CELL <= p[1] <= (ry + rh) * CELL for p in pts):
                    trozos = [list(map(to_d, pts))]
                else:
                    trozos = []
                for t in trozos:
                    item = {"kind": kind, "points": [[round(a, 1), round(b, 1)] for a, b in t]}
                    if tags:
                        item["tags"] = dict(tags)
                    feats.append(item)
        # el paisaje del hueco, recortado a este rectángulo
        hoja = box(rx * CELL, ry * CELL, (rx + rw) * CELL, (ry + rh) * CELL)
        for kind, g in campo:
            if not g.intersects(hoja):
                continue
            if g.geom_type == "Point":
                feats.append({"kind": kind, "points": [[round(a, 1), round(b, 1)] for a, b in map(to_d, g.coords)]})
                continue
            if g.geom_type == "LineString":
                for t in _recortar([to_d(p) for p in g.coords], W, H):
                    feats.append({"kind": kind, "points": [[round(a, 1), round(b, 1)] for a, b in t]})
                continue
            q = g.intersection(hoja.buffer(-1))
            for part in getattr(q, "geoms", [q]):
                if part.geom_type == "Polygon" and part.area > 300:
                    ring = list(part.exterior.coords)[:-1]
                    feats.append({"kind": kind, "points": [[round(a, 1), round(b, 1)] for a, b in map(to_d, ring)]})
        out[k] = {"width_m": round(W, 1), "height_m": round(H, 1),
                  "anchor": {"lat": 0.0, "lon": 0.0}, "features": feats}
    return out


# ---------------------------------------------------------------------------
# Dibujo del plan
# ---------------------------------------------------------------------------

def dibujar_plan(path, boxes, holes_rects, roads, sitios, ends, zona=(60, 0, 126, 60), s=1 / 14, campo=()):
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = zona
    W, H = int((x1 - x0) * CELL * s), int((y1 - y0) * CELL * s)
    im = Image.new("RGB", (W, H), (28, 28, 30))
    d = ImageDraw.Draw(im)
    P = lambda x, y: ((x - x0 * CELL) * s, (y - y0 * CELL) * s)
    for n, (x, y, w, h) in boxes.items():
        if n.startswith("Relleno_"):
            continue
        col = (200, 180, 90) if not n.startswith(("Enlace_", "Cruce_")) else (70, 90, 50)
        d.rectangle([P(x * CELL, y * CELL), P((x + w) * CELL, (y + h) * CELL)], fill=col, outline=(20, 20, 20))
    for rects in holes_rects:
        for (x, y, w, h) in rects:
            d.rectangle([P(x * CELL, y * CELL), P((x + w) * CELL, (y + h) * CELL)], fill=(60, 110, 60), outline=(120, 200, 120))
    for kind, g in campo:
        col = {"forest": (30, 70, 35), "orchard": (110, 130, 60), "farmland": (150, 140, 70),
               "scrub": (90, 110, 60), "grass": (90, 150, 80), "water": (60, 120, 220),
               "wetland": (80, 140, 130)}.get(kind)
        if g.geom_type == "Polygon" and col:
            d.polygon([P(*q) for q in g.exterior.coords], fill=col)
        elif kind in ("stream", "river") and g.geom_type == "LineString":
            d.line([P(*q) for q in g.coords], fill=(70, 140, 230), width=2 if kind == "stream" else 3)
    for r in roads:
        d.line([P(*p) for p in r["line"]], fill=(240, 240, 240) if r["cls"] >= 4 else (190, 150, 100),
               width=2 if r["cls"] >= 4 else 1)
    for st in sitios:
        b = st["geom"].bounds
        col = {"centro_comercial": (240, 140, 40), "poligono": (150, 150, 190), "base_militar": (200, 60, 60),
               "ocio": (230, 200, 60), "venta": (230, 120, 160), "gasolinera": (60, 200, 230),
               "cortijo": (160, 110, 70), "aldea": (235, 235, 210)}.get(st["tipo"], (220, 220, 220))
        d.rectangle([P(b[0], b[1]), P(b[2], b[3])], fill=col)
        for kind, pts, _t in st["feats"]:
            if kind in ("track", "service") and len(pts) > 1:
                d.line([P(*q) for q in pts], fill=(170, 130, 90), width=1)
    for e in ends:
        x, y = P(e["x"], e["y"])
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 60, 60) if e["tipo"] == "enlace" else (60, 160, 255))
    im.save(path)


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("knox")
    ap.add_argument("layout")
    ap.add_argument("--solo-plan", action="store_true")
    ap.add_argument("--plan-png", default=os.path.join(HERE, "rellenos_plan.png"))
    a = ap.parse_args(argv)
    knox = os.path.abspath(a.knox)
    layout = json.load(open(a.layout, encoding="utf-8"))
    out_dir = os.path.join(knox, "output")
    sys.path.insert(0, knox)
    os.chdir(knox)
    import zlib

    boxes = cajas(out_dir, layout)
    grupos, occ = huecos(boxes)
    print(f"{len(grupos)} huecos: " + ", ".join(f"{len(g)} celdas" for g in grupos))
    # Las zonas: los huecos cerrados y las zonas con nombre propio
    # (Cabañeros, el aeropuerto, el Campo de Montiel, el sur), con las
    # celdas que queden libres
    zonas = []
    tomadas = set().union(*grupos) if grupos else set()
    for gi, hole in enumerate(grupos):
        vec = {occ.get((x + dx, y + dy)) for (x, y) in hole for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
        tema = "tablas" if ("Daimiel" in vec and "CiudadReal" not in vec and len(hole) < 90) else None
        nombre = "Relleno_Tablas" if tema == "tablas" else f"Relleno_{gi + 1}"
        zonas.append({"nombre": nombre, "hole": hole, "tema": tema, "gi": gi, "unir": [],
                      "tipos": POR_TEMA.get(tema) if tema else POR_HUECO.get(gi, [])})
    for z in ZONAS_EXTRA:
        x, y, w, h = z["rect"]
        cells = {(xx, yy) for xx in range(x, x + w) for yy in range(y, y + h)
                 if (xx, yy) not in occ and (xx, yy) not in tomadas}
        # solo la parte conectada más grande
        trozos = []
        resto = set(cells)
        while resto:
            c = resto.pop()
            t, st = {c}, [c]
            while st:
                q = st.pop()
                for m in ((q[0] + 1, q[1]), (q[0] - 1, q[1]), (q[0], q[1] + 1), (q[0], q[1] - 1)):
                    if m in resto:
                        resto.discard(m)
                        t.add(m)
                        st.append(m)
            trozos.append(t)
        if not trozos:
            continue
        cells = max(trozos, key=len)
        tomadas |= cells
        tema = z.get("tema")
        zonas.append({"nombre": f"Relleno_{z['nombre']}", "hole": cells, "tema": tema, "gi": None,
                      "unir": z.get("unir", []), "tipos": z.get("tipos", POR_TEMA.get(tema, []))})
    centros = [((b[0] + b[2] / 2) * CELL, (b[1] + b[3] / 2) * CELL) for n, b in boxes.items()
               if n in layout["towns"]]
    nombres_aldea = list(NOMBRES_ALDEA)
    from shapely.geometry import LineString as _LS, Point as _P
    from shapely.ops import nearest_points as _np, unary_union as _uu

    # 1. Las carreteras de cada zona: de pueblo a pueblo, salidas, ramales
    for z in zonas:
        hole, tema, gi, nombre = z["hole"], z["tema"], z["gi"], z["nombre"]
        z["rects"] = rects = rectangulos(hole)
        vecinos = {}
        for (x, y) in hole:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = occ.get((x + dx, y + dy))
                if n:
                    vecinos[n] = boxes[n]
        z["vecinos"] = vecinos
        salidas = []
        for n, b in vecinos.items():
            if n in layout["towns"]:
                salidas += salidas_pueblo(knox, n, b, hole)
        limpio = []
        for e in sorted(salidas, key=lambda e: -e["cls"]):
            if all(math.dist((e["x"], e["y"]), (f["x"], f["y"])) > 60 for f in limpio):
                limpio.append(e)
        ramas = []
        for n, b in vecinos.items():
            if n not in layout["towns"]:
                ramas += ramales_enlace(out_dir, n, b, hole)
        z["ramas"] = ramas
        z["rng"] = rng = random.Random(1000 + (gi if gi is not None else zlib.crc32(nombre.encode()) % 997))
        z["aero"] = z["entrada"] = bloqueo = None
        if tema == "aeropuerto":
            z["aero"], bloqueo, z["entrada"] = aeropuerto(rects)
        t0 = time.time()
        g, roads, ends = radiales(knox, out_dir, layout, boxes, occ, hole, limpio, ramas, bloqueo, z["unir"])
        z["g"], z["roads"], z["ends"] = g, roads, ends
        print(f"{nombre}: {len(hole)} celdas, {len(roads)} carreteras ({time.time() - t0:.0f}s)", flush=True)

    # 2. Las puertas entre zonas que se tocan, y lo que quede suelto
    pt = puertas(zonas)
    fallan = set()
    for z in zonas:
        pend = [dict(e) for e in pt[z["nombre"]]]
        usadas = {e["de"] for e in z["ends"] if e["tipo"] == "enlace"}
        if not z["g"].road:
            pend += [dict(r) for r in z["ramas"] if r["de"] not in usadas]
        if not pend:
            continue
        for e in conectar(z["g"], z["roads"], z["ends"], pend, z["rng"]):
            if e["tipo"] == "puerta":
                fallan.add(e["id"])
    if fallan:
        print(f"  puertas que no han podido unirse: {sorted(fallan)}")
        for z in zonas:
            z["roads"] = [r for r in z["roads"] if r.get("puerta") not in fallan
                          and r.get("puerta_fin") not in fallan]
            z["ends"] = [e for e in z["ends"] if e.get("id") not in fallan]
    for z in zonas:
        if not z["roads"] and z["tema"] != "aeropuerto":
            ends = []
            for n, b in z["vecinos"].items():
                if n not in layout["towns"]:
                    ends += ramales_enlace(out_dir, n, b, z["hole"])
            z["g"], z["roads"] = trazar(z["hole"], ends[:3])
            z["ends"] = ends[:3] if z["roads"] else []

    # 3. Lo propio de cada zona: el acceso al aeropuerto, la carretera del
    # parque de Cabañeros, transversales, sitios, aldeas, campo
    plan = []
    for z in zonas:
        hole, tema, gi, nombre = z["hole"], z["tema"], z["gi"], z["nombre"]
        rects, g, roads, ends, rng, vecinos = z["rects"], z["g"], z["roads"], z["ends"], z["rng"], z["vecinos"]
        aero, entrada = z["aero"], z["entrada"]
        if entrada is not None and g.road:
            # la avenida del aeropuerto: sale recta de la puerta y se junta
            # con la carretera más cercana
            ex, ey = entrada
            recta = (ex, ey + 90)
            n0 = g.cercano(g.nodo(*recta))
            path = g.ruta(n0, set(g.road))
            if path:
                line = [entrada, recta] + [g.punto(n) for n in path]
                q = _np(_uu([_LS(r["line"]) for r in roads]), _P(line[-1]))[0]
                line[-1] = (q.x, q.y)
                line = ondular(_suavizar(simplificar(line)), g, rng, *AMPLITUD["camino"], fijo_final=False)
                roads.append({"cls": 6, "line": line, "end": None})
                marcar(g, line, 6)
                # árboles a los dos lados de la avenida
                av = _LS(line)
                for d in range(30, int(av.length) - 20, 22):
                    p_ = av.interpolate(d)
                    p2 = av.interpolate(min(d + 2, av.length))
                    tx, ty = p2.x - p_.x, p2.y - p_.y
                    tl = math.hypot(tx, ty) or 1
                    for lado in (1, -1):
                        aero["feats"].append(("tree", [(p_.x - ty / tl * 13 * lado, p_.y + tx / tl * 13 * lado)], {}))
        if tema == "cabaneros" and roads:
            # la carretera del parque: entra por otro punto del enlace, baja
            # hasta el fondo del parque y vuelve a la carretera de Horcajo
            usados_ = [(e["x"], e["y"]) for e in ends]
            for n, b in vecinos.items():
                if n in layout["towns"]:
                    continue
                for r_ in ramales_enlace(out_dir, n, b, hole, maxdist=200, lejos_de=usados_):
                    if min(math.dist((r_["x"], r_["y"]), u) for u in usados_) < 600:
                        continue
                    nx_, ny_ = r_["n"]
                    r_["dentro"] = (r_["x"] + nx_ * STUB, r_["y"] + ny_ * STUB)
                    na = g.cercano(g.nodo(*r_["dentro"]))
                    xs_ = [c[0] for c in hole]
                    ys_ = [c[1] for c in hole]
                    wp = ((min(xs_) + 0.3 * (max(xs_) + 1 - min(xs_))) * CELL,
                          (min(ys_) + 0.72 * (max(ys_) + 1 - min(ys_))) * CELL)
                    nw = g.cercano(g.nodo(*wp))
                    g.atraer = False
                    p1 = g.ruta(na, {nw})
                    g.atraer = True
                    p2 = g.ruta(nw, set(g.road)) if p1 else None
                    if not (p1 and p2):
                        continue
                    line = [(r_["x"], r_["y"]), r_["dentro"]] + [g.punto(m) for m in p1 + p2[1:]]
                    q = _np(_uu([_LS(rr["line"]) for rr in roads]), _P(line[-1]))[0]
                    line[-1] = (q.x, q.y)
                    line = ondular(_suavizar(simplificar(line)), g, rng, *AMPLITUD["carretera"], fijo_final=False)
                    roads.append({"cls": 4, "line": line, "end": r_})
                    marcar(g, line, 4)
                    ends.append(r_)
                    break
        grande = len(hole) > 150
        roads += transversales(g, roads, rng, maximo=3 if grande else 2 if len(hole) > 60 else 1)
        sitios = [aero] if aero else []
        sitios += colocar_sitios(hole, rects, roads, boxes, gi, rng, tipos=z["tipos"],
                                 ocupado=aero["geom"] if aero else None)
        # aldeas: una en los huecos grandes y en Cabañeros, dos en los enormes
        n_aldeas = 2 if len(hole) >= 220 else 1 if (len(hole) >= 90 or tema == "cabaneros") else 0
        for k in range(n_aldeas):
            nom = "Retuerta del Bullaque" if (tema == "cabaneros" and k == 0) else \
                (nombres_aldea.pop(0) if nombres_aldea else None)
            if nom is None:
                break
            ocup = _uu([st["geom"].buffer(30) for st in sitios]) if sitios else None
            al = colocar_aldea(roads, _zona(rects).buffer(-20), ocup, centros + [st["geom"].centroid.coords[0]
                               for st in sitios if st["tipo"] == "aldea"], rng, nom,
                               lejos_min=450 if tema == "cabaneros" else 600)
            if al:
                sitios.append(al)
        extra_campo = []
        evitar = None
        if tema == "tablas":
            extra_campo, _ = tablas(rects, roads, sitios, rng)
            evitar = _uu([g_.buffer(8) for k_, g_ in extra_campo if k_ in ("water", "wetland")] or [_P0()])
            agua = _uu([g_.buffer(6) for k_, g_ in extra_campo if k_ == "water"] or [_P0()])
            rio = _uu([g_ for k_, g_ in extra_campo if k_ == "river"] or [_P0()])
            sitios += destinos(g, rects, roads, sitios, rng,
                               ["molino", "puesto_forestal", "observatorio", "observatorio", "refugio"],
                               evitar=agua, junto_a={"molino": rio})
        if tema == "cabaneros":
            sitios += destinos(g, rects, roads, sitios, rng,
                               ["puesto_forestal", "aserradero", "refugio", "puesto_forestal",
                                "refugio", "aserradero", "observatorio"])
            campo = paisaje(hole, rects, roads, sitios, rng, cultivos=CULTIVOS_CABANEROS,
                            manchas_por=5, dehesa=0.35)
        else:
            campo = paisaje(hole, rects, roads, sitios, rng, evitar=evitar)
        campo = extra_campo + campo
        print(f"{nombre}: {len(hole)} celdas en {len(rects)} mapas, "
              f"{sum(e['tipo'] == 'pueblo' for e in ends)} salidas de pueblo, "
              f"{sum(e['tipo'] == 'enlace' for e in ends)} ramales de enlace, "
              f"{sum(e['tipo'] == 'puerta' for e in ends)} puertas, "
              f"sitios: {', '.join(s_['tipo'] for s_ in sitios if s_['tipo'] != 'cortijo')}"
              f" y {sum(s_['tipo'] == 'cortijo' for s_ in sitios)} cortijos", flush=True)
        plan.append({"nombre": nombre, "hole": hole, "rects": rects, "ends": ends, "roads": roads,
                     "sitios": sitios, "campo": campo, "tema": tema})

    dibujar_plan(a.plan_png, boxes, [p["rects"] for p in plan],
                 [r for p in plan for r in p["roads"]], [s for p in plan for s in p["sitios"]],
                 [e for p in plan for e in p["ends"]], campo=[c for p in plan for c in p["campo"]])
    print(f"plan dibujado en {a.plan_png}")
    if a.solo_plan:
        return 0
    return generar(knox, out_dir, layout, boxes, plan)


def _quitar_mod(txt, mod):
    import re as _re
    return _re.sub(r"^\s*mod = " + _re.escape(mod) + r",\s*\n", "", txt, flags=_re.M)


def vida_enlace(lname, box, lines, boxes, layout, rng, nombres):
    """Lo que se le añade a una carretera de enlace para que no sea solo campo:
    una aldea con sus manzanas en las largas, y una venta o una armería de
    carretera. Devuelve una lista de sitios (en tiles del mundo)."""
    from shapely.geometry import box as _box
    lx, ly, lw, lh = box
    roads = [{"cls": 5, "line": l} for l in lines if _largo(l) > 200]
    if not roads:
        return []
    total = sum(_largo(r["line"]) for r in roads)
    centros = [((b[0] + b[2] / 2) * CELL, (b[1] + b[3] / 2) * CELL) for n, b in boxes.items()
               if n in layout["towns"]]
    permitido = _box(lx * CELL + 12, ly * CELL + 12, (lx + lw) * CELL - 12, (ly + lh) * CELL - 12)
    sitios = []
    if total >= 2200 and nombres:
        al = colocar_aldea(roads, permitido, None, centros, rng, nombres[0], lejos_min=600, objetivo=total / 2)
        if al:
            nombres.pop(0)
            sitios.append(al)
    if total >= 900:
        from shapely.ops import unary_union
        ocup = unary_union([st["geom"] for st in sitios]) if sitios else None
        tipo = rng.choice(["venta", "armeria", "gasolinera"])
        sitios += colocar_sitios(None, [box], roads, boxes, None, rng, tipos=[tipo],
                                 ocupado=ocup, con_caminos=False)
    return sitios


def generar(knox, out_dir, layout, boxes, plan):
    from knoxbuild import placement as P
    from generator import osm as kosm, sketch
    import app as knoxapp

    nuevos = {}
    for p in plan:
        for k, r in enumerate(p["rects"]):
            nuevos[f"{p['nombre']}_{k + 1}"] = r
    # Los Relleno_ de una pasada anterior que ya no están en el plan (otro
    # nombre, otro tamaño): fuera de output y de los mods, que si no se
    # quedarían encima de los nuevos.
    import shutil
    mods = os.path.join(os.path.expanduser("~"), "Zomboid", "mods")
    viejos = [d for d in os.listdir(out_dir) if d.startswith("Relleno_") and d not in nuevos]
    for d in viejos:
        shutil.rmtree(os.path.join(out_dir, d), ignore_errors=True)
        if os.path.isdir(os.path.join(mods, d)):
            shutil.rmtree(os.path.join(mods, d), ignore_errors=True)
    if viejos:
        lista = os.path.join(mods, "default.txt")
        if os.path.exists(lista):
            txt = open(lista, encoding="utf-8").read()
            for d in viejos:
                txt = _quitar_mod(txt, d)
            open(lista, "w", encoding="utf-8").write(txt)
        print("quitados mapas de una pasada anterior: " + ", ".join(viejos))
    # Los mapas retirados del plano (los enlaces largos de Infantes)
    retirados = [d for d in os.listdir(out_dir) if d in RETIRADOS]
    for d in retirados:
        shutil.rmtree(os.path.join(out_dir, d), ignore_errors=True)
        if os.path.isdir(os.path.join(mods, d)):
            shutil.rmtree(os.path.join(mods, d), ignore_errors=True)
    lista = os.path.join(mods, "default.txt")
    if os.path.exists(lista):
        txt = open(lista, encoding="utf-8").read()
        nuevo = txt
        for d in RETIRADOS:
            nuevo = _quitar_mod(nuevo, d)
        if nuevo != txt:
            open(lista, "w", encoding="utf-8").write(nuevo)
    if retirados:
        print("quitados mapas que ya no están en el plano: " + ", ".join(retirados))
    # Las tiendas pueden decir qué venden (shop=weapons es una armería)
    sketch.EXTRA_TAGS = set(sketch.EXTRA_TAGS) | {"shop"}
    ramales = {e["de"] for p in plan for e in p["ends"] if e["tipo"] == "enlace"}
    # enlaces con un ramal de una pasada anterior que ya no hace falta: se
    # rehacen sin él, para que no quede un ramal que acaba en el campo
    for n in boxes:
        if n.startswith(("Enlace_", "Cruce_")) and n not in ramales:
            try:
                d = json.load(open(os.path.join(out_dir, n, f"{n}_design.json"), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if any(f.get("branch") == "relleno" for f in d.get("features", [])):
                ramales.add(n)

    real_world_maps = P.world_maps
    todos = {**{n: b for n, b in boxes.items() if not n.startswith("Relleno_")}, **nuevos}

    def world_maps(own_mod=None):
        out = [m for m in real_world_maps(own_mod) if m.get("kind") != "installed"
               or m.get("name") not in todos]
        for name, (x, y, w, h) in todos.items():
            if name == own_mod:
                continue
            out.append({"name": name, "kind": "plan", "x": x * 300 / 256, "y": y * 300 / 256,
                        "w": w * 300 / 256, "h": h * 300 / 256})
        return out

    P.world_maps = world_maps
    client = knoxapp.app.test_client()
    LINK = {"preset": "rural", "align_streets": 0, "rotate_degrees": 0, "straight_roads": 0}

    def call(method, url, **kw):
        r = getattr(client, method)(url, **kw)
        body = r.get_json(silent=True) or {}
        if r.status_code != 200:
            raise RuntimeError(f"{url} -> {r.status_code}: {body.get('error', body)}")
        return body

    def construir(name, design, mpt, box):
        call("post", "/api/generate", json={"mapName": name, "design": design,
                                            "metersPerTile": mpt, "settings": LINK})
        call("post", f"/api/placement/{name}", json={"cell_x": box[0], "cell_y": box[1]})
        drawn = sketch.features(sketch.design_to_drawn(design))
        real_load = kosm.load_cache
        kosm.load_cache = lambda *a, **k: list(drawn)
        try:
            call("post", "/api/buildings", json={"mapName": name})
        finally:
            kosm.load_cache = real_load
        with open(os.path.join(out_dir, name, f"{name}_design.json"), "w", encoding="utf-8") as f:
            json.dump(design, f)

    import csv as _csv
    import importlib.util as _ilu
    import re as _re
    import zlib as _zlib
    _spec = _ilu.spec_from_file_location("monumentos_cr", os.path.join(HERE, "monumentos.py"))
    M = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(M)
    PALETA = [("crema", 35), ("ocre", 20), ("piedra_dorada", 15), ("piedra_clara", 15), ("ladrillo", 15)]
    estilos = {}

    def fachadas(name):
        """Casas, ventas y tiendas del campo con fachadas de aquí: encalado
        crema u ocre, piedra o ladrillo, y teja."""
        d = os.path.join(out_dir, name)
        with open(os.path.join(d, f"{name}_placements.csv"), encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        for r in rows:
            if r["kind"] not in ("house", "shop", "restaurant", "apartment"):
                continue
            path = os.path.join(d, "buildings", r["file"])
            text = open(path, encoding="utf-8").read()
            rng = random.Random(_zlib.crc32(r["file"].encode()))
            mat = rng.choices([m for m, _ in PALETA], [w for _, w in PALETA])[0]
            tejado = bool(_re.search(r'RoofType="(?!FlatTop)', text))
            key = (mat, tejado)
            if key not in estilos:
                st = M.estilo("painted", mat, "teja" if tejado else None, None)
                if not tejado:
                    st["roof"] = {}
                estilos[key] = st
            open(path, "w", encoding="utf-8").write(M.recubrir(text, estilos[key]))

    ok = {}
    # 0. Los pueblos que han cambiado de sitio en el plano (Infantes,
    # Villahermosa): se recolocan; hay que volver a compilarlos
    for t, tt in layout["towns"].items():
        try:
            pl = json.load(open(os.path.join(out_dir, t, "placement.json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (pl.get("cell_x"), pl.get("cell_y")) != (tt["cell_x"], tt["cell_y"]):
            try:
                call("post", f"/api/placement/{t}", json={"cell_x": tt["cell_x"], "cell_y": tt["cell_y"]})
                print(f"{t}: movido a la celda {tt['cell_x']},{tt['cell_y']}", flush=True)
                ok[t] = True
            except Exception as exc:  # noqa: BLE001
                print(f"{t}: FALLO al moverlo: {exc}")
                ok[t] = False

    def conectores(lname, lbox, design, to_w):
        """Calles grandes de un pueblo que acaban en el borde del enlace sin
        nada al otro lado (la de Poblete hacia Corral y la Cañada, p. ej.):
        se siguen dentro del enlace hasta su carretera, con una curva."""
        lx, ly, lw, lh = lbox
        celdas = {(x, y) for x in range(lx, lx + lw) for y in range(ly, ly + lh)}
        vias = [[to_w(q) for q in f["points"]] for f in design["features"]
                if f["kind"] in ROADS | {"service", "track"} and len(f["points"]) > 1]
        principales = [[to_w(q) for q in f["points"]] for f in design["features"]
                       if f["kind"] in ROADS and len(f["points"]) > 1 and f.get("extra") != "relleno"]
        if not principales:
            return []
        out = []
        hechos = []
        for t, tb in boxes.items():
            if t not in layout["towns"]:
                continue
            if not (tb[0] <= lx + lw and lx <= tb[0] + tb[2] and tb[1] <= ly + lh and ly <= tb[1] + tb[3]):
                continue
            try:
                sal = salidas_pueblo(knox, t, tb, celdas)
            except OSError:
                continue
            for e in sorted(sal, key=lambda e: -e["cls"]):
                p = (e["x"], e["y"])
                if e["cls"] < 5 or any(math.dist(p, h) < 80 for h in hechos):
                    continue
                if any(math.dist(p, _cerca(v, p)) < 30 for v in vias):
                    continue                      # ya sigue por el enlace
                nx, ny = e["n"]
                s0 = (p[0] + nx * STUB, p[1] + ny * STUB)
                q = min((_cerca(v, s0) for v in principales), key=lambda c: math.dist(c, s0))
                d = math.dist(q, s0)
                if d < 20 or d > 1000:
                    continue
                c1 = (s0[0] + nx * d * 0.5, s0[1] + ny * d * 0.5)
                curva = [((1 - u) ** 2 * s0[0] + 2 * (1 - u) * u * c1[0] + u * u * q[0],
                          (1 - u) ** 2 * s0[1] + 2 * (1 - u) * u * c1[1] + u * u * q[1])
                         for u in [k / 16 for k in range(17)]]
                if not all(lx * CELL + 3 <= x <= (lx + lw) * CELL - 3 and ly * CELL + 3 <= y <= (ly + lh) * CELL - 3
                           for x, y in curva):
                    continue
                hechos.append(p)
                out.append({"cls": e["cls"], "line": [p] + curva, "de": t})
        return out

    # 1. Los enlaces: un ramal donde da a un hueco, y vida a lo largo de la
    # carretera (aldeas, ventas, armerías). Se rehacen todos los enlaces.
    enlaces = sorted(n for n in boxes if n.startswith(("Enlace_", "Cruce_")))
    nombres = [n for n in NOMBRES_ALDEA if n not in {st.get("nombre") for p in plan for st in p["sitios"]}]
    for lname in enlaces:
        t0 = time.time()
        try:
            design, mpt, lines = carretera_de(out_dir, lname)
            lx, ly, lw, lh = boxes[lname]
            top = (ly + lh) * CELL
            to_d = lambda w: [round((w[0] - lx * CELL) * mpt, 1), round((top - w[1]) * mpt, 1)]
            to_w = lambda d: (lx * CELL + d[0] / mpt, top - d[1] / mpt)
            feats = [f for f in design["features"] if f.get("branch") != "relleno" and f.get("extra") != "relleno"]
            cons = conectores(lname, boxes[lname], {**design, "features": feats}, to_w)
            vida = vida_enlace(lname, boxes[lname], lines + [c["line"] for c in cons], boxes, layout,
                               random.Random(_zlib.crc32(lname.encode())), nombres)
            if not vida and not cons and lname not in ramales:
                continue
            for c in cons:
                linea = c["line"]

                def bajo(f):
                    if f["kind"] in ROADS:
                        return False
                    return any(math.dist(to_w(q), _cerca(linea, to_w(q))) < 14 for q in f["points"])
                feats = [f for f in feats if not bajo(f)]
                feats.append({"kind": "primary" if c["cls"] >= 6 else "secondary",
                              "points": [to_d(q) for q in linea], "extra": "relleno"})
            if vida:
                from shapely.geometry import LineString as _LS, Point as _Pt, Polygon as _Pg
                from shapely.ops import unary_union as _uu
                huella = _uu([st["geom"].buffer(6) for st in vida])

                def pisa(f):
                    if f["kind"] in ROADS:
                        return False
                    pts = [to_w(q) for q in f["points"]]
                    g_ = _Pg(pts) if len(pts) >= 3 else _LS(pts) if len(pts) == 2 else _Pt(pts[0])
                    return g_.intersects(huella)
                feats = [f for f in feats if not pisa(f)]
                for st in vida:
                    for kind, pts, tags in st["feats"]:
                        item = {"kind": kind, "points": [to_d(q) for q in pts], "extra": "relleno"}
                        if tags:
                            item["tags"] = dict(tags)
                        feats.append(item)
            for p in plan:
                for e in p["ends"]:
                    if e["tipo"] != "enlace" or e["de"] != lname:
                        continue
                    nx, ny = e["n"]
                    inner = (e["x"] - nx * STUB, e["y"] - ny * STUB)
                    branch = [e["q"], inner, (e["x"], e["y"])]
                    # fuera lo que caiga encima del ramal
                    def encima(f):
                        if f["kind"] in ROADS:
                            return False
                        return any(math.dist(to_w(q), _cerca(branch, to_w(q))) < 12 for q in f["points"])
                    feats = [f for f in feats if not encima(f)]
                    feats.append({"kind": "secondary", "points": [to_d(q) for q in branch], "branch": "relleno"})
            construir(lname, {**design, "features": feats}, mpt, (lx, ly))
            if vida:
                fachadas(lname)
            que = ", ".join([st["tipo"] for st in vida] + [f"calle de {c['de']}" for c in cons]) or "ramal"
            print(f"{lname}: {que} ({time.time() - t0:.0f}s)", flush=True)
            ok[lname] = True
        except Exception as exc:  # noqa: BLE001
            print(f"{lname}: FALLO {exc}")
            ok[lname] = False
    # 2. Los mapas de relleno
    for gi, p in enumerate(plan):
        ds = disenos(p["rects"], p["roads"], p["sitios"], seed=7000 + gi * 50, campo=p["campo"])
        for k, r in enumerate(p["rects"]):
            name = f"{p['nombre']}_{k + 1}"
            t0 = time.time()
            try:
                construir(name, ds[k], 2.0, (r[0], r[1]))
                fachadas(name)
                print(f"{name}: {r[2]}x{r[3]} celdas en {r[0]},{r[1]} ({time.time() - t0:.0f}s)", flush=True)
                ok[name] = True
            except Exception as exc:  # noqa: BLE001
                print(f"{name}: FALLO {exc}")
                ok[name] = False
    # Los Relleno_ nuevos, activados en la lista de mods por defecto
    lista = os.path.join(mods, "default.txt")
    if os.path.exists(lista):
        txt = open(lista, encoding="utf-8").read()
        faltan = [n for n, good in ok.items() if good and n.startswith("Relleno_")
                  and not _re.search(r"^\s*mod = " + _re.escape(n) + r",", txt, flags=_re.M)]
        if faltan:
            m = _re.search(r"mods\s*\{[^}]*", txt)
            if m:
                txt = txt[:m.end()] + "".join(f"    mod = {n},\n" for n in faltan) + txt[m.end():]
                open(lista, "w", encoding="utf-8").write(txt)
                print("activados en la lista de mods: " + ", ".join(faltan))
    # La lista de mapas nuevos o rehechos, para compilarlos (RELLENAR.bat)
    with open(os.path.join(HERE, "rellenos_mapas.txt"), "w", encoding="utf-8") as f:
        f.write(",".join(n for n, good in ok.items() if good))
    print("\nResumen:")
    for n, good in ok.items():
        print(f"  {n:44s} {'listo para Compile e Install' if good else 'FALLO'}")
    return 0 if all(ok.values()) else 1


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
