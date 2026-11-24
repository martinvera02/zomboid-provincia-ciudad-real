"""Edificios singulares de Ciudad Real, rehechos a mano con tiles del juego.

KnoxMap levanta cada edificio con un estilo genérico de su tipo: la catedral
sale como una iglesia de madera de Kentucky y el ayuntamiento como una oficina.
Este script, que se lanza DESPUÉS de provincia.py y ANTES de compilar,
sustituye los .tbx de unos cuantos edificios concretos:

  - Iglesias (catedral, San Pedro, Santiago, la Merced): se vuelven a
    construir con nave y torre. La nave lleva varias plantas de altura y la
    torre sube por encima, con su escalera; el material es piedra y el tejado
    de teja, con la torre en pizarra donde la real la tiene.
  - Ayuntamiento: piedra gris y tejado de pizarra, como el de Higueras.
  - Hospital General: ladrillo y piedra clara en vez del blanco genérico,
    conservando el interior de hospital que hizo KnoxMap.
  - Plaza Mayor: las fachadas que dan a la plaza en ocre y crema con teja.

Cada edificio se ocupa en la misma huella y en la misma caja que le dio
KnoxMap, así que no pisa a ningún vecino ni hay que recolocar nada.

Uso (desde la carpeta de KnoxMap, con su Python):
    .venv\\Scripts\\python.exe ..\\ProvinciaCR\\monumentos.py .
    .venv\\Scripts\\python.exe ..\\ProvinciaCR\\monumentos.py . --vistas carpeta_png
Luego compilar como siempre (compilar.py). Para deshacerlo basta con volver
a generar Ciudad Real.
"""
from __future__ import annotations

import argparse
import copy
import csv
import os
import random
import re
import sys
import zlib

MAPA = "CiudadReal"
MARCA = "<!-- monumentos.py -->"

# ---------------------------------------------------------------------------
# Materiales: un muro de casa de la hoja walls_exterior_house_0X y la hoja con
# los huecos de ventana del mismo material (cada material tiene 16 variantes
# de hueco, una por tipo de ventana, en bloques de 32 tiles).
# ---------------------------------------------------------------------------
MATERIALES = {
    "piedra_dorada": ("walls_exterior_house_02", 4, "walls_exterior_house_07", 0),
    "piedra_clara": ("walls_exterior_house_02", 0, "walls_exterior_house_06", 96),
    "piedra_gris": ("walls_exterior_house_02", 16, "walls_exterior_house_07", 32),
    "pizarra_gris": ("walls_exterior_house_01", 0, "walls_exterior_house_05", 0),
    "ladrillo": ("walls_exterior_house_01", 16, "walls_exterior_house_05", 64),
    "ladrillo_rojo": ("walls_exterior_house_01", 4, "walls_exterior_house_05", 32),
    "crema": ("walls_exterior_house_02", 48, "walls_exterior_house_08", 32),
    "ocre": ("walls_exterior_house_02", 84, "walls_exterior_house_09", 64),
}

# Tejados completos (faldones, remates y piñones) sacados de los estilos de
# casa del juego que los usan.
TEJADOS = {
    "teja": "painted",        # roofs_04: rojo
    "pizarra": "clapboard",   # roofs_01: gris azulado
    "marron": "brick",        # roofs_02
}

# Los piñones (el triángulo de muro bajo un tejado a dos aguas) van con el
# muro, no con el tejado: se toman del estilo de casa del material más
# parecido, para que no salga un hastial de madera blanca en una iglesia.
PINONES = {
    "piedra_dorada": "stucco", "piedra_gris": "panel", "pizarra_gris": "siding_grey",
    "ladrillo": "brick", "ladrillo_rojo": "brick",
    # Sin estilo de casa propio: los piñones de stucco pasados a la hoja del
    # mismo material (walls_exterior_roofs_XX, bloques de 24 tiles).
    "piedra_clara": ("walls_exterior_roofs_08", 0),
    "crema": ("walls_exterior_roofs_07", 0),
    "ocre": ("walls_exterior_roofs_01", 192),
}

VENTANAS = {
    "vidriera": ("fixtures_windows_church_014", "fixtures_windows_church_015"),
    "blanca": ("fixtures_windows_white_022", "fixtures_windows_white_023"),
}


