"""Coloca los pueblos en el mundo de Project Zomboid y dibuja el plano.

Uso: python layout.py <knoxmap> <links.json> <salida_dir> [compresión]

- Cada pueblo es un mapa de KnoxMap a escala real (2 m/tile), con el norte
  arriba; su tamaño en celdas sale de su caja en build_cr.PUEBLOS.
- Los pueblos conservan la dirección real entre ellos; lo que se acorta es el
  campo entre sus bordes: hueco_juego = hueco_real * compresión, con un mínimo.
- Las carreteras de enlace siguen la forma de la carretera real, transformada
  de forma continua entre la colocación de un pueblo y la del otro.

Salidas: layout.json (celda de cada pueblo y puntos de cada enlace en tiles
del mundo) y plano.png (geografía real a la izquierda, mundo del juego a la
derecha, con el condado de Knox original a la misma escala).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

KNOX = Path(sys.argv[1])
LINKS = json.loads(Path(sys.argv[2]).read_text())["links"]
OUT = Path(sys.argv[3])
K = float(sys.argv[4]) if len(sys.argv) > 4 else 0.15
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(KNOX))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cr import PUEBLOS  # noqa: E402
from generator.rendering.projection import Projector  # noqa: E402

CELL = 300            # tiles por celda
MPT = 2.0             # metros por tile en los pueblos
MIN_GAP_CELLS = 2     # hueco mínimo entre pueblos (1,2 km en el juego)
VANILLA = (0, 0, 67, 54)          # condado de Knox, en celdas
ORIGIN = (VANILLA[2] + 6, 4)      # esquina de la provincia: al este de Knox

# ---------------------------------------------------------------- pueblos
# Todos con el norte arriba (sin giro): así las carreteras de enlace salen de
# cada mapa en la dirección real y encajan entre pueblos. Para construirlo de
# verdad, los pueblos se regeneran con align_streets = 0.
towns = {}
for name, (s, w, n, e) in PUEBLOS.items():
    proj = Projector.build(s, w, n, e, MPT, 0.0)
    towns[name] = {"proj": proj, "cx": proj.width // CELL, "cy": proj.height // CELL,
                   "rot": 0.0, "lonlat": ((w + e) / 2, (s + n) / 2)}

# Posición real de cada centro en km (este, norte) respecto a Ciudad Real.
lon0, lat0 = towns["CiudadReal"]["lonlat"]
kx = 111.32 * math.cos(math.radians(lat0))
for t in towns.values():
    lo, la = t["lonlat"]
    t["real"] = np.array([(lo - lon0) * kx, (la - lat0) * 111.32])
    t["half"] = np.array([t["cx"], t["cy"]]) * CELL * MPT / 2000  # km de juego

names = list(towns)

# Posición deseada: la real, escalada de forma uniforme por K (misma forma de
# la provincia, más pequeña). Los pueblos conservan su tamaño real.
cell_km = CELL * MPT / 1000
for n in names:
    t = towns[n]
    cx = t["real"][0] * K / cell_km - t["cx"] / 2
    cy = -t["real"][1] * K / cell_km - t["cy"] / 2      # Y del mundo crece al sur
    t["cell"] = (int(round(cx)), int(round(cy)))

# Al redondear a celdas puede volver a haber roces. Se colocan de uno en uno,
# de más cerca a más lejos de Ciudad Real; si un pueblo choca con uno ya puesto
# (contando el hueco mínimo), va a la posición libre más cercana a la deseada.
def boxc(n):
    x, y = towns[n]["cell"]
    return x, y, x + towns[n]["cx"], y + towns[n]["cy"]


def clashes(n, placed):
    x0, y0, x1, y1 = boxc(n)
    g = MIN_GAP_CELLS
    for o in placed:
        a0, b0, a1, b1 = boxc(o)
        if x0 < a1 + g and a0 < x1 + g and y0 < b1 + g and b0 < y1 + g:
            return True
    return False


placed = []
for n in sorted(names, key=lambda n: np.linalg.norm(towns[n]["real"])):
    want = towns[n]["cell"]
    # Si choca, se aparta en la dirección real desde el pueblo con el que
    # choca (más cercano en la realidad): así Puertollano queda al sur de
    # Argamasilla, como en el mapa, y no a un lado donde hubiera hueco.
    hit = [o for o in placed if clashes(n, [o])]
    if hit:
        o = min(hit, key=lambda o: np.linalg.norm(towns[n]["real"] - towns[o]["real"]))
        v = towns[n]["real"] - towns[o]["real"]
        d = np.array([v[0], -v[1]]) / (np.linalg.norm(v) or 1)   # en celdas: Y hacia el sur
    else:
        d = None

    def cost(off):
        if d is None:
            return off[0] ** 2 + off[1] ** 2
        along = off[0] * d[0] + off[1] * d[1]
        across = abs(off[0] * d[1] - off[1] * d[0])
        return math.hypot(*off) + 3 * across - 0.5 * along

    cands = [(dx, dy) for dx in range(-40, 41) for dy in range(-40, 41)]
    for dx, dy in sorted(cands, key=cost):
        towns[n]["cell"] = (want[0] + dx, want[1] + dy)
        if not clashes(n, placed):
            break
    placed.append(n)

# La provincia entera, al este del condado de Knox y sin coordenadas negativas.
dx = ORIGIN[0] - min(towns[n]["cell"][0] for n in names)
dy = ORIGIN[1] - min(towns[n]["cell"][1] for n in names)
for n in names:
    x, y = towns[n]["cell"]
    towns[n]["cell"] = (x + dx, y + dy)

for i, a in enumerate(names):
    for b in names[i + 1:]:
        ax0, ay0, ax1, ay1 = boxc(a)
        bx0, by0, bx1, by1 = boxc(b)
        if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
            raise SystemExit(f"Solape entre {a} {boxc(a)} y {b} {boxc(b)}")


# ---------------------------------------------------------------- enlaces
def to_world(name, lon, lat):
    t = towns[name]
    px, py = t["proj"].to_px(lat, lon)
    return t["cell"][0] * CELL + px, t["cell"][1] * CELL + py


def inside_map(name, lon, lat):
    px, py = towns[name]["proj"].to_px(lat, lon)
    return 0 <= px < towns[name]["cx"] * CELL and 0 <= py < towns[name]["cy"] * CELL


links_out = []
for l in LINKS:
    a, b = l["a"], l["b"]
    pts = l["points"]
    # Tramo entre la salida del mapa A y la entrada del mapa B.
    i0 = max(i for i, (lo, la) in enumerate(pts) if inside_map(a, lo, la)) if any(
        inside_map(a, lo, la) for lo, la in pts) else 0
    i1 = min(i for i, (lo, la) in enumerate(pts) if inside_map(b, lo, la)) if any(
        inside_map(b, lo, la) for lo, la in pts) else len(pts) - 1
    seg = pts[i0:i1 + 1]
    if len(seg) >= 2 and i1 > i0:
        cum = np.concatenate([[0], np.cumsum([math.dist(p, q) for p, q in zip(seg, seg[1:])])])
        frac = cum / (cum[-1] or 1)
        world = []
        for (lo, la), f in zip(seg, frac):
            wa = np.array(to_world(a, lo, la))
            wb = np.array(to_world(b, lo, la))
            world.append(((1 - f) * wa + f * wb).tolist())
    else:
        # En la realidad los dos mapas se tocan o se pisan (Puertollano y
        # Argamasilla): la carretera pasa de uno a otro sin campo entre medias.
        # En el juego hay hueco, así que se une el mismo punto visto desde cada mapa.
        both = [p for p in pts if inside_map(a, *p) and inside_map(b, *p)] or [pts[i0]]
        p = both[len(both) // 2]
        world = [list(to_world(a, *p)), list(to_world(b, *p))]
    # Simplificar a un punto cada ~60 tiles para que sea manejable.
    simp = [world[0]]
    for p in world[1:-1]:
        if math.dist(p, simp[-1]) >= 60:
            simp.append(p)
    simp.append(world[-1])
    length_tiles = sum(math.dist(p, q) for p, q in zip(simp, simp[1:]))
    xs = [p[0] for p in simp]
    ys = [p[1] for p in simp]
    # Un enlace que pasa por encima de otro pueblo no sirve: ese pueblo ya está
    # en el camino y basta con sus dos enlaces.
    crosses = [o for o in names if o not in (a, b) and any(
        boxc(o)[0] * CELL <= x < boxc(o)[2] * CELL and boxc(o)[1] * CELL <= y < boxc(o)[3] * CELL
        for x, y in simp)]
    if crosses:
        print(f"  (descartado {a}-{b}: pasa por {', '.join(crosses)})")
        continue
    links_out.append({"a": a, "b": b, "ref": l["ref"], "real_km": l["km"],
                      "game_km": round(length_tiles * MPT / 1000, 1),
                      "bbox_cells": [int(min(xs) // CELL), int(min(ys) // CELL),
                                     int(max(xs) // CELL), int(max(ys) // CELL)],
                      "points": [[round(x), round(y)] for x, y in simp]})

layout = {"compression": K, "meters_per_tile": MPT,
          "towns": {n: {"cell_x": t["cell"][0], "cell_y": t["cell"][1],
                        "cells": [t["cx"], t["cy"]], "rotation": round(t["rot"], 1)}
                    for n, t in towns.items()},
          "links": links_out}
(OUT / "layout.json").write_text(json.dumps(layout, indent=1, ensure_ascii=False))

# ---------------------------------------------------------------- plano
W, H = 2400, 1300
img = Image.new("RGB", (W, H), "#f4f1ea")
dr = ImageDraw.Draw(img)
try:
    F = ImageFont.truetype("DejaVuSans.ttf", 18)
    FB = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
    FS = ImageFont.truetype("DejaVuSans.ttf", 15)
except OSError:
    F = FB = FS = ImageFont.load_default()
INK, ROAD, TOWN, KNOXC = "#2b2b2b", "#c0392b", "#2c5d8a", "#9aa59a"
LABEL = {"CiudadReal": "Ciudad Real + Miguelturra", "Bolanos": "Bolaños", "Malagon": "Malagón",
         "CorralDeCalatrava": "Corral", "CanadaDeCalatrava": "Cañada", "CaracuelDeCalatrava": "Caracuel",
         "Argamasilla": "Argamasilla de C.", "Villamayor": "Villamayor de C.", "Alcolea": "Alcolea de C."}
taken = []


def label(box, text):
    """Etiqueta junto a la caja, en la primera posición que no pise otra."""
    x0, y0, x1, y1 = box
    w, h = dr.textbbox((0, 0), text, font=FS)[2:]
    for tx, ty in ((x1 + 5, y0), (x1 + 5, y1 - h), (x0 - w - 5, y0), (x0 - w - 5, y1 - h),
                   (x0, y0 - h - 4), (x0, y1 + 3)):
        r = (tx, ty, tx + w, ty + h)
        if not any(r[0] < q[2] and q[0] < r[2] and r[1] < q[3] and q[1] < r[3] for q in taken):
            break
    taken.append(r)
    dr.text((tx, ty), text, font=FS, fill=INK)


# Panel izquierdo: realidad.
L = (40, 90, 1140, 1240)
dr.text((L[0], 30), "Realidad (OpenStreetMap + Catastro)", font=FB, fill=INK)
allpts = [p for l in LINKS for p in l["points"]] + [t["lonlat"] for t in towns.values()]
lo_min = min(p[0] for p in allpts) - 0.03
lo_max = max(p[0] for p in allpts) + 0.03
la_min = min(p[1] for p in allpts) - 0.03
la_max = max(p[1] for p in allpts) + 0.03
sx = (L[2] - L[0]) / ((lo_max - lo_min) * kx)
sy = (L[3] - L[1]) / ((la_max - la_min) * 111.32)
sc = min(sx, sy)


def rp(lo, la):
    return L[0] + (lo - lo_min) * kx * sc, L[3] - (la - la_min) * 111.32 * sc


for l in LINKS:
    dr.line([rp(*p) for p in l["points"]], fill=ROAD, width=3)
for n, (s, w, nn, e) in PUEBLOS.items():
    x0, y1 = rp(w, s)
    x1, y0 = rp(e, nn)
    dr.rectangle([x0, y0, x1, y1], outline=TOWN, width=3, fill="#dbe6f0")
    taken.append((x0, y0, x1, y1))
for n, (s_, w_, nn_, e_) in PUEBLOS.items():
    x0, y1 = rp(w_, s_)
    x1, y0 = rp(e_, nn_)
    label((x0, y0, x1, y1), LABEL.get(n, n))
# barra de escala 10 km
bx, by = L[0] + 10, L[3] - 10
dr.line([(bx, by), (bx + 10 * sc, by)], fill=INK, width=4)
dr.text((bx, by - 26), "10 km reales", font=FS, fill=INK)

# Panel derecho: mundo del juego, a la misma escala (km por píxel) que el
# izquierdo, para que se vea cuánto se acorta. Recuadro con el condado de Knox.
R = (1220, 90, 2360, 1240)
dr.text((R[0], 30), f"En el juego (pueblos a escala real, distancias x{K:g})", font=FB, fill=INK)
cells_all = [boxc(n) for n in names]
cx0 = min(b[0] for b in cells_all) - 1
cy0 = min(b[1] for b in cells_all) - 1
cx1 = max(b[2] for b in cells_all) + 1
cy1 = max(b[3] for b in cells_all) + 1
cs = cell_km * sc                       # px por celda, misma escala que la realidad
offx = R[0] + ((R[2] - R[0]) - (cx1 - cx0) * cs) / 2
offy = R[1] + 40


def wp(cx, cy):
    return offx + (cx - cx0) * cs, offy + (cy - cy0) * cs


for l in links_out:
    dr.line([wp(x / CELL, y / CELL) for x, y in l["points"]], fill=ROAD, width=3)
for n in names:
    x0, y0, x1, y1 = boxc(n)
    a0, b0 = wp(x0, y0)
    a1, b1 = wp(x1, y1)
    dr.rectangle([a0, b0, a1, b1], outline=TOWN, width=3, fill="#dbe6f0")
    taken.append((a0, b0, a1, b1))
for n in names:
    x0, y0, x1, y1 = boxc(n)
    a0, b0 = wp(x0, y0)
    a1, b1 = wp(x1, y1)
    label((a0, b0, a1, b1), LABEL.get(n, n))
bx, by = R[0] + 10, R[3] - 10
dr.line([(bx, by), (bx + 10 / cell_km * cs, by)], fill=INK, width=4)
dr.text((bx, by - 26), "10 km en el juego", font=FS, fill=INK)

# Tamaño total frente al condado de Knox, en texto.
pw = (cx1 - cx0 - 2) * cell_km
ph = (cy1 - cy0 - 2) * cell_km
town_cells = sum(towns[n]["cx"] * towns[n]["cy"] for n in names)
road_km = sum(l["game_km"] for l in links_out)
for i, line in enumerate([
        f"Provincia en el juego: {pw:.0f} x {ph:.0f} km  (condado de Knox original: 40 x 32 km)",
        f"{len(names)} pueblos a 2 m/tile: {town_cells} celdas  |  {len(links_out)} carreteras de enlace: {road_km:.0f} km",
        "Todos los pueblos con el norte arriba, para que las carreteras encajen entre mapas"]):
    dr.text((R[0] + 260, R[3] - 90 + i * 26), line, font=FS, fill=INK)
img.save(OUT / "plano.png")

# Resumen
print(f"compresión {K}")
for n, t in towns.items():
    print(f"  {n:20s} celda {t['cell']}  {t['cx']}x{t['cy']}  giro {t['rot']:.0f}°")
tot = 0
for l in links_out:
    x0, y0, x1, y1 = l["bbox_cells"]
    tot += l["game_km"]
    print(f"  {l['a']:20s}-{l['b']:20s} {l['ref']:9s} real {l['real_km']:5.1f} km -> juego {l['game_km']:4.1f} km  caja {x1-x0+1}x{y1-y0+1}")
print(f"carreteras de enlace: {tot:.0f} km en el juego")
