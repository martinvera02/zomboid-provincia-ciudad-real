"""Descarga los edificios del Catastro (servicio INSPIRE ATOM) de una lista de
municipios y los deja descomprimidos, listos para catastro_merge.py.

Uso:
    python descargar_catastro.py <carpeta_salida> <código> [<código> ...]
    python descargar_catastro.py datos/catastro 13900 13056 13071

<código> es el código INE de cinco cifras que usa el Catastro (las dos
primeras son la provincia: 13 = Ciudad Real). Ojo: algunas capitales tienen
un código propio del Catastro (Ciudad Real es 13900). Para ver los de una
provincia:  python descargar_catastro.py --lista 13

Cada municipio queda en <carpeta_salida>/A.ES.SDGC.BU.<código>/ con sus
*.building.gml y *.buildingpart.gml.
Datos: © Dirección General del Catastro.
"""
from __future__ import annotations

import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

FEED = "https://www.catastro.hacienda.gob.es/INSPIRE/buildings/{p}/ES.SDGC.bu.atom_{p}.xml"


def get(url: str, tries: int = 4) -> bytes:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                return r.read()
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def zips_of_province(prov: str) -> dict[str, str]:
    """{código: url del zip} de todos los municipios de una provincia."""
    xml = get(FEED.format(p=prov)).decode("utf-8", "replace")
    out = {}
    for url in re.findall(r'href="([^"]+\.zip)"', xml):
        m = re.search(r"BU\.(\d{5})\.zip", url)
        if m:
            out[m.group(1)] = urllib.parse.quote(url, safe=":/.-_")
    return out


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--lista":
        xml = get(FEED.format(p=sys.argv[2])).decode("utf-8", "replace")
        for code, name in sorted(set(re.findall(r"/(\d{5})-([^/]+)/A\.ES", xml))):
            print(code, urllib.parse.unquote(name))
        return 0
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    dest = Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    codes = sys.argv[2:]
    by_prov: dict[str, dict[str, str]] = {}
    for code in codes:
        prov = code[:2]
        if prov not in by_prov:
            by_prov[prov] = zips_of_province(prov)
        url = by_prov[prov].get(code)
        if not url:
            print(f"{code}: no está en el Catastro de la provincia {prov}")
            continue
        zpath = dest / f"A.ES.SDGC.BU.{code}.zip"
        zpath.write_bytes(get(url))
        with zipfile.ZipFile(zpath) as z:
            z.extractall(dest / zpath.stem)
        print(f"{code}: {zpath.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
