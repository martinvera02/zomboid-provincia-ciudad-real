# Monta el zip de la Provincia de Ciudad Real para pasárselo a tus amigos.
# Se lanza con EMPAQUETAR.bat (doble clic), desde Documentos\ProvinciaCR.
#
# Mete en el zip:
#   - los mods de la provincia que tienes instalados en Zomboid\mods
#   - lo que hay en la carpeta "contenido" (o "pack") de al lado: manual,
#     instalador...
# y lo deja en el Escritorio como ProvinciaCR_beta2.zip.
# No copia nada a carpetas temporales: escribe el zip directamente.
param(
    [string]$Mods = (Join-Path $env:USERPROFILE 'Zomboid\mods'),
    [string]$Salida = [Environment]::GetFolderPath('Desktop'),
    [string]$Nombre = 'ProvinciaCR_beta2.zip'
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
# En el repositorio lo que va dentro del zip está en pack/contenido; en la
# carpeta de trabajo (Documentos\ProvinciaCR) en pack.
$extras = Join-Path $here 'contenido'
if (-not (Test-Path $extras)) { $extras = Join-Path $here 'pack' }

# Los 41 mods de la provincia (17 pueblos y 24 carreteras).
$pueblos = @('CiudadReal', 'Puertollano', 'Almagro', 'CorralDeCalatrava', 'Bolanos', 'Daimiel',
    'Malagon', 'Argamasilla', 'Piedrabuena', 'Poblete', 'Alcolea', 'Villamayor',
    'CanadaDeCalatrava', 'CaracuelDeCalatrava', 'Infantes', 'Villahermosa', 'Horcajo')
$carreteras = @(Get-ChildItem -Path $Mods -Directory |
    Where-Object { $_.Name -like 'Enlace_*' -or $_.Name -like 'Cruce_*' } |
    ForEach-Object { $_.Name } | Sort-Object)
$lista = $pueblos + $carreteras

function Pausa { Write-Host ''; Read-Host 'Pulsa Enter para cerrar' | Out-Null }

try {
    $faltan = @($pueblos | Where-Object { -not (Test-Path (Join-Path $Mods $_)) })
    if ($faltan.Count) { throw "No están instalados en ${Mods}: $($faltan -join ', ')" }
    if (-not (Test-Path $extras)) { throw "No encuentro la carpeta 'contenido' ni 'pack' en $here" }
    if ($carreteras.Count -ne 24) {
        Write-Host "Aviso: hay $($carreteras.Count) mods de carretera (Enlace_/Cruce_), se esperaban 24." -ForegroundColor Yellow
    }

    # Todo lo que va al zip: (archivo, nombre dentro del zip).
    $items = New-Object System.Collections.Generic.List[object]
    foreach ($f in Get-ChildItem -Path $extras -File) { $items.Add(@($f.FullName, $f.Name)) }
    foreach ($id in $lista) {
        $root = Join-Path $Mods $id
        foreach ($f in Get-ChildItem -Path $root -File -Recurse) {
            $rel = $f.FullName.Substring($root.Length + 1).Replace('\', '/')
            $items.Add(@($f.FullName, "mods/$id/$rel"))
        }
    }
    $bytes = ($items | ForEach-Object { (Get-Item -LiteralPath $_[0]).Length } | Measure-Object -Sum).Sum
    Write-Host ("{0} mods, {1} archivos, {2:N1} GB sin comprimir" -f $lista.Count, $items.Count, ($bytes / 1GB))

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zipPath = Join-Path $Salida $Nombre
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    $zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
    try {
        $i = 0
        foreach ($it in $items) {
            $i++
            if ($i % 100 -eq 0 -or $i -eq $items.Count) {
                Write-Progress -Activity "Creando $Nombre" -Status "$i de $($items.Count)" -PercentComplete (100 * $i / $items.Count)
            }
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $it[0], $it[1], [System.IO.Compression.CompressionLevel]::Optimal)
        }
    } finally {
        $zip.Dispose()
        Write-Progress -Activity "Creando $Nombre" -Completed
    }
    $size = (Get-Item $zipPath).Length
    Write-Host ''
    Write-Host ("Listo: {0}  ({1:N2} GB)" -f $zipPath, ($size / 1GB)) -ForegroundColor Green
    Write-Host 'Pásaselo a tus amigos: dentro va el manual (LEEME) y el instalador.'
    Pausa
}
catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Pausa
    exit 1
}
