# Provincia de Ciudad Real para Project Zomboid

Un mapa jugable de **17 pueblos reales de la provincia de Ciudad Real** para Project Zomboid (Build 42). Cada pueblo está a escala real, con sus calles de OpenStreetMap y sus edificios del Catastro. Los pueblos están unidos por carreteras que siguen el trazado de las reales, y el campo entre ellos está relleno de cultivos, aldeas, cortijos y sitios donde buscar loot.

![La provincia en el juego](docs/img/provincia.png)

*Los 75 mapas de la beta 2: 17 pueblos, 21 carreteras de enlace y 37 mapas de campo entre ellos.*

## Qué hay en el mapa

- **Pueblos a escala real (1 tile = 2 m):** Ciudad Real con Miguelturra, Puertollano, Almagro, Bolaños de Calatrava, Daimiel, Malagón, Argamasilla de Calatrava, Piedrabuena, Poblete, Alcolea de Calatrava, Villamayor de Calatrava, Corral de Calatrava, Cañada de Calatrava, Caracuel de Calatrava, Villanueva de los Infantes, Villahermosa y Horcajo de los Montes. Son 461 celdas de 300 × 300 tiles.
- **Edificios del Catastro:** cada edificio tiene la huella oficial, su número real de plantas y su uso (vivienda, bloque, nave, comercio, edificio público). En Ciudad Real se pasa de unas 2.900 huellas en OpenStreetMap a unas 15.700.
- **Carreteras entre pueblos:** siguen la forma de la carretera real (N-420, N-430, N-401, A-43, CM-412, CM-4106…), con las distancias acortadas a menos de la mitad. De Ciudad Real a Almagro hay unos 9 km en el juego, frente a 24 km reales. Llevan campos, bosques, setos y casas de campo a los lados.
- **Cruces:** algunos pueblos se enganchan a mitad de otra carretera, como Cañada con la de Ciudad Real–Almagro.
- **El campo entre pueblos** (beta 2): ya no hay huecos vacíos. Hay parcelas irregulares de cereal, olivar, viña, monte y dehesa, con setos, arroyos y cortijos al final de caminos de tierra. También aldeas con dos o tres manzanas, plaza, iglesia, bar, tienda y ayuntamiento, y carreteras comarcales con curvas que unen unos pueblos con otros.
- **Zonas con nombre:**
  - las Tablas de Daimiel, con lagunas, carrizal, pasarelas, observatorios y el Molino de Molemocho;
  - Cabañeros, con monte, dehesa, puestos forestales con torre, aserraderos y refugios;
  - el Aeropuerto Central, con pista, terminal, torre, hangares, bomberos y hotel;
  - el Campo de Montiel, alrededor de Infantes y Villahermosa;
  - el sur, entre Puertollano, Argamasilla y Villamayor.
- **Sitios de loot:** tres bases militares, polígonos de naves, un centro comercial, zonas de ocio, ventas de carretera, gasolineras con su explanada y armerías. En Ciudad Real está además la comisaría de la Policía Nacional.
- **Monumentos de Ciudad Real hechos a mano:** la catedral, San Pedro, Santiago, la Merced, el ayuntamiento, el Hospital General y la Plaza Mayor, con materiales y formas parecidas a las reales (ver abajo).

| Antes / después del Catastro (casco de Ciudad Real) | Junta entre Poblete, el enlace y Ciudad Real |
|---|---|
| ![Catastro](docs/img/catastro_antes_despues.jpg) | ![Enlace](docs/img/enlace_poblete_ciudad_real.png) |

![Monumentos de Ciudad Real](docs/img/monumentos.png)

*Los edificios de `monumentos.py`, dibujados con `tools/vista_tbx.py`.*

## Cómo funciona