def _t(sheet: str, n: int) -> str:
    return f"{sheet}_{n:03d}"


def muro(material: str) -> dict:
    sheet, b, cuts, c = MATERIALES[material]
    tiles = {
        "West": _t(sheet, b), "North": _t(sheet, b + 1),
        "NorthWest": _t(sheet, b + 2), "SouthEast": _t(sheet, b + 3),
        "WestWindow": _t(sheet, b + 8), "NorthWindow": _t(sheet, b + 9),
        "WestDoor": _t(sheet, b + 10), "NorthDoor": _t(sheet, b + 11),
    }
    for k in range(1, 17):
        tiles[f"WestWindow{k}"] = _t(cuts, c + 2 * (k - 1))
        tiles[f"NorthWindow{k}"] = _t(cuts, c + 2 * (k - 1) + 1)
    for k in range(17, 20):
        tiles[f"WestWindow{k}"] = tiles["WestWindow"]
        tiles[f"NorthWindow{k}"] = tiles["NorthWindow"]
    return {"category": "exterior_walls", "tiles": tiles}


def _casa(nombre: str) -> dict:
    from knoxbuild import catalog as C
    for s in C.HOUSE_STYLES:
        if s["name"] == nombre:
            return s
    raise KeyError(nombre)


def _pinones(material: str) -> dict:
    fuente = PINONES[material]
    if isinstance(fuente, str):
        return copy.deepcopy(_casa(fuente)["roof"]["caps"])
    hoja, base = fuente
    tiles = {}
    for k, v in _casa("stucco")["roof"]["caps"]["tiles"].items():
        m = re.match(r"^walls_exterior_roofs_01_(\d+)$", v)
        # Solo los de 45 grados: sin piñones de 30 grados el tejado se hace a
        # 45 (render_tbx mira si existe CapPeak30S1), y los tejados bajos no
        # se usan aquí.
        if m and "30" not in k and "Shallow" not in k:
            tiles[k] = _t(hoja, base + int(m.group(1)) - 96)
    sheet, b, _, _ = MATERIALES[material]
    tiles["CapGapE3"], tiles["CapGapS3"] = _t(sheet, b), _t(sheet, b + 1)
    return {"category": "roof_caps", "tiles": tiles}


def tejado(nombre: str, material: str | None = None) -> dict:
    kit = copy.deepcopy(_casa(TEJADOS[nombre])["roof"])
    if material:
        kit["caps"] = _pinones(material)
    return kit


def estilo(base: str, material: str, cubierta: str | None, ventana: str | None = None,
           kind: str | None = None, nombre: str = "monumento") -> dict:
    """Un estilo de KnoxMap (el de `base`) con otro muro, tejado y ventana."""
    from knoxbuild import build as B
    s = copy.deepcopy(B.style_named(base, kind) or B.style_named(base, None))
    s["name"] = nombre
    s["exterior"] = muro(material)
    if cubierta:
        s["roof"] = tejado(cubierta, material)
    if ventana:
        w, n = VENTANAS[ventana]
        s["window"] = {"category": "windows", "tiles": {"West": w, "North": n}}
        s["windows_by_levels"] = []
    s.pop("grime", None)
    s.pop("shutters", None)
    return s


# ---------------------------------------------------------------------------
# Leer y reescribir .tbx
# ---------------------------------------------------------------------------

def huella(text: str) -> list[list[bool]]:
    from knoxbuild import buildtiles as BT
    b = BT.parse_tbx(text)
    return [[bool(v) for v in row] for row in b.floors[0].rooms]


_ENTRY = re.compile(r'( <tile_entry category="([a-z_]+)">\n)(.*?)( </tile_entry>\n)', re.S)


def _entry_xml(tiles: dict) -> str:
    return "".join(f'  <tile enum="{k}" tile="{v}"/>\n' for k, v in tiles.items())


