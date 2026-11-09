"""Dibuja un edificio .tbx en isométrico, como lo pinta el juego, para revisarlo
sin compilar el mapa.

    python vista_tbx.py <edificio.tbx> <salida.png> <carpeta Tiles/2x> [--hasta N] [--escala S]

Usa el propio KnoxMap para convertir el .tbx en los tiles de cada casilla
(knoxbuild.buildtiles: muros, puertas, ventanas, tejados) y los apila igual que
tools/render_lots.py. Hay que lanzarlo con el Python de KnoxMap y desde su
carpeta (o con KNOXMAP apuntando a ella). Los tiles de hojas que no estén en la
carpeta se saltan (muebles, sobre todo), así que el exterior sale completo.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

from PIL import Image

KNOX = os.environ.get("KNOXMAP", os.getcwd())
sys.path.insert(0, KNOX)

from knoxbuild import buildtiles as BT  # noqa: E402

LEVEL_PX = 96


class Tiles:
    def __init__(self, folder: str, tw: int):
        self.folder, self.tw = folder, tw
        self.sheets: dict[str, Image.Image | None] = {}
        self.cache: dict[str, Image.Image | None] = {}

    def __call__(self, name: str):
        if name in self.cache:
            return self.cache[name]
        img = None
        m = re.match(r"^(.*)_(\d+)$", name)
        if m:
            sheet_name, idx = m.group(1), int(m.group(2))
            if sheet_name not in self.sheets:
                path = os.path.join(self.folder, f"{sheet_name}.png")
                self.sheets[sheet_name] = Image.open(path).convert("RGBA") if os.path.exists(path) else None
            sheet = self.sheets[sheet_name]
            if sheet is not None:
                cols = max(1, sheet.width // 128)
                cx, cy = (idx % cols) * 128, (idx // cols) * 256
                if cy + 256 <= sheet.height:
                    img = sheet.crop((cx, cy, cx + 128, cy + 256))
                    if self.tw != 64:
                        img = img.resize((self.tw, self.tw * 2), Image.LANCZOS)
                    else:
                        img = img.resize((64, 128), Image.LANCZOS)
        self.cache[name] = img
        return img


def squares_of(text: str, max_level: int | None = None) -> dict[tuple[int, int, int], list[str]]:
    b = BT.parse_tbx(text)
    out = {}
    for z in range(len(b.floors)):
        if max_level is not None and z > max_level:
            break
        for (x, y), tiles in BT.level_tiles(b, z).items():
            if tiles:
                out[(x, y, z)] = tiles
    return out


def draw(squares: dict, tiles_dir: str, scale: float = 1.0,
         ground: str | None = "floors_exterior_street_01_16", pad: int = 3) -> Image.Image:
    xs = [k[0] for k in squares]
    ys = [k[1] for k in squares]
    x0, y0 = min(xs) - pad, min(ys) - pad
    W, H = max(xs) - x0 + 1 + pad, max(ys) - y0 + 1 + pad
    top = max(k[2] for k in squares)
    TW = max(4, round(64 * scale))
    half, quarter, level_px = TW // 2, TW // 4, round(LEVEL_PX * TW / 64)
    tiles = Tiles(tiles_dir, TW)
    width = (W + H) * half + TW
    height = (W + H) * quarter + 2 * TW + (top + 1) * level_px
    canvas = Image.new("RGBA", (width, height), (34, 38, 42, 255))
    lift = (top + 1) * level_px
    for z in range(top + 1):
        for s in range(W + H - 1):
            for dx in range(max(0, s - H + 1), min(W, s + 1)):
                dy = s - dx
                names = squares.get((dx + x0, dy + y0, z), ())
                if z == 0 and ground and not names:
                    names = (ground,)
                for name in names:
                    img = tiles(name)
                    if img is not None:
                        canvas.alpha_composite(img, ((dx - dy) * half + H * half,
                                                     (dx + dy) * quarter + lift - z * level_px
                                                     - TW * 3 // 2))
    bbox = canvas.getbbox()
    return canvas.crop(bbox) if bbox else canvas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tbx")
    ap.add_argument("salida")
    ap.add_argument("tiles")
    ap.add_argument("--hasta", type=int, default=None, help="última planta que se dibuja")
    ap.add_argument("--escala", type=float, default=0.5)
    a = ap.parse_args(argv)
    text = open(a.tbx, encoding="utf-8").read()
    img = draw(squares_of(text, a.hasta), a.tiles, a.escala)
    img.convert("RGB").save(a.salida)
    print(a.salida, img.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
