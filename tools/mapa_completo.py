"""Dibuja todos los mapas de KnoxMap juntos, cada uno en su sitio del mundo.

    python tools/mapa_completo.py <KnoxMap>/output mapa.png [--escala 5]

Usa el <mapa>.bmp de suelo de cada mapa (1 píxel por tile) y su
placement.json; --escala N junta N×N tiles en un píxel.
"""
import argparse
import json
import os

from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("png")
    ap.add_argument("--escala", type=int, default=5)
    a = ap.parse_args()
    F = a.escala
    mapas = []
    for n in sorted(os.listdir(a.output)):
        bmp = os.path.join(a.output, n, f"{n}.bmp")
        pl = os.path.join(a.output, n, "placement.json")
        if os.path.exists(bmp) and os.path.exists(pl):
            p = json.load(open(pl, encoding="utf-8"))
            mapas.append((n, p["cell_x"] * 300, p["cell_y"] * 300, Image.open(bmp).size))
    x0 = min(m[1] for m in mapas)
    y0 = min(m[2] for m in mapas)
    x1 = max(m[1] + m[3][0] for m in mapas)
    y1 = max(m[2] + m[3][1] for m in mapas)
    lienzo = Image.new("RGB", ((x1 - x0) // F, (y1 - y0) // F), (28, 28, 30))
    d = ImageDraw.Draw(lienzo)
    for n, x, y, (w, h) in mapas:
        im = Image.open(os.path.join(a.output, n, f"{n}.bmp")).convert("RGB")
        lienzo.paste(im.resize((w // F, h // F), Image.BOX), ((x - x0) // F, (y - y0) // F))
        if not n.startswith(("Enlace_", "Cruce_", "Relleno_")):
            d.text(((x - x0 + w / 2) // F, (y - y0 + h / 2) // F), n, fill=(255, 255, 255),
                   stroke_width=2, stroke_fill=(0, 0, 0))
    lienzo.save(a.png)
    print(f"{len(mapas)} mapas, {lienzo.size[0]}x{lienzo.size[1]} px -> {a.png}")


if __name__ == "__main__":
    main()