def recubrir(text: str, s: dict) -> str:
    """Cambia muros exteriores y tejado de un .tbx ya hecho, sin tocar su planta
    ni sus muebles: cada entrada de esas categorías se reescribe con las mismas
    claves (West, North, SlopeS1...) apuntando a los tiles nuevos."""
    kit = s.get("roof") or {}
    nuevo = {"exterior_walls": s["exterior"]["tiles"],
             "roof_slopes": (kit.get("slopes") or {}).get("tiles"),
             "roof_tops": (kit.get("tops") or {}).get("tiles"),
             "roof_caps": (kit.get("caps") or {}).get("tiles")}
    if s.get("window"):
        nuevo["windows"] = s["window"]["tiles"]
    ext = s["exterior"]["tiles"]

    def swap(m):
        cat = m.group(2)
        tiles = nuevo.get(cat)
        if not tiles:
            return m.group(0)
        out = []
        for line in m.group(3).splitlines(keepends=True):
            e = re.search(r'enum="([^"]+)"', line)
            key = e.group(1) if e else None
            if key in tiles:
                line = re.sub(r'tile="[^"]*"', f'tile="{tiles[key]}"', line)
            elif cat == "roof_caps" and key in ("CapGapE3", "CapGapS3"):
                line = re.sub(r'tile="[^"]*"', f'tile="{ext["West" if key.endswith("E3") else "North"]}"', line)
            out.append(line)
        return m.group(1) + "".join(out) + m.group(4)

    return _ENTRY.sub(swap, text)


def tejado_torre(text: str, torre: tuple, kit: dict | None, piramide: bool = True) -> str:
    """El tejado de la torre: los objetos <roof> que caen dentro de la caja de la
    torre pasan a un tejado propio (p. ej. pizarra) y, si la torre es cuadrada y
    de lado impar, a un chapitel de cuatro aguas en vez de a dos."""
    tx0, ty0, tx1, ty1 = torre
    entries = list(_ENTRY.finditer(text))
    n = len(entries)
    idx = {}
    if kit:
        extra = ""
        for key, cat in (("slopes", "roof_slopes"), ("tops", "roof_tops"), ("caps", "roof_caps")):
            tiles = (kit.get(key) or {}).get("tiles")
            if tiles:
                n += 1
                idx[key] = n
                extra += f' <tile_entry category="{cat}">\n{_entry_xml(tiles)} </tile_entry>\n'
        last = entries[-1]
        text = text[:last.end()] + extra + text[last.end():]
    lado = tx1 - tx0 + 1
    cuadrada = piramide and lado == ty1 - ty0 + 1 and lado % 2 == 1

    def obj(m):
        o = m.group(0)
        g = {k: int(re.search(f' {k}="(\\d+)"', o).group(1)) for k in ("x", "y", "width", "height")}
        dentro = (tx0 <= g["x"] and g["x"] + g["width"] - 1 <= tx1
                  and ty0 <= g["y"] and g["y"] + g["height"] - 1 <= ty1)
        if not dentro:
            return o
        if cuadrada and 'RoofType="FlatTop"' in o and 'Depth="Three"' in o and g["width"] * g["height"] < lado * lado:
            return ""          # la tira plana que deja un tejado par: la tapa el chapitel
        for key, attr in (("slopes", "SlopeTiles"), ("tops", "TopTiles"), ("caps", "CapTiles")):
            if key in idx:
                o = re.sub(f'{attr}="\\d+"', f'{attr}="{idx[key]}"', o)
        if cuadrada and 'RoofType="FlatTop"' not in o:
            o = re.sub(r'RoofType="[^"]+"', 'RoofType="Peak30Quad"', o)
            o = re.sub(r'Depth="[^"]+"', 'Depth="Zero"', o)
            for c in ("W", "N", "E", "S"):
                o = o.replace(f'capped{c}="true"', f'capped{c}="false"')
            o = re.sub(r' x="\d+"', f' x="{tx0}"', o)
            o = re.sub(r' y="\d+"', f' y="{ty0}"', o)
            o = re.sub(r' width="\d+"', f' width="{lado}"', o)
            o = re.sub(r' height="\d+"', f' height="{lado}"', o)
        return o

    return re.sub(r'  <object type="roof"[^>]*/>\n', obj, text)


# ---------------------------------------------------------------------------
# Iglesias: nave alta y torre
# ---------------------------------------------------------------------------

def _rect_mask(w, h, rects, base=None):
    m = [[False] * w for _ in range(h)]
    for x0, y0, x1, y1 in rects:
        for y in range(max(0, y0), min(h, y1 + 1)):
            for x in range(max(0, x0), min(w, x1 + 1)):
                m[y][x] = True if base is None else base[y][x]
    return m