Los pueblos los genera [KnoxMap](https://github.com/spytheeuclidean-a11y/knoxmap), una herramienta de la comunidad que convierte datos de OpenStreetMap en mapas de Project Zomboid: calles, edificios con habitaciones y muebles, zombis según la población… Este proyecto es el pipeline que hay alrededor: datos españoles, colocación de los pueblos en el mundo y las carreteras que los unen.

```
 BBBike (OSM .pbf) ──┐
                     ├─ catastro_merge.py ─► .pbf con edificios del Catastro
 Catastro INSPIRE ───┘        │
 (descargar_catastro.py)      │
                              ▼
 roads.py ─► carreteras reales entre pueblos (grafo de OSM, caminos más cortos)
                              │
 layout.py / layout_add.py ─► plano: celda de cada pueblo en el mundo del juego
                              │
 provincia.py ─► con KnoxMap: genera los pueblos, los coloca y construye los enlaces
                              │
 rellenos.py ─► rellena el campo entre pueblos (y añade aldeas y sitios a los enlaces)
                              │
 compilar.py ─► compila e instala los 75 mapas como mods
                              │
 tools/check_*.py ─► comprueba solapes y que cada carretera encaje en su junta
```

### Las partes que no son triviales

- **Edificios del Catastro en OSM** (`catastro_merge.py`). Lee el GML INSPIRE (EPSG:25830), toma las plantas sobre rasante de las partes de cada edificio, traduce el uso a etiquetas `building=*` y sustituye los edificios de OSM que se solapan. El resultado es un `.pbf` normal que KnoxMap lee sin saber que viene del Catastro.
- **Colocación** (`layout.py`). Los pueblos no se pueden acercar más de lo que miden, así que se escalan las posiciones reales de forma uniforme y, si dos chocan, el segundo se aparta en la dirección real entre ellos. Así se conserva la forma de la provincia. Todos van con el norte arriba (sin el giro que KnoxMap aplica para alinear calles), para que las carreteras salgan de cada pueblo en su dirección real.
- **Juntas exactas** (`provincia.py`, `snap_link`). KnoxMap endereza las calles de cada pueblo y las desplaza cerca de los bordes, así que un enlace trazado sobre la carretera real llega desviado entre 150 y 250 tiles. Por eso cada enlace se engancha a las carreteras que el pueblo generado tiene de verdad en sus bordes, leídas de su `road_hierarchy.bmp`. Se eligen las dos salidas a la vez: grandes, de clase parecida (que una autovía no acabe en un callejón), cerca de la salida real y con el enlace más compacto. El desplazamiento de cada extremo se reparte a lo largo de la carretera para conservar su forma.
- **Dos mapas no pueden compartir celda.** Cada enlace es un mapa rectangular aparte. Si la recta no cabe sin pisar otro mapa, la carretera se busca con A* por las celdas libres (penalizando los giros) y se construye en tramos rectos, cada uno su propio mapa. Los enlaces muy largos se hacen siempre así: en un solo rectángulo serían cientos de celdas de campo vacío.
- **Cruces.** Para enganchar un pueblo a mitad de un enlace, se rehace el enlace con un ramal que sale de su carretera hasta el borde que mira al pueblo, y después se construye la carretera nueva hasta ese ramal.
- **Monumentos** (`monumentos.py`). Se lanza después de generar y antes de compilar, y sustituye el `.tbx` de unos edificios concretos dentro de la misma parcela. Las iglesias se rehacen planta a planta: nave alta, torre con la escalera dentro y chapitel de pizarra o teja. Los muros salen de los materiales del juego, cada uno con sus huecos de ventana y sus piñones. El ayuntamiento lleva seis picos de pizarra, y el hospital y la Plaza Mayor cambian de fachada sin tocar su interior. `tools/vista_tbx.py` los dibuja en isométrico con los tiles del juego para revisarlos sin compilar.
- **Nombres del Catastro.** Al sustituir los edificios de OSM por los del Catastro, cada huella del Catastro hereda el nombre y el tipo (iglesia, hospital, ayuntamiento…) del edificio de OSM con el que coincide. Sin eso, Ciudad Real tenía una sola iglesia.
- **El campo entre pueblos** (`rellenos.py`). Los huecos cerrados entre mapas se buscan en la rejilla de celdas. Las zonas abiertas (Cabañeros, el aeropuerto, el Campo de Montiel, el sur) son rectángulos con nombre, de los que se toman las celdas libres. El proceso para cada zona:
  - **Salidas:** se leen las calles de cada pueblo vecino que llegan al borde y los puntos de los enlaces vecinos donde puede salir un ramal.
  - **Carreteras:** se trazan con Dijkstra/A* sobre una rejilla de 10 tiles, que penaliza los giros y pegarse al borde del mapa y premia aprovechar carreteras ya trazadas. Luego se suavizan y se les da un serpenteo para que no sean rectas.
  - **Uniones:** donde dos zonas se tocan, una "puerta" en el borde hace que las dos mitades de la carretera salgan del mismo punto.
  - **Campo:** el terreno son parcelas de Voronoi, y los sitios (bases, ventas, aldeas…) se colocan a lo largo de las carreteras. Cada zona se parte en rectángulos, que son mapas aparte.
  - **Enlaces:** el mismo script rehace los enlaces para añadirles los ramales, aldeas y ventas. También alarga dentro del enlace las calles grandes de un pueblo que acababan en su borde sin nada al otro lado.
- **Mapa de papel.** KnoxMap dibuja el mapa del juego con la descarga de OSM, y un enlace no la tiene; sin más, solo saldrían sus casas. Al construir cada enlace se le pasa su propio dibujo, así que la carretera sale en el mapa de papel en el mismo sitio que en el suelo.

## Reproducirlo

Hace falta Windows con Project Zomboid (Build 42) y KnoxMap instalado. Su `Setup.bat` saca los tiles de tu propia copia del juego. Los scripts usan el Python de KnoxMap y se lanzan desde su carpeta.

1. **Datos de OpenStreetMap:** un recorte en formato PBF de [extract.bbbike.org](https://extract.bbbike.org) que cubra los pueblos. El `.pbf` ya mezclado con el Catastro que usa esta beta está en `data/provincia_osm_catastro.osm.pbf` (25 MB), así que puedes saltarte los pasos 1 y 2.
2. **Catastro:**
   ```
   python scripts/descargar_catastro.py datos/catastro 13900 13056 13071 ...
   python scripts/catastro_merge.py recorte.osm.pbf provincia.osm.pbf datos/catastro/*/
   ```
   `python scripts/descargar_catastro.py --lista 13` muestra los códigos de cada municipio.
3. **Plano** (opcional; `data/layout.json` es el de esta beta):
   ```
   python scripts/roads.py provincia.osm.pbf enlaces.json
   python scripts/layout.py <KnoxMap> enlaces.json salida 0.45
   python scripts/layout_add.py <KnoxMap> layout.json enlaces.json layout_nuevo.json Pueblo1,Pueblo2
   ```
4. **Generar**, desde la carpeta de KnoxMap y con su `output` vacío:
   ```
   .venv\Scripts\python.exe <repo>\scripts\provincia.py . provincia.osm.pbf <repo>\data\layout.json ^
       --pueblos todos --enlaces todos ^
       --cruces "CanadaDeCalatrava>CiudadReal-Almagro,Malagon>Piedrabuena-Alcolea"
   ```
5. **Compilar e instalar:** `.venv\Scripts\python.exe <repo>\scripts\compilar.py . <repo>\data\layout.json`
6. **Monumentos de Ciudad Real** (antes de compilar, o después con `compilar.py --solo CiudadReal --forzar`):
   `.venv\Scripts\python.exe <repo>\scripts\monumentos.py . --vistas vistas`.
   `scripts/ACTUALIZAR_CIUDAD_REAL.bat` hace generar + monumentos + compilar de una vez si los scripts están en `Documentos\ProvinciaCR`.
7. **Rellenar el campo entre pueblos:** `.venv\Scripts\python.exe <repo>\scripts\rellenos.py . <repo>\data\layout.json` (`--solo-plan` solo dibuja el plano en un PNG). Deja en `rellenos_mapas.txt` la lista de mapas nuevos o rehechos, para compilarlos con `compilar.py --lista rellenos_mapas.txt --forzar`. `scripts/RELLENAR.bat` hace las dos cosas.
8. **Comprobar:** `python tools/check_bordes.py <KnoxMap>\output`; `python tools/mapa_completo.py <KnoxMap>\output mapa.png` dibuja todo el mundo junto.
9. **Empaquetar para otros jugadores:** `pack\EMPAQUETAR.bat` crea un zip con los mods instalados, el [manual de instalación](pack/contenido/LEEME%20-%20Manual%20de%20instalacion.txt) y un instalador que los copia y activa sin tocar los demás mods del jugador.

Los pueblos y sus cajas están en `scripts/build_cr.py` (`PUEBLOS`).

## Limitaciones conocidas

- Los interiores son los que inventa KnoxMap, y en los cascos antiguos las manzanas no quedan cerradas del todo.
- El campo es genérico, no el terreno real, y las aldeas, ventas y bases son inventadas. Más allá de los últimos campos no hay suelo.
- Horcajo de los Montes está desplazado de su sitio para no caer encima del condado de Knox original. Villanueva de los Infantes y Villahermosa están más cerca de Almagro que en la realidad.
- Algunas calles de pueblo acaban de golpe en el borde del pueblo (cortes de 5–10 tiles que marca `check_bordes.py`).
- No está probado en multijugador.

## Créditos y licencias

- Código de este repositorio: licencia MIT (ver `LICENSE`).
- Datos de mapa: © colaboradores de OpenStreetMap, [ODbL](https://www.openstreetmap.org/copyright).
- Edificios: © Dirección General del Catastro, datos INSPIRE.
- [KnoxMap](https://github.com/spytheeuclidean-a11y/knoxmap) (MIT) genera los mapas; no se incluye aquí.
- Project Zomboid es de The Indie Stone. Este proyecto no está relacionado con ellos.
