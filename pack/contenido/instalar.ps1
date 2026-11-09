# Instalador de la Provincia de Ciudad Real para Project Zomboid (Build 42).
# Lo lanzan INSTALAR.bat y DESINSTALAR.bat; no hace falta abrirlo a mano.
#
#   instalar.ps1               copia los mods y los activa
#   instalar.ps1 -Desinstalar  los quita y los desactiva
#
# Toca solo dos cosas en tu carpeta de Zomboid:
#   - las carpetas de los mods de la provincia, dentro de Zomboid\mods
#   - la lista de mods activos (Zomboid\mods\default.txt), de la que
#     guarda antes una copia: default.txt.antes_provincia_cr
param([switch]$Desinstalar)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $here 'mods'

function Pausa { Write-Host ''; Read-Host 'Pulsa Enter para cerrar' | Out-Null }

try {
    if (-not (Test-Path $source)) {
        throw "No encuentro la carpeta 'mods' junto al instalador. Descomprime el zip entero y lanza INSTALAR.bat desde ahí (no desde dentro del zip)."
    }
    $pack = @(Get-ChildItem -Path $source -Directory | Sort-Object Name | ForEach-Object { $_.Name })
    if ($pack.Count -eq 0) { throw "La carpeta 'mods' del pack está vacía." }

    # Carpeta de Zomboid del usuario (la de partidas y mods, no la del juego).
    $zomboid = Join-Path $env:USERPROFILE 'Zomboid'
    if (-not (Test-Path $zomboid)) {
        Write-Host "No encuentro tu carpeta de Zomboid en $zomboid"
        Write-Host '(Es la que tiene las carpetas Saves, mods, Logs... Se crea al abrir el juego una vez.)'
        $zomboid = Read-Host 'Escribe la ruta de tu carpeta Zomboid'
        if (-not (Test-Path $zomboid)) { throw "Esa carpeta no existe: $zomboid" }
    }
    $mods = Join-Path $zomboid 'mods'
    New-Item -ItemType Directory -Force -Path $mods | Out-Null
    $list = Join-Path $mods 'default.txt'

    if (Get-Process -Name 'ProjectZomboid64' -ErrorAction SilentlyContinue) {
        throw 'Project Zomboid está abierto. Ciérralo y vuelve a lanzar el instalador.'
    }

    # Lista de mods activos.
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    if (Test-Path $list) {
        $text = [System.IO.File]::ReadAllText($list)
        Copy-Item $list "$list.antes_provincia_cr" -Force
    } else {
        $text = "VERSION = 1,`r`n`r`nmods`r`n{`r`n}`r`n`r`nmaps`r`n{`r`n}`r`n"
    }
    if ($text -notmatch '(?s)mods\s*\{') { $text += "`r`nmods`r`n{`r`n}`r`n" }

    function Activo($t, $id) { return $t -match ('(?m)^\s*mod\s*=\s*' + [regex]::Escape($id) + '\s*,') }

    if ($Desinstalar) {
        foreach ($id in $pack) {
            $dir = Join-Path $mods $id
            if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
            $text = [regex]::Replace($text, '(?m)^\s*mod\s*=\s*' + [regex]::Escape($id) + '\s*,\s*\r?\n', '')
        }
        [System.IO.File]::WriteAllText($list, $text, $utf8)
        Write-Host ''
        Write-Host "Desinstalado: $($pack.Count) mods quitados de $mods"
        Write-Host '(Erika''s Tiles y tus otros mods no se han tocado.)'
        Pausa
        exit 0
    }

    # Copiar los mods (si ya estaban, se sustituyen por los del pack).
    Write-Host "Copiando $($pack.Count) mods a $mods ..."
    $i = 0
    foreach ($id in $pack) {
        $i++
        Write-Progress -Activity 'Instalando la Provincia de Ciudad Real' -Status $id -PercentComplete (100 * $i / $pack.Count)
        $dst = Join-Path $mods $id
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Copy-Item -Recurse -Force (Join-Path $source $id) $dst
    }
    Write-Progress -Activity 'Instalando la Provincia de Ciudad Real' -Completed

    # Activarlos: Erika's Tiles primero, luego los de la provincia.
    $add = @()
    foreach ($id in @('Erikas_Tiles') + $pack) {
        if (-not (Activo $text $id)) { $add += "    mod = $id," }
    }
    if ($add.Count -gt 0) {
        $block = ($add -join "`r`n") + "`r`n"
        $m = [regex]::Match($text, '(?s)(mods\s*\{.*?)(\})')
        $text = $text.Substring(0, $m.Groups[2].Index) + $block + $text.Substring($m.Groups[2].Index)
    }
    [System.IO.File]::WriteAllText($list, $text, $utf8)

    Write-Host ''
    Write-Host 'Instalación terminada.' -ForegroundColor Green
    Write-Host "  $($pack.Count) mods copiados y activados en $mods"
    Write-Host '  Copia de tu lista de mods anterior: default.txt.antes_provincia_cr'
    Write-Host ''
    Write-Host 'Antes de jugar:' -ForegroundColor Yellow
    Write-Host '  1. Suscríbete en Steam a Erika''s Tiles (obligatorio):'
    Write-Host '     https://steamcommunity.com/workshop/filedetails/?id=3346506593'
    Write-Host '  2. Sube la memoria del juego (apartado 4 del LEEME).'
    Write-Host '  3. Crea una partida NUEVA.'
    Pausa
}
catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'No se ha terminado la instalación. Mira el apartado 6 del LEEME.'
    Pausa
    exit 1
}