def _and(a, b):
    return [[a[y][x] and b[y][x] for x in range(len(a[0]))] for y in range(len(a))]


def _or(a, b):
    return [[a[y][x] or b[y][x] for x in range(len(a[0]))] for y in range(len(a))]


def escalonado(width, height, plantas, kind, seed, core, arriba="storage"):
    """Un edificio cuya planta cambia de forma con la altura (nave + torre).

    `plantas` es una máscara por planta, de abajo arriba; la escalera (`core`)
    tiene que caber en todas. Las plantas altas de la nave quedan como
    desvanes; la torre es la que sube hasta arriba."""
    from knoxbuild import layout as L
    from knoxbuild.settings import Settings
    levels = len(plantas)
    stairs = L._stairs_in_core(core)
    settings = Settings()
    storeys = []
    for lvl, m in enumerate(plantas):
        p = L.build_plan(width, height, commercial=False, seed=seed + 977 * lvl,
                         kind=kind if lvl == 0 else arriba, mask=m, ground=(lvl == 0),
                         settings=settings, core=core, level=lvl, levels=levels,
                         stairs=stairs)
        storeys.append(p)
    b = L.Building(width=width, height=height, storeys=storeys)
    for lvl in range(levels - 1):
        b.stairs.append(stairs)
        L._clear_for_stairs(storeys[lvl], *stairs)
        L._clear_for_stairs(storeys[lvl + 1], *stairs)
    L._place_windows(b, kind)
    L._clear_the_way(b)
    return b


def _caja_libre(mask, w, h, cerca):
    """La caja w x h llena de huella más cercana al punto `cerca`."""
    H, W = len(mask), len(mask[0])
    best = None
    for y0 in range(H - h + 1):
        for x0 in range(W - w + 1):
            if all(mask[y][x] for y in range(y0, y0 + h) for x in range(x0, x0 + w)):
                d = (x0 + w / 2 - cerca[0]) ** 2 + (y0 + h / 2 - cerca[1]) ** 2
                if best is None or d < best[0]:
                    best = (d, (x0, y0, x0 + w - 1, y0 + h - 1))
    return best[1] if best else None


def _nave(mask, eje, ancho):
    """La banda más larga de `ancho` tiles a lo largo del eje ('x' o 'y') que
    cabe en la huella: el cuerpo de la iglesia."""
    H, W = len(mask), len(mask[0])
    best = None
    rng = range(H - ancho + 1) if eje == "x" else range(W - ancho + 1)
    for a in rng:
        # columnas (o filas) llenas en toda la banda
        largo = W if eje == "x" else H
        full = [all(mask[a + k][i] if eje == "x" else mask[i][a + k] for k in range(ancho))
                for i in range(largo)]
        run = start = 0
        for i, f in enumerate(full + [False]):
            if f:
                if run == 0:
                    start = i
                run += 1
            else:
                if run and (best is None or run > best[0]):
                    best = (run, a, start, start + run - 1)
                run = 0
    if best is None:
        return None
    _, a, s, e = best
    return (s, a, e, a + ancho - 1) if eje == "x" else (a, s, a + ancho - 1, e)


IGLESIAS = {
    # nombre en el CSV: (material, tejado nave, tejado torre, eje nave, ancho nave,
    #                    plantas nave, lado torre, plantas torre, extremo torre)
    "Catedral de Santa María del Prado": dict(
        material="piedra_clara", nave="teja", torre="pizarra", eje="x", ancho=12,
        alto=3, lado=7, alto_torre=8, extremo="oeste"),
    "Iglesia de San Pedro": dict(
        material="piedra_clara", nave="teja", torre="pizarra", eje="x", ancho=10,
        alto=3, lado=7, alto_torre=7, extremo="oeste"),
    "Iglesia de Santiago": dict(
        material="piedra_dorada", nave="teja", torre="teja", eje="x", ancho=9,
        alto=2, lado=7, alto_torre=5, extremo="oeste"),
    "Iglesia de la Merced": dict(
        material="crema", nave="teja", torre="teja", eje="y", ancho=5,
        alto=2, lado=6, alto_torre=4, extremo="norte"),
}


