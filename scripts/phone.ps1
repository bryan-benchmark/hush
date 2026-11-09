# Open the labeler on a phone that is not on this network.
# This computer stays on. The printed https link is the one to open.
# Localhost on this computer does not ask for the code.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root "apps\monitor\.env.local"
if (-not (Test-Path $envFile)) {
  Write-Error "Missing apps/monitor/.env.local"
}
$exeDir = Join-Path $env:LOCALAPPDATA "ohush"
$exe = Join-Path $exeDir "cloudflared.exe"
if (-not (Test-Path $exe)) {
  New-Item -ItemType Directory -Force -Path $exeDir | Out-Null
  Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $exe
}
& $exe tunnel --url http://127.0.0.1:3010
