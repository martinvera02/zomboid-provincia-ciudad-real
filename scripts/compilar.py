"""Compila e instala de una vez todos los mapas de la provincia (pueblos y
enlaces), uno detrás de otro, como si pulsaras Compile e Install en la ventana
de KnoxMap para cada uno.

Uso (Windows, desde la carpeta de KnoxMap, con la ventana de KnoxMap CERRADA):
    .venv\\Scripts\\python.exe ..\\ProvinciaCR\\compilar.py . ..\\ProvinciaCR\\layout.json

    --solo   mapas concretos separados por comas (por defecto: todos los
             pueblos del plano y todos los Enlace_* y Cruce_* generados)
    --sin-instalar   solo compila
    --forzar  vuelve a compilar aunque ya estuviera compilado (después de
              regenerar un pueblo o de pasar monumentos.py)

Si se corta (apagas el PC, falla un mapa), vuelve a lanzarlo: los mapas ya
compilados se saltan solos y solo se rehace lo que falte.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("knox")
    ap.add_argument("layout")
    ap.add_argument("--solo", default="")
    ap.add_argument("--sin-instalar", action="store_true")
    ap.add_argument("--forzar", action="store_true")
    args = ap.parse_args()

    knox = os.path.abspath(args.knox)
    layout = json.loads(open(args.layout, encoding="utf-8").read())
    out = os.path.join(knox, "output")
    if args.solo:
        maps = [m for m in args.solo.split(",") if m]
    else:
        maps = [t for t in layout["towns"] if os.path.isdir(os.path.join(out, t))]
        maps += sorted(e for e in os.listdir(out) if e.startswith(("Enlace_", "Cruce_")))
    missing = [m for m in maps if not os.path.isdir(os.path.join(out, m))]
    if missing:
        sys.exit(f"No están generados: {', '.join(missing)}. Lanza antes provincia.py.")

    sys.path.insert(0, knox)
    os.chdir(knox)
    import app as knoxapp
    from knoxbuild import placement as P

    client = knoxapp.app.test_client()
    results = {}
    t_all = time.time()
    for i, name in enumerate(maps, 1):
        print(f"\n[{i}/{len(maps)}] {name}", flush=True)
        try:
            map_dir = os.path.join(out, name)
            where = P.saved(map_dir) or P.project_origin(map_dir, name)
            st = client.get(f"/api/compile-status?map={name}").get_json() or {}
            done_before = not args.forzar and (st.get("cells", 0) > 0 and st.get("cells", 0) >= st.get("expected", 1)
                           and not st.get("failed") and P.lots_match(map_dir, where))
            if done_before:
                print("  ya estaba compilado", flush=True)
            else:
                t0 = time.time()
                r = client.post("/api/compile", json={"mapName": name})
                if r.status_code != 200:
                    raise RuntimeError((r.get_json(silent=True) or {}).get("error", r.status_code))
                last = ""
                while True:
                    time.sleep(5)
                    st = client.get(f"/api/compile-status?map={name}").get_json() or {}
                    line = f"  {st.get('cells', 0)}/{st.get('expected', '?')} celdas"
                    if line != last:
                        print(line, flush=True)
                        last = line
                    if st.get("state") in ("done", "error", "stopped"):
                        break
                if st.get("state") != "done":
                    raise RuntimeError(st.get("error") or st.get("state"))
                if st.get("failed"):
                    raise RuntimeError(f"{len(st['failed'])} grupos de celdas fallaron; "
                                       "vuelve a lanzar compilar.py para reintentarlos")
                print(f"  compilado en {(time.time() - t0) / 60:.1f} min", flush=True)
            if not args.sin_instalar:
                r = client.post("/api/install", json={"mapName": name})
                body = r.get_json(silent=True) or {}
                if r.status_code != 200:
                    raise RuntimeError(body.get("error", r.status_code))
                print(f"  instalado como mod {body.get('modId')}", flush=True)
            results[name] = True
        except Exception as exc:  # noqa: BLE001 - se informa y se sigue
            print(f"  FALLO: {exc}", flush=True)
            results[name] = False

    print(f"\nResumen ({(time.time() - t_all) / 60:.0f} min):")
    for n, ok in results.items():
        print(f"  {n:48s} {'listo' if ok else 'FALLO'}")
    good = [n for n, ok in results.items() if ok]
    if good and not args.sin_instalar:
        print("\nMods para activar en el juego (además de Erika's Tiles):")
        print("  " + ", ".join(good))
    return 0 if all(results.values()) else 1


# Imprescindible en Windows (procesos nuevos vuelven a importar este archivo).
if __name__ == "__main__":
    sys.exit(main())