def iglesia(row, text, cfg, seed):
    mask = huella(text)
    H, W = len(mask), len(mask[0])
    nave = _nave(mask, cfg["eje"], cfg["ancho"]) or (0, 0, W - 1, H - 1)
    nx0, ny0, nx1, ny1 = nave
    lado = cfg["lado"]
    # la torre a los pies de la nave, pegada a ella
    cerca = {"oeste": (nx0, (ny0 + ny1) / 2), "este": (nx1, (ny0 + ny1) / 2),
             "norte": ((nx0 + nx1) / 2, ny0), "sur": ((nx0 + nx1) / 2, ny1)}[cfg["extremo"]]
    torre = None
    for l in (lado, lado - 1, 5):
        torre = _caja_libre(mask, l, l, cerca) if l >= 6 else None
        if torre:
            break
    if torre is None:
        torre = _caja_libre(mask, 3, 6, cerca) or _caja_libre(mask, 6, 3, cerca)
    tx0, ty0, tx1, ty1 = torre
    # escalera dentro de la torre: 3 x 6 contra un lado
    core = (tx0, ty0, tx0 + 2, ty0 + 5) if ty1 - ty0 >= 5 else (tx0, ty0, tx0 + 5, ty0 + 2)
    m_nave = _rect_mask(W, H, [nave], mask)
    m_torre = _rect_mask(W, H, [torre], mask)
    plantas = [mask]
    for lvl in range(1, max(cfg["alto"], cfg["alto_torre"])):
        m = [[False] * W for _ in range(H)]
        if lvl < cfg["alto"]:
            m = _or(m, m_nave)
        if lvl < cfg["alto_torre"]:
            m = _or(m, m_torre)
        plantas.append(m)
    b = escalonado(W, H, plantas, "church", seed, core)
    # La torre es muro casi ciego: ventanas solo en el campanario (la última
    # planta) y alguna saetera a media altura.
    arriba = len(b.storeys) - 1
    for lvl in range(cfg["alto"], arriba):
        if (arriba - lvl) % 3:
            b.storeys[lvl].windows = []
    from knoxbuild.tbx import render_tbx
    s = estilo("church_stucco", cfg["material"], cfg["nave"], "vidriera", "church",
               "monumento_" + cfg["material"])
    out = render_tbx(b, row["name"], s)
    kit = tejado(cfg["torre"], cfg["material"]) if cfg["torre"] != cfg["nave"] else None
    out = tejado_torre(out, torre, kit)
    return out, {"nave": nave, "torre": torre, "plantas": len(plantas)}


# ---------------------------------------------------------------------------
# Lo demás: mismo edificio, otros materiales
# ---------------------------------------------------------------------------

AYUNTAMIENTO = dict(material="piedra_clara", tejado="pizarra", ventana="blanca")

HOSPITAL = [  # por orden de tramo: el bloque de hospitalización en ladrillo
    dict(material="ladrillo_rojo", tejado=None),
    dict(material="piedra_clara", tejado=None),
    dict(material="ladrillo_rojo", tejado=None),
    dict(material="piedra_gris", tejado=None),
    dict(material="ladrillo_rojo", tejado=None),
    dict(material="piedra_clara", tejado=None),
    dict(material="ladrillo_rojo", tejado=None),
    dict(material="piedra_clara", tejado=None),
]

# El contorno de la Plaza Mayor (OSM, relación 9735636) en tiles del mapa de
# Ciudad Real; los edificios a menos de PLAZA_DIST tiles se pintan.
PLAZA = [(1255, 1319), (1249, 1277), (1245, 1277), (1233, 1281), (1227, 1283),
         (1226, 1285), (1229, 1293), (1231, 1298), (1233, 1303), (1236, 1312),
         (1238, 1316), (1240, 1322), (1243, 1322), (1254, 1320)]
PLAZA_DIST = 4
PLAZA_MATERIALES = ["ocre", "crema", "piedra_clara"]


