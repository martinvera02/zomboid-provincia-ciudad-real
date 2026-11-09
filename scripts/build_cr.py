"""Genera pueblos de Ciudad Real con KnoxMap a partir de un PBF local.

Uso (Windows, desde la carpeta de KnoxMap ya instalada):
    .venv\\Scripts\\python.exe build_cr.py . zona_ciudad_real_osm_catastro.osm.pbf Almagro
    .venv\\Scripts\\python.exe build_cr.py . zona_ciudad_real_osm_catastro.osm.pbf CiudadReal,Almagro,Bolanos
    .venv\\Scripts\\python.exe build_cr.py . zona_ciudad_real_osm_catastro.osm.pbf todos

Uso general:  python build_cr.py <ruta knoxmap> <ruta .osm.pbf> [pueblos] [m_por_tile]

<pueblos> es uno o varios nombres de PUEBLOS separados por comas, o "todos"
(por defecto CiudadReal). El PBF tiene que cubrirlos.

Variables opcionales:
    FILL=1  rellena huecos en filas de casas (fill_frontage). Por defecto 0:
            con los edificios del Catastro casi no faltan.

KnoxMap normalmente descarga un extracto de Geofabrik; aquí se le da el PBF
de BBBike directamente, sustituyendo la búsqueda y la descarga del extracto.
Cada pueblo queda en <knoxmap>/output/<pueblo>, listo para Compile e Install
desde la ventana de KnoxMap. No pulses Generate en la ventana para estos mapas:
volvería a descargar OSM y se perderían los edificios del Catastro.
"""
import json
import os
import sys
import time

# (sur, oeste, norte, este): el núcleo urbano según el Catastro, con 300 m de margen
PUEBLOS = {
    "CiudadReal": (38.9522, -3.9562, 39.0061, -3.8749),  # con Miguelturra, 12 x 11 celdas
    "Puertollano": (38.6744, -4.1285, 38.7130, -4.0663),  # 10 x 8
    "Almagro": (38.8783, -3.7245, 38.8990, -3.6956),  # 5 x 4
    "CorralDeCalatrava": (38.8510, -4.0888, 38.8645, -4.0738),  # 3 x 3
    "Bolanos": (38.8928, -3.6803, 38.9225, -3.6491),
    "Daimiel": (39.0579, -3.6266, 39.0849, -3.5966),
    "Malagon": (39.1554, -3.8654, 39.1788, -3.8364),
    "Argamasilla": (38.7115, -4.0931, 38.7385, -4.0655),
    "Piedrabuena": (39.0264, -4.1869, 39.0444, -4.1626),
    "Poblete": (38.9298, -3.9904, 38.9505, -3.9673),
    "Alcolea": (38.9781, -4.1279, 38.9934, -4.1048),
    "Villamayor": (38.7805, -4.1468, 38.7940, -4.1318),
    "CanadaDeCalatrava": (38.8499, -4.0267, 38.8580, -4.0151),
    "CaracuelDeCalatrava": (38.8399, -4.0692, 38.8498, -4.0588),
    "Infantes": (38.7259, -3.0251, 38.7448, -2.9998),  # Villanueva de los Infantes
    "Villahermosa": (38.7407, -2.8834, 38.7578, -2.8581),
    "Horcajo": (39.3211, -4.6606, 39.3337, -4.6396),  # Horcajo de los Montes
}


def main() -> int:
    KNOX = os.path.abspath(sys.argv[1])
    PBF = os.path.abspath(sys.argv[2])
    ASKED = sys.argv[3] if len(sys.argv) > 3 else "CiudadReal"
    MPT = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0

    names = list(PUEBLOS) if ASKED.lower() == "todos" else [n.strip() for n in ASKED.split(",") if n.strip()]
    unknown = [n for n in names if n not in PUEBLOS]
    if unknown:
        sys.exit(f"Pueblo desconocido: {', '.join(unknown)}. Opciones: {', '.join(PUEBLOS)} o todos")

    os.environ["KNOXMAP_OSM_SOURCE"] = "extract"
    sys.path.insert(0, KNOX)
    os.chdir(KNOX)

    from generator import extract  # noqa: E402

    REGION = {"id": "ciudad-real", "name": "Ciudad Real (BBBike)", "url": "local"}
    extract._index = lambda refresh_ok=True: {"features": []}
    extract.regions_for = lambda *a, **k: [REGION]
    extract._download = lambda region, say, should_stop: PBF

    import app as knoxapp  # noqa: E402

    # true_map 0: KnoxMap lo recomienda a 2 m/tile y con densidad europea.
    SETTINGS = {"true_map": 0, "fill_frontage": int(os.environ.get("FILL", "0"))}

    client = knoxapp.app.test_client()

    def build(name: str) -> bool:
        bbox = dict(zip(("south", "west", "north", "east"), PUEBLOS[name]))
        print(f"\n=== {name} ===", flush=True)

        t = time.time()
        r = client.post("/api/generate", json={**bbox, "metersPerTile": MPT,
                                               "mapName": name, "settings": SETTINGS})
        body = r.get_json() or {}
        if r.status_code != 200:
            print(f"generate FALLO ({r.status_code}): {body.get('error', body)}")
            return False
        print(f"generate ok en {time.time() - t:.0f}s: {body.get('cellsX')} x {body.get('cellsY')} celdas",
              flush=True)

        t = time.time()
        r = client.post("/api/buildings", json={"mapName": name})
        body = r.get_json() or {}
        if r.status_code != 200:
            print(f"buildings FALLO ({r.status_code}): {body.get('error', body)}")
            if isinstance(body.get("log"), str):
                print(body["log"][-3000:])
            return False
        print(f"buildings ok en {time.time() - t:.0f}s", flush=True)
        return True

    results = {n: build(n) for n in names}
    print("\nResumen:")
    for n, ok in results.items():
        print(f"  {n:22s} {'listo para Compile e Install' if ok else 'FALLO'}")
    return 0 if all(results.values()) else 1


# Imprescindible en Windows: KnoxMap reparte trabajo en procesos nuevos, y cada
# uno vuelve a importar este archivo. Sin esta guarda, cada proceso volvería a
# generar los pueblos y chocarían entre sí ("already being generated").
if __name__ == "__main__":
    if os.environ.get("KNOX_SPAWN_TEST"):  # para probar en Linux como en Windows
        import multiprocessing
        multiprocessing.set_start_method("spawn", force=True)
    sys.exit(main())
