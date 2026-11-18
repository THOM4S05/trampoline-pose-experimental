param([string]$PublicUrl = 'https://desktop-qfvrcme.tail48ad3d.ts.net:8443', [int]$Port = 8766)
$ErrorActionPreference = 'Stop'
$experimentalRoot = Split-Path -Parent $PSScriptRoot
$experimentalPython = Join-Path $experimentalRoot '.venv\Scripts\python.exe'
$experimentalScript = Join-Path $experimentalRoot 'experiments\twist-width-copy\scripts\serve_twist.py'
Set-Location -LiteralPath $experimentalRoot
& $experimentalPython $experimentalScript --port $Port --public-url $PublicUrl
exit $LASTEXITCODE