def picos(text: str, lado: int = 3) -> str:
    """Cambia el tejado de arriba por una fila de chapiteles de `lado` x `lado`
    (cuatro aguas a 30 grados): los picos de pizarra del ayuntamiento."""
    floors = text.split("<floor>")
    for i in range(len(floors) - 1, 0, -1):
        roofs = re.findall(r'  <object type="roof"[^>]*/>\n', floors[i])
        if roofs:
            break
    else:
        return text
    plantilla = next((r for r in roofs if 'RoofType="FlatTop"' not in r), roofs[0])
    W = int(re.search(r'width="(\d+)"', text).group(1))
    H = int(re.search(r'height="(\d+)"', text).group(1))
    mask = huella(text)
    nuevos = []
    for y0 in range(0, H - lado + 1, lado):
        for x0 in range(0, W - lado + 1, lado):
            if not all(mask[y][x] for y in range(y0, y0 + lado) for x in range(x0, x0 + lado)):
                continue
            o = plantilla
            for k, v in (("x", x0), ("y", y0), ("width", lado), ("height", lado)):
                o = re.sub(f' {k}="\\d+"', f' {k}="{v}"', o)
            o = re.sub(r'RoofType="[^"]+"', 'RoofType="Peak30Quad"', o)
            o = re.sub(r'Depth="[^"]+"', 'Depth="Zero"', o)
            o = re.sub(r'capped([WNES])="true"', r'capped\1="false"', o)
            nuevos.append(o)
    if not nuevos:
        return text
    body = floors[i]
    for r in roofs:
        body = body.replace(r, "", 1)
    head, sep, tail = body.partition("  <rooms>")
    if not sep:
        head, sep, tail = body.partition("</floor>")
    floors[i] = head + "".join(nuevos) + sep + tail
    return "<floor>".join(floors)


def ayuntamiento_tbx(row, text):
    """El ayuntamiento se rehace entero para que lleve tejado (KnoxMap pone a
    los edificios públicos azotea) y, en vez de un tejado a dos aguas, los
    picos de pizarra del edificio de Higueras."""
    mask = huella(text)
    H, W = len(mask), len(mask[0])
    levels = min(int(row["levels"]), 4)
    from knoxbuild import layout as L
    from knoxbuild.tbx import render_tbx
    b = L.build_building(W, H, levels=levels, kind="civic", seed=1976, mask=mask)
    s = estilo("church_stucco", AYUNTAMIENTO["material"], AYUNTAMIENTO["tejado"],
               AYUNTAMIENTO["ventana"], "church", "monumento_ayuntamiento")
    return picos(render_tbx(b, row["name"], s))


# La comisaría provincial de la Policía Nacional, en el cruce de la Ronda de
# Toledo con la calle Carlos López Bustos. En el Catastro son dos edificios; el
# grande se rehace como comisaría de KnoxMap (calabozos, taquillas, armero...).
COMISARIA = dict(nombre="Policía Nacional", lat=38.99283, lon=-3.92276, plantas=3)


def comisaria_rows(rows):
    found = [r for r in rows if r["name"] == COMISARIA["nombre"]]
    if found or MAPA != "CiudadReal":
        return found
    # sin nombres (mapa generado con un .pbf antiguo): por su sitio
    try:
        from build_cr import PUEBLOS
        from generator.rendering.projection import Projector
        P = Projector.build(*PUEBLOS["CiudadReal"], 2.0, 0.0)
        x, y = P.to_px(COMISARIA["lat"], COMISARIA["lon"])
    except Exception:  # noqa: BLE001
        return []
    near = [r for r in rows
            if abs(int(r["tile_x"]) + int(r["width"]) / 2 - x) < 40
            and abs(int(r["tile_y"]) + int(r["height"]) / 2 - y) < 40]
    near.sort(key=lambda r: -int(r["width"]) * int(r["height"]))
    return near[:1]


def comisaria_tbx(row, text, grande):
    mask = huella(text)
    H, W = len(mask), len(mask[0])
    levels = max(int(row["levels"]), COMISARIA["plantas"]) if grande else int(row["levels"])
    import random as _r
    from knoxbuild import build as B, layout as L
    from knoxbuild.settings import Settings
    from knoxbuild.tbx import render_tbx
    b = L.build_building(W, H, levels=levels, kind="police", seed=1840, mask=mask)
    s = B.pick_style("police", 0, 0, _r.Random(1840), Settings())
    return render_tbx(b, row["name"] or "Comisaría", s), levels


