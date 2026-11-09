@echo off
rem Regenera Ciudad Real con el .pbf nuevo, rehace los monumentos y lo
rem vuelve a compilar e instalar. Cierra antes la ventana de KnoxMap.
cd /d "%~dp0..\KnoxMap"
echo === 1/3 Generar Ciudad Real ===
.venv\Scripts\python.exe ..\ProvinciaCR\provincia.py . ..\ProvinciaCR\provincia_osm_catastro.osm.pbf ..\ProvinciaCR\layout.json --pueblos CiudadReal
if errorlevel 1 goto fallo
echo === 2/3 Monumentos ===
.venv\Scripts\python.exe ..\ProvinciaCR\monumentos.py . --vistas ..\ProvinciaCR\vistas_monumentos
if errorlevel 1 goto fallo
echo === 3/3 Compilar e instalar ===
.venv\Scripts\python.exe ..\ProvinciaCR\compilar.py . ..\ProvinciaCR\layout.json --solo CiudadReal --forzar
if errorlevel 1 goto fallo
echo.
echo Listo. Las vistas de cada edificio estan en ProvinciaCR\vistas_monumentos
pause
exit /b 0
:fallo
echo.
echo Algo ha fallado: copia lo de arriba y pasamelo.
pause
exit /b 1
