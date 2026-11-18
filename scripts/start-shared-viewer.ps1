param([string]$Directory = 'artifacts/shared-viewer-preview', [int]$Port = 8770)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$viewerPath = if ([System.IO.Path]::IsPathRooted($Directory)) { $Directory } else { Join-Path $projectRoot $Directory }
$viewerPath = (Resolve-Path -LiteralPath $viewerPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $viewerPath 'index.html'))) {
    throw 'Prepare the shared viewer export first. See shared-viewer/README.md.'
}
Write-Host "Shared viewer preview: http://127.0.0.1:$Port/"
Write-Host 'This is a local preview. GitHub Pages provides hosting after publication.'
& $python -m http.server $Port --bind 127.0.0.1 --directory $viewerPath