def en_plaza(row) -> bool:
    from shapely.geometry import Polygon, box
    tx, ty, w, h = (int(row[k]) for k in ("tile_x", "tile_y", "width", "height"))
    return box(tx, ty, tx + w, ty + h).distance(Polygon(PLAZA)) <= PLAZA_DIST


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("knoxmap", help="carpeta de KnoxMap")
    ap.add_argument("--vistas", help="carpeta donde dejar un PNG de cada edificio (necesita los tiles)")
    a = ap.parse_args(argv)
    knox = os.path.abspath(a.knoxmap)
    sys.path.insert(0, knox)
    os.chdir(knox)
    out_dir = os.path.join(knox, "output", MAPA)
    bdir = os.path.join(out_dir, "buildings")
    with open(os.path.join(out_dir, f"{MAPA}_placements.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    hechos = []

    def leer(row):
        with open(os.path.join(bdir, row["file"]), encoding="utf-8") as f:
            return f.read()

    def escribir(row, text, que):
        path = os.path.join(bdir, row["file"])
        original(row)          # guarda el de KnoxMap si aún no está guardado
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("?>", "?>\n" + MARCA, 1))
        hechos.append((row, que))
        print(f"  {row['file']:28s} {row['name'][:40]:40s} {que}")

    def original(row):
        """El .tbx que hizo KnoxMap. Se guarda aparte (.tbx.orig) la primera
        vez; si el .tbx actual no lleva nuestra marca es que KnoxMap lo ha
        vuelto a generar, y ese pasa a ser el original."""
        orig = os.path.join(bdir, row["file"] + ".orig")
        actual = leer(row)
        if MARCA not in actual:
            with open(orig, "w", encoding="utf-8") as f:
                f.write(actual)
            return actual
        with open(orig, encoding="utf-8") as f:
            return f.read()

    print("Iglesias:")
    for name, cfg in IGLESIAS.items():
        row = next((r for r in rows if r["name"] == name), None)
        if row is None:
            print(f"  (no está: {name})")
            continue
        text, info = iglesia(row, original(row), cfg, seed=zlib.crc32(name.encode()) & 0xFFFF)
        escribir(row, text, f"nave {info['nave']} torre {info['torre']} {info['plantas']} plantas")

    print("Ayuntamiento:")
    row = next((r for r in rows if r["name"] == "Ayuntamiento"), None)
    if row:
        escribir(row, ayuntamiento_tbx(row, original(row)), "piedra gris, pizarra")

    print("Comisaría:")
    comis = comisaria_rows(rows)
    comis.sort(key=lambda r: -int(r["width"]) * int(r["height"]))
    for i, row in enumerate(comis):
        text, lv = comisaria_tbx(row, original(row), i == 0)
        escribir(row, text, f"comisaría, {lv} plantas")

    print("Hospital General:")
    tramos = [r for r in rows if r["name"].startswith("Hospital General de Ciudad Real")]
    tramos.sort(key=lambda r: r["file"])
    for i, row in enumerate(tramos):
        cfg = HOSPITAL[i % len(HOSPITAL)]
        s = estilo("medical", cfg["material"], cfg["tejado"], None, "medical")
        escribir(row, recubrir(original(row), s), cfg["material"])

    print("Plaza Mayor:")
    nombres = {r["name"] for r, _ in hechos}
    k = 0
    for row in rows:
        if row["name"] in nombres or not en_plaza(row):
            continue
        mat = PLAZA_MATERIALES[k % len(PLAZA_MATERIALES)]
        k += 1
        # azoteas como las de la plaza: solo cambia la fachada
        s = estilo("painted", mat, None, "blanca")
        s["roof"] = {}
        escribir(row, recubrir(original(row), s), mat)

    if a.vistas:
        os.makedirs(a.vistas, exist_ok=True)
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(here, "tools"))
        sys.path.insert(0, os.path.join(os.path.dirname(here), "tools"))
        sys.path.insert(0, here)
        import vista_tbx as V
        tiles = os.environ.get("TILES") or os.path.join(knox, "vendor", "PZMappingTools", "Tiles", "2x")
        for row, _ in hechos:
            img = V.draw(V.squares_of(leer(row)), tiles, 0.5)
            img.convert("RGB").save(os.path.join(a.vistas, row["file"].replace(".tbx", ".png")))
    print(f"{len(hechos)} edificios cambiados. Ahora compila Ciudad Real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
