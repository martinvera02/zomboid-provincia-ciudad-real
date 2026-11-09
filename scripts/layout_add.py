"""Añade pueblos al plano sin mover los que ya están.

Uso: python layout_add.py <knoxmap> <layout.json actual> <links.json> <salida.json> <pueblo,pueblo,...>

- Los pueblos que ya están en el plano conservan su celda.
- Cada pueblo nuevo va a su posición real escalada igual que el resto (misma
  compresión y misma referencia, Ciudad Real), y si choca con algo (pueblos,
  enlaces ya generados en <knoxmap>/output o el condado de Knox original) se
  mueve a la posición libre más cercana.
- Se añaden al plano los enlaces de links.json en los que participa algún
  pueblo nuevo, con la forma de la carretera real pasada al mundo del juego.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np

KNOX = Path(sys.argv[1])
OLD = json.loads(Path(sys.argv[2]).read_text())
LINKS = json.loads(Path(sys.argv[3]).read_text())["links"]
OUT = Path(sys.argv[4])
NEW = [t for t in sys.argv[5].split(",") if t]

sys.path.insert(0, str(KNOX))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_cr import PUEBLOS  # noqa: E402
from generator.rendering.projection import Projector  # noqa: E402

CELL = 300
MPT = OLD["meters_per_tile"]
K = OLD["compression"]
GAP = 2
VANILLA = (0, 0, 67, 54)
cell_km = CELL * MPT / 1000

towns = {}
for name in list(OLD["towns"]) + NEW:
    s, w, n, e = PUEBLOS[name]
    proj = Projector.build(s, w, n, e, MPT, 0.0)
    towns[name] = {"proj": proj, "cx": proj.width // CELL, "cy": proj.height // CELL,
                   "lonlat": ((w + e) / 2, (s + n) / 2)}
lon0, lat0 = towns["CiudadReal"]["lonlat"]
kx = 111.32 * math.cos(math.radians(lat0))


def raw_cell(n):
    t = towns[n]
    lo, la = t["lonlat"]
    real = ((lo - lon0) * kx, (la - lat0) * 111.32)
    return (real[0] * K / cell_km - t["cx"] / 2, -real[1] * K / cell_km - t["cy"] / 2)


# Desplazamiento del plano actual respecto a la posición escalada pura.
rx, ry = raw_cell("CiudadReal")
shift = (OLD["towns"]["CiudadReal"]["cell_x"] - rx, OLD["towns"]["CiudadReal"]["cell_y"] - ry)
for n, t in OLD["towns"].items():
    towns[n]["cell"] = (t["cell_x"], t["cell_y"])

# Lo que ya ocupa el mundo: pueblos, enlaces y cruces generados, y Knox.
taken = [(t["cell_x"], t["cell_y"], *t["cells"]) for t in OLD["towns"].values()]
out_dir = KNOX / "output"
for entry in os.listdir(out_dir):
    if entry.startswith(("Enlace_", "Cruce_")):
        try:
            pl = json.loads((out_dir / entry / "placement.json").read_text())
            inf = json.loads((out_dir / entry / f"{entry}_info.json").read_text())
            taken.append((pl["cell_x"], pl["cell_y"], inf["cells_x"], inf["cells_y"]))
        except (OSError, ValueError, KeyError):
            pass
taken.append(VANILLA)


def free(x, y, w, h):
    if x < 0 or y < 0 or x + w > 400 or y + h > 400:
        return False
    for ox, oy, ow, oh in taken:
        if x < ox + ow + GAP and ox < x + w + GAP and y < oy + oh + GAP and oy < y + h + GAP:
            return False
    return True


for n in NEW:
    t = towns[n]
    wx, wy = raw_cell(n)
    want = (round(wx + shift[0]), round(wy + shift[1]))
    best = None
    for r in range(0, 120):
        ring = [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1) if max(abs(dx), abs(dy)) == r]
        for dx, dy in sorted(ring, key=lambda d: d[0] ** 2 + d[1] ** 2):
            if free(want[0] + dx, want[1] + dy, t["cx"], t["cy"]):
                best = (want[0] + dx, want[1] + dy)
                break
        if best:
            break
    t["cell"] = best
    taken.append((*best, t["cx"], t["cy"]))
    moved = math.dist(best, want)
    print(f"  {n:14s} celda {best}  {t['cx']}x{t['cy']}"
          + (f"  (desplazado {moved * cell_km:.1f} km de su sitio escalado)" if moved > 1 else ""))


def to_world(name, lon, lat):
    t = towns[name]
    px, py = t["proj"].to_px(lat, lon)
    return t["cell"][0] * CELL + px, t["cell"][1] * CELL + py


def inside_map(name, lon, lat):
    px, py = towns[name]["proj"].to_px(lat, lon)
    return 0 <= px < towns[name]["cx"] * CELL and 0 <= py < towns[name]["cy"] * CELL


new_links = []
for l in LINKS:
    a, b = l["a"], l["b"]
    if a not in towns or b not in towns or (a not in NEW and b not in NEW):
        continue
    pts = l["points"]
    ins_a = [i for i, p in enumerate(pts) if inside_map(a, *p)]
    ins_b = [i for i, p in enumerate(pts) if inside_map(b, *p)]
    i0 = max(ins_a) if ins_a else 0
    i1 = min(ins_b) if ins_b else len(pts) - 1
    seg = pts[i0:i1 + 1] if i1 > i0 else [pts[i0], pts[min(i0 + 1, len(pts) - 1)]]
    cum = np.concatenate([[0], np.cumsum([math.dist(p, q) for p, q in zip(seg, seg[1:])])])
    frac = cum / (cum[-1] or 1)
    world = [((1 - f) * np.array(to_world(a, *p)) + f * np.array(to_world(b, *p))).tolist()
             for p, f in zip(seg, frac)]
    simp = [world[0]]
    for p in world[1:-1]:
        if math.dist(p, simp[-1]) >= 60:
            simp.append(p)
    simp.append(world[-1])
    length = sum(math.dist(p, q) for p, q in zip(simp, simp[1:]))
    new_links.append({"a": a, "b": b, "ref": l["ref"], "real_km": l["km"],
                      "game_km": round(length * MPT / 1000, 1),
                      "points": [[round(x), round(y)] for x, y in simp]})
    print(f"  enlace {a}-{b} ({l['ref']}): real {l['km']} km -> juego {length * MPT / 1000:.1f} km")

lay = dict(OLD)
lay["towns"] = dict(OLD["towns"])
for n in NEW:
    t = towns[n]
    lay["towns"][n] = {"cell_x": t["cell"][0], "cell_y": t["cell"][1], "cells": [t["cx"], t["cy"]], "rotation": 0.0}
lay["links"] = list(OLD["links"]) + new_links
OUT.write_text(json.dumps(lay, indent=1, ensure_ascii=False))
print(f"escrito {OUT}")
