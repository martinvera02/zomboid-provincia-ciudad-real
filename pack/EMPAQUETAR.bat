@echo off
rem Crea ProvinciaCR_beta1.zip en el Escritorio con los mods instalados, el manual y el instalador.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0empaquetar.ps1"
