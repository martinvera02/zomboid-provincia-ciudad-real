@echo off
rem Rellena los huecos entre Ciudad Real y los pueblos de alrededor (campo,
rem carreteras, centro comercial, poligono, base militar, ventas...), y
rem compila e instala los mapas nuevos y los enlaces a los que se les ha
rem puesto un ramal. Cierra antes la ventana de KnoxMap.
cd /d "%~dp0..\KnoxMap"
echo === 1/2 Generar los rellenos ===
.venv\Scripts\python.exe ..\ProvinciaCR\rellenos.py . ..\ProvinciaCR\layout.json
if errorlevel 1 goto fallo
echo === 2/2 Compilar e instalar ===
.venv\Scripts\python.exe ..\ProvinciaCR\compilar.py . ..\ProvinciaCR\layout.json --lista ..\ProvinciaCR\rellenos_mapas.txt --forzar
if errorlevel 1 goto fallo
echo.
echo Listo. El plano de lo que se ha hecho esta en ProvinciaCR\rellenos_plan.png
echo Los mods nuevos (Relleno_...) ya quedan activados en la lista por defecto.
pause
exit /b 0
:fallo
echo.
echo Algo ha fallado: copia lo de arriba y pasamelo.
pause
exit /b 1
